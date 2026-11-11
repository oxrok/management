#!/usr/bin/env python3
"""The CI doctor's write plan: what the agent wants opened, applied by a separate job.

In the ci-doctor workflow the agent holds no write credential. Instead of
`bot.py push/pr/issue` it records each write here; the workflow's `apply`
job, which holds the bot's App key and runs no agent, checks every entry
again and makes it with bot.py (AGENTS.md "Maintenance",
docs/AGENT-POLICY.md, rung 2).

Commands (the agent's):
  pr     --repo R --dir WORKTREE --signature S [--signature S ...] --title T --body-file F
         [--for-repo R2]
         the commits WORKTREE's branch (agent/ci-<slug>) has over origin/main,
         as a patch, for a draft PR. --for-repo names the repo whose CI the
         signatures are from when it is not R (a flakes.toml PR here).
  issue  --repo R --signature S [--signature S ...] --title T --body-file F
  show   the plan so far

Command (the apply job's):
  apply  PLAN_DIR [--dry-run]

The plan lives in $CI_DOCTOR_PLAN (a directory). Every PR and issue gets the
labels `maintenance`, `area:ci` and `ci-doctor`, and one
`CI-Doctor: <repo> | <signature>` line per signature (tools/ci.py `open`
reads those). An entry whose signature already has an open ci-doctor item
is skipped at apply time, so two runs do not open the same thing twice.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ghlib import ROOT, die, load_config, repo_entry  # noqa: E402
import ci  # noqa: E402

LABELS = ["maintenance", "area:ci", ci.LABEL]
BRANCH = re.compile(r"^agent/ci-[a-z0-9][a-z0-9.-]{0,60}$")
# Paths a CI doctor patch may never touch: the gates themselves.
FORBIDDEN = re.compile(r"^(\.github/workflows/|rulesets/)")
MAX_PATCH = 256 * 1024
MAX_BODY = 32 * 1024
MAX_TITLE = 120
MAX_ENTRIES = 10


def plan_dir():
    d = os.environ.get("CI_DOCTOR_PLAN")
    if not d:
        die("CI_DOCTOR_PLAN is not set: plan.py is for the ci-doctor workflow; "
            "by hand, use bot.py as .claude/skills/ci-doctor/SKILL.md says")
    p = Path(d)
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_plan(d):
    f = d / "plan.json"
    return json.loads(f.read_text()) if f.exists() else []


def save_plan(d, plan):
    (d / "plan.json").write_text(json.dumps(plan, indent=1) + "\n")


def check_text(title, body, signatures):
    if not title.strip() or len(title) > MAX_TITLE or "\n" in title:
        die("the title must be one line of at most %d characters" % MAX_TITLE)
    if len(body.encode()) > MAX_BODY:
        die("the body is over %d bytes; carry the digest's excerpt, not more" % MAX_BODY)
    if not signatures:
        die("at least one --signature (a cluster's `signature:` line from ci.py failures)")
    for s in signatures:
        if "\n" in s or not s.strip() or len(s) > 250:
            die("a signature is one line, as ci.py prints it: %r" % s[:80])


def patch_paths(patch):
    return sorted(set(re.findall(r"^diff --git a/(\S+) b/", patch, re.M)
                      + re.findall(r"^diff --git a/\S+ b/(\S+)", patch, re.M)))


def check_patch(patch):
    if not patch.strip():
        die("the branch has no commits over origin/main")
    if len(patch.encode()) > MAX_PATCH:
        die("the patch is over %d bytes: the smallest change that fixes it, please" % MAX_PATCH)
    bad = [p for p in patch_paths(patch) if FORBIDDEN.match(p)]
    if bad:
        die("the patch touches %s; a CI doctor fix never changes workflows or rulesets "
            "(open an issue instead)" % ", ".join(bad))


def git(d, *args, check=True):
    r = subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        die("git %s failed:\n%s" % (" ".join(args), r.stderr.strip()))
    return r.stdout


def add_entry(entry):
    d = plan_dir()
    plan = load_plan(d)
    if len(plan) >= MAX_ENTRIES:
        die("the plan has %d entries already; report the rest instead" % MAX_ENTRIES)
    n = len(plan) + 1
    entry["body_file"] = "%02d.body.md" % n
    (d / entry["body_file"]).write_text(entry.pop("body"))
    if "patch" in entry:
        entry["patch_file"] = "%02d.patch" % n
        (d / entry["patch_file"]).write_text(entry.pop("patch"))
    plan.append(entry)
    save_plan(d, plan)
    print("planned %d: %s %s: %s" % (n, entry["type"], entry["repo"], entry["title"]))


def cmd_pr(cfg, args):
    repo = repo_entry(cfg, args.repo)["name"]
    body = Path(args.body_file).read_text()
    check_text(args.title, body, args.signature)
    branch = git(args.dir, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if not BRANCH.match(branch):
        die("the worktree is on %r; the doctor's branches are agent/ci-<slug>" % branch)
    patch = git(args.dir, "format-patch", "--stdout", "origin/main..HEAD")
    check_patch(patch)
    for_repo = repo_entry(cfg, args.for_repo or repo)["name"]
    add_entry({"type": "pr", "repo": repo, "for_repo": for_repo, "branch": branch,
               "title": args.title, "signatures": args.signature, "body": body,
               "patch": patch})


def cmd_issue(cfg, args):
    repo = repo_entry(cfg, args.repo)["name"]
    body = Path(args.body_file).read_text()
    check_text(args.title, body, args.signature)
    add_entry({"type": "issue", "repo": repo, "for_repo": repo, "title": args.title,
               "signatures": args.signature, "body": body})


def cmd_show(cfg, args):
    plan = load_plan(plan_dir())
    if not plan:
        print("the plan is empty")
    for n, e in enumerate(plan, 1):
        print("%d. %s %s%s: %s" % (n, e["type"], e["repo"],
                                   " " + e["branch"] if e.get("branch") else "", e["title"]))
        for s in e["signatures"]:
            print("   %s" % s)


# --- apply: the bot's job ----------------------------------------------------

def footer(repo, signatures):
    lines = ["", "---"]
    run = os.environ.get("GITHUB_RUN_ID")
    if run:
        lines.append("Planned by the ci-doctor workflow, run %s/%s/actions/runs/%s; "
                     "opened by tools/plan.py apply." % (
                         os.environ.get("GITHUB_SERVER_URL", "https://github.com"),
                         os.environ.get("GITHUB_REPOSITORY", "oxrok/management"), run))
    lines += ["CI-Doctor: %s | %s" % (repo, s) for s in signatures]
    return "\n".join(lines) + "\n"


def tool(*args, check=True):
    r = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / args[0]), *args[1:]],
                       capture_output=True, text=True)
    if r.returncode != 0 and check:
        die("%s failed:\n%s" % (" ".join(args[:2]), r.stderr.strip()))
    return r


def board_add(url):
    r = tool("board.py", "add", url, "--area", "ci", check=False)
    if r.returncode != 0:
        print("  warning: not added to the board: %s" % r.stderr.strip().splitlines()[-1:])


def apply_pr(cfg, e, d, work, dry, target):
    repo = repo_entry(cfg, e["repo"])["name"]
    patch = (d / e["patch_file"]).read_text()
    check_patch(patch)
    if not BRANCH.match(e["branch"]):
        die("entry branch %r is not agent/ci-<slug>" % e["branch"])
    print("  paths: %s" % ", ".join(patch_paths(patch)))
    if dry:
        return
    wt = Path(work) / e["branch"].replace("/", "-")
    subprocess.run(["git", "clone", "-q", "--depth", "50", "--branch", "main",
                    "https://github.com/%s.git" % repo, str(wt)], check=True)
    git(wt, "checkout", "-q", "-b", e["branch"])
    pf = wt.parent / (wt.name + ".patch")
    pf.write_text(patch)
    r = subprocess.run(["git", "-C", str(wt), "-c", "user.name=oxrok-bot[bot]",
                        "-c", "user.email=oxrok-bot[bot]@users.noreply.github.com",
                        "am", "-q", "--3way", str(pf)], capture_output=True, text=True)
    if r.returncode != 0:
        print("  skipped: the patch no longer applies to main:\n%s" % r.stderr.strip()[:2000])
        return
    if tool("bot.py", "push", str(wt), e["branch"], check=False).returncode != 0:
        print("  skipped: could not push %s (it may exist already)" % e["branch"])
        return
    body = (d / e["body_file"]).read_text() + footer(target, e["signatures"])
    bf = wt.parent / (wt.name + ".body.md")
    bf.write_text(body)
    args = ["bot.py", "pr", "--repo", repo, "--head", e["branch"], "--draft",
            "--title", e["title"], "--body-file", str(bf)]
    for label in LABELS:
        args += ["--label", label]
    url = tool(*args).stdout.strip().splitlines()[-1]
    print("  opened %s" % url)
    board_add(url)


def apply_issue(cfg, e, d, work, dry, target):
    repo = repo_entry(cfg, e["repo"])["name"]
    if dry:
        return
    bf = Path(work) / ("issue-%s.md" % e["body_file"])
    bf.write_text((d / e["body_file"]).read_text() + footer(target, e["signatures"]))
    args = ["bot.py", "issue", "--repo", repo,
            "--title", e["title"], "--body-file", str(bf)]
    for label in LABELS:
        args += ["--label", label]
    url = tool(*args).stdout.strip().splitlines()[-1]
    print("  opened %s" % url)
    board_add(url)


def cmd_apply(cfg, args):
    d = Path(args.plan_dir)
    plan = load_plan(d)
    if not isinstance(plan, list) or len(plan) > MAX_ENTRIES:
        die("not a plan, or more than %d entries" % MAX_ENTRIES)
    if not plan:
        print("the plan is empty; nothing to open")
        return
    open_by_repo = {}
    with tempfile.TemporaryDirectory() as work:
        for n, e in enumerate(plan, 1):
            if e.get("type") not in ("pr", "issue"):
                die("entry %d: unknown type %r" % (n, e.get("type")))
            # The artifact is data: file names are the ones add_entry writes,
            # never a path out of the plan directory (the bot's key is on disk).
            want = {"body_file": "%02d.body.md" % n}
            if e["type"] == "pr":
                want["patch_file"] = "%02d.patch" % n
            for k, v in want.items():
                if e.get(k) != v:
                    die("entry %d: %s is %r, not %r" % (n, k, e.get(k), v))
            title, sigs = e.get("title", ""), e.get("signatures") or []
            body = (d / e["body_file"]).read_text()
            check_text(title, body, sigs)
            repo = repo_entry(cfg, e["repo"])["name"]
            print("%d. %s %s: %s" % (n, e["type"], repo, title))
            # Signatures are of the repo whose CI failed; a flakes.toml PR here
            # names that repo in its signatures' marker, not oxrok/management.
            target = repo_entry(cfg, e.get("for_repo") or repo)["name"]
            if target not in open_by_repo:
                open_by_repo[target] = ci.open_items(target)
            dup = [t for s in sigs for t in ci.tracked_by(open_by_repo[target], s)]
            if dup:
                print("  skipped: already tracked by %s" % ", ".join(sorted(set(dup))))
                continue
            (apply_pr if e["type"] == "pr" else apply_issue)(cfg, e, d, work, args.dry_run,
                                                             target)
            # What this run opened counts for the entries after it.
            open_by_repo[target].append({"ref": "this run", "kind": e["type"], "title": title,
                                         "signatures": sigs})


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("pr", "issue"):
        p = sub.add_parser(name)
        p.add_argument("--repo", required=True)
        p.add_argument("--signature", action="append", required=True)
        p.add_argument("--title", required=True)
        p.add_argument("--body-file", required=True)
        if name == "pr":
            p.add_argument("--dir", required=True)
            p.add_argument("--for-repo")
    sub.add_parser("show")
    p = sub.add_parser("apply")
    p.add_argument("plan_dir")
    p.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    {"pr": cmd_pr, "issue": cmd_issue, "show": cmd_show, "apply": cmd_apply}[args.cmd](cfg, args)


if __name__ == "__main__":
    main()
