"""Set up and reach the Make.com scenario that posts to Facebook and Instagram.

Make's API needs a token (secret MAKE_API_TOKEN, made in Make under Profile > API access).
GitHub Actions can reach Make, so the whole scenario is built from here:

python -m engine.make discover   # print the account, connections and Make's own module names
python -m engine.make build      # create the webhook and the scenario, send a test, switch it on

The repo is public and so are its Actions logs: never print the webhook address or the token.
"""

import argparse
import json
import os
import sys

import requests

ZONES = ["eu1.make.com", "eu2.make.com", "us1.make.com", "us2.make.com"]
HOOK_NAME = "HOTT posts"
SCENARIO_NAME = "HOTT auto-post: webhook to Facebook and Instagram"
FACEBOOK_APP = "facebook-pages"
INSTAGRAM_APP = "instagram-business"


class MakeError(RuntimeError):
    pass


class Make:
    def __init__(self, token=None):
        self.token = token or os.environ["MAKE_API_TOKEN"]
        self.base = None
        for zone in ([os.environ["MAKE_ZONE"]] if os.environ.get("MAKE_ZONE") else ZONES):
            response = requests.get(f"https://{zone}/api/v2/users/me", headers=self._headers(), timeout=30)
            if response.ok:
                self.base = f"https://{zone}/api/v2"
                self.zone = zone
                break
        if not self.base:
            raise MakeError("The Make token was refused in every zone. Check MAKE_API_TOKEN.")

    def _headers(self):
        return {"Authorization": f"Token {self.token}", "Content-Type": "application/json"}

    def call(self, method, path, **kwargs):
        response = requests.request(method, f"{self.base}{path}", headers=self._headers(), timeout=60, **kwargs)
        if not response.ok:
            raise MakeError(f"{method} {path} -> {response.status_code}: {response.text[:800]}")
        return response.json() if response.content else {}

    def team_id(self):
        if os.environ.get("MAKE_TEAM_ID"):
            return int(os.environ["MAKE_TEAM_ID"])
        for org in self.call("GET", "/organizations")["organizations"]:
            teams = self.call("GET", "/teams", params={"organizationId": org["id"]})["teams"]
            if teams:
                self.organization = org["id"]
                return teams[0]["id"]
        raise MakeError("No Make team found.")

    def hooks(self, team):
        return self.call("GET", "/hooks", params={"teamId": team})["hooks"]

    def connections(self, team):
        return self.call("GET", "/connections", params={"teamId": team})["connections"]


def webhook_url():
    """The address posts are sent to: the secret if set, else looked up in Make with the API token."""
    if os.environ.get("MAKE_WEBHOOK_URL"):
        return os.environ["MAKE_WEBHOOK_URL"]
    if not os.environ.get("MAKE_API_TOKEN"):
        return None
    make = Make()
    for hook in make.hooks(make.team_id()):
        if hook["name"] == HOOK_NAME:
            if os.environ.get("GITHUB_ACTIONS"):
                print(f"::add-mask::{hook['url']}")  # keep it out of the public logs
            return hook["url"]
    return None


def enabled():
    return bool(os.environ.get("MAKE_WEBHOOK_URL") or os.environ.get("MAKE_API_TOKEN"))


def _template_modules(make, app):
    """Module names and fields from Make's public templates that use an app, so the blueprint matches Make."""
    found = {}
    templates = make.call("GET", "/templates", params={"public": "true", "usedApps[]": app, "pg[limit]": 15,
                                                       "organizationId": getattr(make, "organization", "")})["templates"]
    for template in templates:
        public_id = template.get("approvedId") or template.get("publishedId")
        try:
            blueprint = make.call("GET", f"/templates/{template['id']}/blueprint",
                                  params={"templatePublicId": public_id, "forUse": "true"})["blueprint"]
        except MakeError:
            continue
        for module in _walk(blueprint.get("flow", [])):
            name = module.get("module", "")
            if name.startswith(app + ":") and name not in found:
                found[name] = {"version": module.get("version"), "parameters": module.get("parameters"),
                               "mapper": module.get("mapper"), "template": template.get("name")}
    return found


def _walk(flow):
    for module in flow:
        yield module
        for route in module.get("routes", []):
            yield from _walk(route.get("flow", []))


def discover():
    make = Make()
    team = make.team_id()
    print(f"Zone: {make.zone}  Team: {team}")
    print("\nConnections:")
    for connection in make.connections(team):
        # Only the app, not the account names: these logs are public.
        print(f"  {connection['id']}: {connection.get('accountName')}")
    print("\nHooks:")
    for hook in make.hooks(team):
        print(f"  {hook['id']}: {hook['name']} ({hook.get('typeName')}, scenario {hook.get('scenarioId')})")
    print("\nScenarios:")
    for scenario in make.call("GET", "/scenarios", params={"teamId": team})["scenarios"]:
        print(f"  {scenario['id']}: {scenario['name']} active={scenario.get('isActive')}")
        try:
            flow = make.call("GET", f"/scenarios/{scenario['id']}/blueprint")["response"]["blueprint"]["flow"]
        except (MakeError, KeyError) as error:
            print(f"    blueprint unreadable: {str(error)[:200]}")
            continue
        for module in _walk(flow):
            name = module.get("module", "")
            print(f"    {name} v{module.get('version')}")
            if name.split(":")[0] in (FACEBOOK_APP, INSTAGRAM_APP, "gateway"):
                print(f"      parameter keys: {sorted((module.get('parameters') or {}).keys())}")
                print(f"      mapper: {json.dumps(module.get('mapper'))[:900]}")
    for app in (FACEBOOK_APP, INSTAGRAM_APP, "gateway"):
        print(f"\nModules of {app} seen in public templates:")
        try:
            for name, info in _template_modules(make, app).items():
                print(f"  {name} v{info['version']}  ({info['template']})")
                print(f"    parameters: {json.dumps(info['parameters'])[:600]}")
                print(f"    mapper: {json.dumps(info['mapper'])[:900]}")
        except MakeError as error:
            print(f"  could not read templates: {error}")


def _pick_connection(connections, app):
    matches = [c for c in connections if (c.get("accountName") or "").startswith(app)]
    if not matches:
        raise MakeError(f"No {app} connection in Make. Connect it in Make first (Connections > Create).")
    return matches[0]["id"]


def blueprint(hook_id, facebook_conn, instagram_conn):
    """Webhook -> Facebook photo post -> Instagram photo post. Test samples (test=true) stop at the filter."""
    not_a_test = {"name": "Real posts only", "conditions": [[{"a": "{{1.test}}", "o": "boolean:equal", "b": "false"}]]}
    spec = json.loads(os.environ.get("MAKE_MODULES") or "{}")
    facebook = spec.get("facebook", {"module": f"{FACEBOOK_APP}:CreatePostWithPhotos", "version": 1, "mapper": {
        "page_id": os.environ.get("FACEBOOK_PAGE_ID", ""),
        "photos": [{"url": "{{1.image_url}}"}],
        "message": "{{1.caption}}",
    }})
    instagram = spec.get("instagram", {"module": f"{INSTAGRAM_APP}:CreatePostPhoto", "version": 1, "mapper": {
        "accountId": os.environ.get("INSTAGRAM_ACCOUNT_ID", ""),
        "image_url": "{{1.image_url}}",
        "caption": "{{1.caption}}",
    }})
    flow = [
        {"id": 1, "module": "gateway:CustomWebHook", "version": 1,
         "parameters": {"hook": hook_id, "maxResults": 1}, "mapper": {},
         "metadata": {"designer": {"x": 0, "y": 0}}},
        {"id": 2, "module": facebook["module"], "version": facebook["version"],
         "parameters": {"__IMTCONN__": facebook_conn}, "mapper": facebook["mapper"], "filter": not_a_test,
         "metadata": {"designer": {"x": 300, "y": 0}}},
        {"id": 3, "module": instagram["module"], "version": instagram["version"],
         "parameters": {"__IMTCONN__": instagram_conn}, "mapper": instagram["mapper"],
         "metadata": {"designer": {"x": 600, "y": 0}}},
    ]
    return {"name": SCENARIO_NAME, "flow": flow, "metadata": {
        "version": 1, "scenario": {"roundtrips": 1, "maxErrors": 3, "autoCommit": True, "sequential": True}}}


def build(activate=True):
    from engine import notify
    make = Make()
    team = make.team_id()
    connections = make.connections(team)
    facebook_conn = _pick_connection(connections, FACEBOOK_APP)
    instagram_conn = _pick_connection(connections, INSTAGRAM_APP)

    hook = next((h for h in make.hooks(team) if h["name"] == HOOK_NAME), None)
    if not hook:
        hook = make.call("POST", "/hooks", json={"name": HOOK_NAME, "teamId": str(team), "typeName": "gateway-webhook",
                                                 "method": False, "headers": False, "stringify": False})["hook"]
        print(f"Created webhook {hook['id']}.")
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::add-mask::{hook['url']}")

    # Teach the webhook the post's fields with a test sample, which the filter keeps off the Page.
    sample = {"image_url": "https://raw.githubusercontent.com/MoshikTwig/hott-reels-engine/main/assets/logo.png",
              "caption": "Test from the Head of the Table Talk engine", "headline": "TEST", "test": True}
    requests.post(hook["url"], json=sample, timeout=60).raise_for_status()

    existing = [s for s in make.call("GET", "/scenarios", params={"teamId": team})["scenarios"]
                if s["name"] == SCENARIO_NAME]
    body = {"blueprint": json.dumps(blueprint(hook["id"], facebook_conn, instagram_conn)),
            "scheduling": json.dumps({"type": "immediately"})}
    if existing:
        scenario = make.call("PATCH", f"/scenarios/{existing[0]['id']}", json=body)["scenario"]
        print(f"Updated scenario {scenario['id']}.")
    else:
        scenario = make.call("POST", "/scenarios", params={"confirmed": "true"},
                             json={**body, "teamId": team})["scenario"]
        print(f"Created scenario {scenario['id']}.")
    if activate:
        make.call("POST", f"/scenarios/{scenario['id']}/start")
        print("Scenario is on.")
    notify.send_text(f"Make scenario is built{' and switched on' if activate else ''}. "
                     "Posts will now go to Facebook and Instagram through Make.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["discover", "build"])
    parser.add_argument("--no-activate", action="store_true")
    args = parser.parse_args()
    try:
        discover() if args.action == "discover" else build(activate=not args.no_activate)
    except MakeError as error:
        print(f"Make error: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
