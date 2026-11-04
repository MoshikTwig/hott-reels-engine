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
import re
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
                print(f"::add-mask::{hook['url']}", flush=True)  # keep it out of the public logs
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
            elif name.startswith("http:"):
                # Field names and short settings only: URLs, headers and bodies may hold private values.
                params = module.get("parameters") or {}
                mapper = module.get("mapper") or {}
                short = lambda d: {k: (v if isinstance(v, (bool, int)) or (isinstance(v, str) and len(v) < 20
                                       and k not in ("url", "data", "headers", "qs")) else type(v).__name__)
                                   for k, v in d.items()}
                print(f"      parameters: {short(params)}")
                print(f"      mapper: {short(mapper)}")
    for app in (FACEBOOK_APP, INSTAGRAM_APP, "gateway"):
        print(f"\nModules of {app} seen in public templates:")
        try:
            for name, info in _template_modules(make, app).items():
                print(f"  {name} v{info['version']}  ({info['template']})")
                print(f"    parameters: {json.dumps(info['parameters'])[:600]}")
                print(f"    mapper: {json.dumps(info['mapper'])[:900]}")
        except MakeError as error:
            print(f"  could not read templates: {error}")


def _pick_connection(connections, word, fallback=None):
    matches = [c["id"] for c in connections if word in (c.get("accountName") or "")]
    if matches:
        return matches[0]
    if fallback:
        return fallback
    raise MakeError(f"No {word} connection in Make yet. Create it in Make under Connections.")


def _chosen_ids(make, scenario_id):
    """The Page and Instagram account picked in Make's editor, so a rebuild keeps them."""
    flow = make.call("GET", f"/scenarios/{scenario_id}/blueprint")["response"]["blueprint"]["flow"]
    ids = {}
    for module in _walk(flow):
        mapper = module.get("mapper") or {}
        if mapper.get("page_id"):
            ids["page_id"] = mapper["page_id"]
        if mapper.get("accountId"):
            ids["accountId"] = mapper["accountId"]
    return ids


def blueprint(hook_id, facebook_conn, instagram_conn, page_id="", account_id=""):
    """Webhook -> Facebook photo post -> Instagram photo post. Test samples (test=true) stop at the filter.

    Module names and fields as Make exports them (facebook-pages:CreatePostWithPhotos v6,
    instagram-business:CreatePostPhoto v1).
    """
    not_a_test = {"name": "Real posts only", "conditions": [[{"a": "{{1.test}}", "o": "boolean:equal", "b": "false"}]]}
    flow = [
        {"id": 1, "module": "gateway:CustomWebHook", "version": 1,
         "parameters": {"hook": hook_id, "maxResults": 1}, "mapper": {},
         "metadata": {"designer": {"x": 0, "y": 0}}},
        {"id": 2, "module": f"{FACEBOOK_APP}:CreatePostWithPhotos", "version": 6,
         "parameters": {"__IMTCONN__": facebook_conn},
         "mapper": {"page_id": page_id, "photos": [{"url": "{{1.image_url}}", "type": "url"}],
                    "message": "{{1.caption}}"},
         "filter": not_a_test, "metadata": {"designer": {"x": 300, "y": 0}}},
        {"id": 3, "module": f"{INSTAGRAM_APP}:CreatePostPhoto", "version": 1,
         "parameters": {"__IMTCONN__": instagram_conn},
         "mapper": {"accountId": account_id, "image_url": "{{1.image_url}}", "caption": "{{1.caption}}"},
         "metadata": {"designer": {"x": 600, "y": 0}}},
    ]
    return {"name": SCENARIO_NAME, "flow": flow, "metadata": {
        "version": 1, "scenario": {"roundtrips": 1, "maxErrors": 3, "autoCommit": True, "sequential": True}}}


def build(activate=True):
    from engine import notify
    make = Make()
    team = make.team_id()
    connections = make.connections(team)
    # Both Facebook Pages and Instagram for Business (Facebook login) connections are type "facebook".
    # The one made first is for the Page, the newest one for Instagram; the editor shows both to check.
    facebook_ids = sorted(c["id"] for c in connections if c.get("accountName") == "facebook")
    facebook_conn = facebook_ids[0] if facebook_ids else _pick_connection(connections, "facebook")
    instagram_conn = _pick_connection(connections, "instagram", fallback=facebook_ids[-1] if facebook_ids else None)

    hook = next((h for h in make.hooks(team) if h["name"] == HOOK_NAME), None)
    if hook and not hook.get("scenarioId"):
        # Not in use yet: replace it, so an address that ever showed up in a log is never the live one.
        make.call("DELETE", f"/hooks/{hook['id']}", params={"confirmed": "true"})
        hook = None
    if not hook:
        hook = make.call("POST", "/hooks", json={"name": HOOK_NAME, "teamId": str(team), "typeName": "gateway-webhook",
                                                 "method": False, "headers": False, "stringify": False})["hook"]
        print(f"Created webhook {hook['id']}.")
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::add-mask::{hook['url']}", flush=True)

    existing = [s for s in make.call("GET", "/scenarios", params={"teamId": team})["scenarios"]
                if s["name"] == SCENARIO_NAME]
    chosen = _chosen_ids(make, existing[0]["id"]) if existing else {}
    page_id = os.environ.get("FACEBOOK_PAGE_ID") or chosen.get("page_id", "")
    account_id = os.environ.get("INSTAGRAM_ACCOUNT_ID") or chosen.get("accountId", "")
    body = {"blueprint": json.dumps(blueprint(hook["id"], facebook_conn, instagram_conn, page_id, account_id)),
            "scheduling": json.dumps({"type": "immediately"})}
    if existing:
        scenario = make.call("PATCH", f"/scenarios/{existing[0]['id']}", json=body)["scenario"]
        print(f"Updated scenario {scenario['id']}.")
    else:
        scenario = make.call("POST", "/scenarios", params={"confirmed": "true"},
                             json={**body, "teamId": team})["scenario"]
        print(f"Created scenario {scenario['id']}.")
    link = f"https://{make.zone}/{team}/scenarios/{scenario['id']}/edit"

    # Teach the webhook the post's fields with a test sample; the filter keeps it off the Page.
    sample = {"image_url": "https://raw.githubusercontent.com/MoshikTwig/hott-reels-engine/main/assets/logo.png",
              "caption": "Test from the Head of the Table Talk engine", "headline": "TEST", "test": True}
    try:
        answer = requests.post(hook["url"], json=sample, timeout=60)
        print(f"Test sample sent to the webhook: HTTP {answer.status_code}")
    except requests.RequestException:
        print("Test sample could not be sent to the webhook.")
    if not (page_id and account_id):
        print("The Page and Instagram account still need picking in Make's editor, so the scenario stays off.")
        notify.send_text("Make scenario is built. Open it, click the Facebook module and pick the Page, click the "
                         f"Instagram module and pick the account, then Save:\n{link}")
        return
    if activate:
        make.call("POST", f"/scenarios/{scenario['id']}/start")
        print("Scenario is on.")
    notify.send_text(f"Make scenario is built{' and switched on' if activate else ''}. "
                     f"Posts now go to Facebook and Instagram through Make.\n{link}")

def activate():
    """Check what was picked in Make's editor, without changing it, then switch the scenario on."""
    from engine import notify
    make = Make()
    team = make.team_id()
    scenario = next((s for s in make.call("GET", "/scenarios", params={"teamId": team})["scenarios"]
                     if s["name"] == SCENARIO_NAME), None)
    if not scenario:
        raise MakeError("The scenario doesn't exist yet. Run build first.")
    flow = make.call("GET", f"/scenarios/{scenario['id']}/blueprint")["response"]["blueprint"]["flow"]
    problems = []
    for module in _walk(flow):
        name, mapper = module.get("module", ""), module.get("mapper") or {}
        conn = (module.get("parameters") or {}).get("__IMTCONN__")
        if name.startswith(FACEBOOK_APP):
            print(f"Facebook module: connection {conn}, Page id {mapper.get('page_id') or 'NOT SET'}, "
                  f"photo {mapper.get('photos')}, message {mapper.get('message')}, filter {bool(module.get('filter'))}")
            if not mapper.get("page_id"):
                problems.append("no Facebook Page picked")
        elif name.startswith(INSTAGRAM_APP):
            print(f"Instagram module: connection {conn}, account id {mapper.get('accountId') or 'NOT SET'}, "
                  f"image {mapper.get('image_url')}, caption {mapper.get('caption')}")
            if not mapper.get("accountId"):
                problems.append("no Instagram account picked")
        else:
            print(f"{name}: {module.get('parameters')}")
    if problems:
        raise MakeError("Not switching on: " + ", ".join(problems))
    if not scenario.get("isActive"):
        make.call("POST", f"/scenarios/{scenario['id']}/start")
    print("Scenario is on.")
    notify.send_text("Auto-posting is ON. The Make scenario is running: each post now goes to the Facebook Page and "
                     "Instagram at 07:00, 11:00, 15:00 and 19:00 (Israel time), and you'll get a message here "
                     "every time one is sent.")


CLOCK_NAME = "HOTT clock"
# Make's free plan allows 2 active scenarios, so one clock scenario wakes the "Tick" workflow once in each
# posting hour (Make's time zone). Tick works out what is due, so an extra or missed wake does no harm.
CLOCK_WINDOWS = [["07:00", "08:00"], ["11:00", "12:00"], ["15:00", "16:00"], ["19:00", "20:00"]]


def _clock_blueprint():
    repo = os.environ.get("GITHUB_REPOSITORY", "MoshikTwig/hott-reels-engine")
    return {"name": CLOCK_NAME, "flow": [{
        "id": 1, "module": "http:ActionSendData", "version": 3,
        "parameters": {"handleErrors": False, "useNewZLibDeCompress": True},
        "mapper": {
            "url": f"https://api.github.com/repos/{repo}/actions/workflows/tick.yml/dispatches",
            "method": "post",
            "headers": [{"name": "Authorization", "value": f"Bearer {os.environ['GH_DISPATCH_TOKEN']}"},
                        {"name": "Accept", "value": "application/vnd.github+json"},
                        {"name": "User-Agent", "value": "hott-make-clock"}],
            "qs": [], "bodyType": "raw", "contentType": "application/json",
            "data": json.dumps({"ref": "main"}),
            "parseResponse": False, "serializeUrl": False, "shareCookies": False, "rejectUnauthorized": True,
            "followRedirect": True, "useQuerystring": False, "gzip": True, "useMtls": False,
            # The rest of the fields Make's own HTTP module saves, left empty, or Make rejects the bundle.
            "ca": "", "timeout": "", "authUser": "", "authPass": "", "followAllRedirects": False,
        },
        "metadata": {"designer": {"x": 0, "y": 0}},
    }], "metadata": {"version": 1, "scenario": {"roundtrips": 1, "maxErrors": 3, "autoCommit": True}}}


def clock():
    """Create (or update) the one scheduled Make scenario that wakes the Tick workflow on time."""
    from engine import notify
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::add-mask::{os.environ['GH_DISPATCH_TOKEN']}", flush=True)
    make = Make()
    team = make.team_id()
    scenarios = make.call("GET", "/scenarios", params={"teamId": team})["scenarios"]
    for old in scenarios:  # the first try made one scenario per time; the free plan can't run them all
        if old["name"].startswith("HOTT clock ") and old["name"] != CLOCK_NAME:
            if old.get("isActive"):
                make.call("POST", f"/scenarios/{old['id']}/stop")
            make.call("DELETE", f"/scenarios/{old['id']}", params={"confirmed": "true"})
            print(f"Removed old clock scenario {old['id']} ({old['name']}).")
    existing = next((sc for sc in scenarios if sc["name"] == CLOCK_NAME), None)
    scheduling = {"type": "indefinitely", "interval": 3600, "restrict": [{"time": w} for w in CLOCK_WINDOWS]}
    body = {"blueprint": json.dumps(_clock_blueprint()), "scheduling": json.dumps(scheduling)}
    if existing:
        scenario = make.call("PATCH", f"/scenarios/{existing['id']}", json=body)["scenario"]
    else:
        scenario = make.call("POST", "/scenarios", params={"confirmed": "true"}, json={**body, "teamId": team})["scenario"]
    if not scenario.get("isActive"):
        make.call("POST", f"/scenarios/{scenario['id']}/start")
    print(f"{CLOCK_NAME}: scenario {scenario['id']} on, scheduling {scenario.get('scheduling')}")
    # One test wake now: Tick only acts if something is actually due, so this is safe at any time.
    result = make.call("POST", f"/scenarios/{scenario['id']}/run", json={"responsive": True})
    print(f"Test wake: status {result.get('status')} (1 = ok, 3 = error)")
    if result.get("status") != 1:
        try:
            logs = make.call("GET", f"/scenarios/{scenario['id']}/logs", params={"pg[limit]": 1})
            text = json.dumps(logs)
        except MakeError as error:
            text = str(error)
        token = os.environ["GH_DISPATCH_TOKEN"]
        text = text.replace(token, "***")
        text = re.sub(r"(Bearer|token)\s+[A-Za-z0-9_]+", r"\1 ***", text)
        print(f"Make's log of that wake: {text[:1500]}")
    notify.send_text("Make is now the clock: it wakes the engine at 07:00, 11:00, 15:00 and 19:00 (Israel time), "
                     "so posts no longer wait on GitHub's late timer.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["discover", "build", "activate", "clock"])
    parser.add_argument("--no-activate", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "discover":
            discover()
        elif args.action == "activate":
            activate()
        elif args.action == "clock":
            clock()
        else:
            build(activate=not args.no_activate)
    except MakeError as error:
        print(f"Make error: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
