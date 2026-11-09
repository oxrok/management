#!/usr/bin/env python3
"""Apply the org's two main-branch rulesets to a repository.

  rulesets/protection.json  no bypass: no deletion, no force push, and the
                            repo's required checks (config.toml `checks`),
                            which also stops direct pushes to main
  rulesets/review.json      pull requests with one approval; org admins may
                            merge their own PR without one (bypass mode
                            "pull_request"), but cannot push to main

Usage: tools/rulesets.py apply [--dry-run] REPO...   (short or full names; "all")
       tools/rulesets.py show REPO
       tools/rulesets.py checks REPO PR     the check names a pull request ran

Idempotent: a ruleset with the same name is updated, otherwise created. Any
other ruleset on the repo is listed and left alone; delete the old one by
hand once the new pair is in place. The bot is never a bypass actor.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ghlib import ROOT, die, gh, load_config, repo_entry  # noqa: E402

RULESETS = ROOT / "rulesets"


def bodies(entry):
    if not entry.get("checks"):
        die("%s has no `checks` in config.toml; a protection ruleset without required checks would let direct pushes through" % entry["name"])
    protection = json.loads((RULESETS / "protection.json").read_text())
    for rule in protection["rules"]:
        if rule["type"] == "required_status_checks":
            rule["parameters"]["required_status_checks"] = [
                {"context": c} for c in entry.get("checks", [])]
    review = json.loads((RULESETS / "review.json").read_text())
    return [protection, review]


def existing(repo):
    return {r["name"]: r for r in gh("api", "repos/%s/rulesets" % repo, json_out=True)}


def cmd_apply(cfg, args):
    names = [r["name"] for r in cfg["repo"]] if args.repos == ["all"] else args.repos
    for name in names:
        entry = repo_entry(cfg, name)
        repo = entry["name"]
        have = existing(repo)
        for body in bodies(entry):
            if args.dry_run:
                print("%s: would %s %r" % (repo, "update" if body["name"] in have else "create",
                                           body["name"]))
                print(json.dumps(body, indent=1))
                continue
            if body["name"] in have:
                gh("api", "-X", "PUT", "repos/%s/rulesets/%d" % (repo, have[body["name"]]["id"]),
                   "--input", "-", stdin=json.dumps(body))
                print("%s: updated %r" % (repo, body["name"]))
            else:
                gh("api", "-X", "POST", "repos/%s/rulesets" % repo,
                   "--input", "-", stdin=json.dumps(body))
                print("%s: created %r" % (repo, body["name"]))
        ours = {b["name"] for b in bodies(entry)}
        for other in have:
            if other not in ours:
                print("%s: other ruleset left alone: %r (id %d)" % (repo, other, have[other]["id"]))


def cmd_show(cfg, args):
    repo = repo_entry(cfg, args.repo)["name"]
    for r in gh("api", "repos/%s/rulesets" % repo, json_out=True):
        full = gh("api", "repos/%s/rulesets/%d" % (repo, r["id"]), json_out=True)
        print(json.dumps({k: full[k] for k in ("id", "name", "enforcement", "bypass_actors",
                                               "rules")}, indent=1))


def cmd_checks(cfg, args):
    repo = repo_entry(cfg, args.repo)["name"]
    sha = gh("pr", "view", str(args.pr), "-R", repo, "--json", "headRefOid",
             json_out=True)["headRefOid"]
    runs = gh("api", "repos/%s/commits/%s/check-runs?per_page=100" % (repo, sha),
              json_out=True)["check_runs"]
    for r in sorted(runs, key=lambda r: r["name"]):
        print("%-50s %s" % (r["name"], r.get("conclusion") or r["status"]))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("apply")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("repos", nargs="+")
    p = sub.add_parser("show")
    p.add_argument("repo")
    p = sub.add_parser("checks")
    p.add_argument("repo")
    p.add_argument("pr", type=int)
    args = ap.parse_args()
    cfg = load_config()
    {"apply": cmd_apply, "show": cmd_show, "checks": cmd_checks}[args.cmd](cfg, args)


if __name__ == "__main__":
    main()
