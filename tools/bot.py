#!/usr/bin/env python3
"""Act on GitHub as the org's bot (a GitHub App), so a human can review what it did.

The App's id and private key live outside every repository, in
~/.config/oxrok-bot/app-id and ~/.config/oxrok-bot/key.pem (OXROK_BOT_DIR
overrides the directory). Installation tokens last an hour and are minted
per command; nothing is cached on disk.

Commands:
  token                          print an installation token
  push DIR BRANCH [--force]      push DIR's BRANCH to its origin as the bot
  pr --repo R --head B --title T (--body-file F | --body S) [--draft] [--base main]
  issue --repo R --title T (--body-file F | --body S) [--label L ...]
  comment --repo R NUMBER (--body-file F | --body S)
  whoami                         the App's slug and the repos it is installed on

Setup (once, by a human): GitHub -> organization settings -> Developer
settings -> GitHub Apps -> New GitHub App. Name "oxrok-bot", no webhook,
repository permissions Contents: read and write, Pull requests: read and
write, Issues: read and write, Metadata: read. Install it on the org, all
repositories. Save the App ID to app-id and a generated private key to
key.pem (mode 600). The bot must never be a bypass actor of a ruleset.
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ghlib import die, gh  # noqa: E402

BOT_DIR = Path(os.environ.get("OXROK_BOT_DIR", Path.home() / ".config" / "oxrok-bot"))
NO_USER_TOKEN = {"GH_TOKEN": "unused"}  # gh must not fall back to the user's login


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def app_jwt():
    try:
        app_id = (BOT_DIR / "app-id").read_text().strip()
        key_pem = (BOT_DIR / "key.pem").read_bytes()
    except OSError as e:
        die("bot credentials missing (%s); see tools/bot.py --help for the setup" % e)
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError:
        die("python3-cryptography is needed to sign the App JWT")
    key = serialization.load_pem_private_key(key_pem, password=None)
    now = int(time.time())
    header = b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    payload = b64url(json.dumps({"iat": now - 60, "exp": now + 540, "iss": app_id}).encode())
    signing = ("%s.%s" % (header, payload)).encode()
    sig = key.sign(signing, padding.PKCS1v15(), hashes.SHA256())
    return "%s.%s" % (signing.decode(), b64url(sig))


def installation(owner="oxrok"):
    jwt = app_jwt()
    inst = gh("api", "/app/installations", "-H", "Authorization: Bearer " + jwt,
              json_out=True, env=NO_USER_TOKEN)
    for i in inst:
        if i["account"]["login"].lower() == owner.lower():
            return jwt, i
    die("the App is not installed on %s" % owner)


def token(owner="oxrok"):
    jwt, inst = installation(owner)
    r = gh("api", "-X", "POST", "/app/installations/%d/access_tokens" % inst["id"],
           "-H", "Authorization: Bearer " + jwt, json_out=True, env=NO_USER_TOKEN)
    return r["token"]


def bot_env():
    return {"GH_TOKEN": token()}


def body_of(args):
    if args.body_file:
        return Path(args.body_file).read_text()
    if args.body is None:
        die("--body or --body-file is required")
    return args.body


MANIFEST = {
    "name": "oxrok-bot",
    "url": "https://github.com/oxrok/management",
    "description": "Opens the draft pull requests and issues that oxrok's maintenance "
                   "tools prepare, so a person reviews them. See oxrok/management.",
    "hook_attributes": {"active": False},
    "redirect_url": "https://oxrok.dev/",
    "public": False,
    "default_permissions": {"contents": "write", "pull_requests": "write",
                            "issues": "write", "metadata": "read"},
    "default_events": [],
}


def cmd_manifest(args):
    """The App manifest, for GitHub's create-from-manifest form."""
    print(json.dumps(MANIFEST, indent=1))


def cmd_convert(args):
    """Exchange the code GitHub redirects with for the App's id and key, and save them."""
    r = gh("api", "-X", "POST", "/app-manifests/%s/conversions" % args.code, json_out=True)
    BOT_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    (BOT_DIR / "app-id").write_text("%d\n" % r["id"])
    pem = BOT_DIR / "key.pem"
    pem.write_text(r["pem"])
    pem.chmod(0o600)
    print("saved app id %d (%s) and its key under %s" % (r["id"], r["slug"], BOT_DIR))
    print("now install it on the org: %s/installations/new" % r["html_url"])


def cmd_token(args):
    print(token())


def cmd_whoami(args):
    jwt, inst = installation()
    app = gh("api", "/app", "-H", "Authorization: Bearer " + jwt, json_out=True,
             env=NO_USER_TOKEN)
    repos = gh("api", "/installation/repositories?per_page=100", json_out=True,
               env={"GH_TOKEN": token()})
    print("%s (app id %s), installed on %s: %s" % (
        app["slug"], app["id"], inst["account"]["login"],
        ", ".join(r["full_name"] for r in repos["repositories"])))


def cmd_push(args):
    url = subprocess.run(["git", "-C", args.dir, "remote", "get-url", "origin"],
                         capture_output=True, text=True, check=True).stdout.strip()
    m = re.match(r"^(?:git@github\.com:|https://github\.com/)([\w.-]+/[\w.-]+?)(?:\.git)?$", url)
    if not m:
        die("origin is not a GitHub remote: %s" % url)
    if not args.branch.startswith("agent/"):
        die("the bot pushes only to agent/* branches, not %s (AGENTS.md, Maintenance)" % args.branch)
    authed = "https://x-access-token:%s@github.com/%s.git" % (token(), m.group(1))
    cmd = ["git", "-C", args.dir, "push", "-q"]
    if args.force:
        # A URL has no remote-tracking ref for the lease, so name the tip we last
        # fetched: the push is refused if the branch moved since.
        known = subprocess.run(["git", "-C", args.dir, "rev-parse", "--verify", "-q",
                                "refs/remotes/origin/" + args.branch],
                               capture_output=True, text=True)
        if known.returncode != 0:
            die("no fetched tip for origin/%s to lease on; `git fetch origin` first" % args.branch)
        cmd.append("--force-with-lease=refs/heads/%s:%s" % (args.branch, known.stdout.strip()))
    cmd += [authed, "%s:refs/heads/%s" % (args.branch, args.branch)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    # Never echo the command line: it carries the token.
    if r.returncode != 0:
        die("push failed:\n" + r.stderr.replace(authed, "<origin>").strip())
    print("pushed %s to %s as the bot" % (args.branch, m.group(1)))


def cmd_pr(args):
    cmd = ["pr", "create", "-R", args.repo, "--head", args.head, "--base", args.base,
           "--title", args.title, "--body", body_of(args)]
    if args.draft:
        cmd.append("--draft")
    for label in args.label or []:
        cmd += ["--label", label]
    print(gh(*cmd, env=bot_env()).strip())


def cmd_issue(args):
    cmd = ["issue", "create", "-R", args.repo, "--title", args.title, "--body", body_of(args)]
    for label in args.label or []:
        cmd += ["--label", label]
    print(gh(*cmd, env=bot_env()).strip())


def cmd_comment(args):
    gh("issue", "comment", str(args.number), "-R", args.repo, "--body", body_of(args),
       env=bot_env())
    print("commented on %s#%d" % (args.repo, args.number))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("token")
    sub.add_parser("whoami")
    sub.add_parser("manifest")
    p = sub.add_parser("convert")
    p.add_argument("code")
    p = sub.add_parser("push")
    p.add_argument("dir")
    p.add_argument("branch")
    p.add_argument("--force", action="store_true")
    for name in ("pr", "issue", "comment"):
        p = sub.add_parser(name)
        p.add_argument("--repo", required=True)
        p.add_argument("--body")
        p.add_argument("--body-file")
        if name == "pr":
            p.add_argument("--head", required=True)
            p.add_argument("--base", default="main")
            p.add_argument("--title", required=True)
            p.add_argument("--draft", action="store_true")
            p.add_argument("--label", action="append")
        elif name == "issue":
            p.add_argument("--title", required=True)
            p.add_argument("--label", action="append")
        else:
            p.add_argument("number", type=int)
    args = ap.parse_args()
    {"token": cmd_token, "whoami": cmd_whoami, "push": cmd_push, "pr": cmd_pr,
     "issue": cmd_issue, "comment": cmd_comment, "manifest": cmd_manifest,
     "convert": cmd_convert}[args.cmd](args)


if __name__ == "__main__":
    main()
