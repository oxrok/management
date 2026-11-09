#!/usr/bin/env python3
"""Track upstream sigrok PRs as oxrok issues on the "Upstream intake" project.

Every tracked item is an issue in the tracking repo (config.toml) carrying
one or more lines "Upstream: <PR URL>" in its body, the label `upstream`,
a workstream label `ws:<name>`, and the project fields Status, Workstream,
Target and Upstream PR. An upstream PR counts as handled when an issue
names it, or when decisions.toml records a verdict for it.

Commands:
  setup                 labels, project, project fields (idempotent)
  intake [--json] [--with-seed]
                        upstream PRs that are neither tracked nor decided
  add ...               create one tracked item
  seed [--dry-run]      create the items of seed.toml that are not tracked
  move ISSUE STATUS     set an item's Status (closes/reopens the issue)
  report                counts by status and workstream, open work

Needs the gh CLI, logged in with the `project` scope.
"""

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.toml"
DECISIONS = ROOT / "decisions.toml"
SEED = ROOT / "seed.toml"

UPSTREAM_LINE = re.compile(r"^Upstream: (https://github\.com/\S+/pull/\d+)\s*$", re.M)
SHORT_REF = re.compile(r"^([\w.-]+/[\w.-]+)#(\d+)$")
VERDICTS = {"not-applicable", "already-done", "wont-do", "superseded"}

STATUS_COLORS = {
    "Triage": "YELLOW",
    "Backlog": "BLUE",
    "In progress": "ORANGE",
    "Done": "GREEN",
    "Won't do": "GRAY",
}
STATUS_HELP = {
    "Triage": "New upstream PR, not yet looked at",
    "Backlog": "Triaged and wanted, not started",
    "In progress": "Being ported or checked",
    "Done": "Landed in the target repo",
    "Won't do": "Decided against after triage; reason in the issue",
}


def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


def gh(*args, json_out=False, stdin=None):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, input=stdin)
    if r.returncode != 0:
        die("gh %s failed:\n%s" % (" ".join(args), r.stderr.strip()))
    return json.loads(r.stdout) if json_out else r.stdout


def load_config():
    with CONFIG.open("rb") as f:
        return tomllib.load(f)


def save_project_number(number):
    text = CONFIG.read_text()
    text = re.sub(r"^project_number = \d+$", "project_number = %d" % number, text, flags=re.M)
    CONFIG.write_text(text)


def url_of(ref):
    """`owner/repo#N` or a PR URL, as a PR URL."""
    m = SHORT_REF.match(ref)
    if m:
        return "https://github.com/%s/pull/%s" % (m.group(1), m.group(2))
    if re.match(r"^https://github\.com/[\w.-]+/[\w.-]+/pull/\d+$", ref):
        return ref
    die("not a PR reference: %s" % ref)


def short_of(url):
    m = re.match(r"^https://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)$", url)
    return "%s#%s" % (m.group(1), m.group(2)) if m else url


# --- project ---------------------------------------------------------------

class Project:
    def __init__(self, cfg):
        self.cfg = cfg
        self.owner = cfg["owner"]
        self.number = cfg["project_number"]
        if not self.number:
            die("no project yet: run `tools/track.py setup`")
        view = gh("project", "view", str(self.number), "--owner", self.owner,
                  "--format", "json", json_out=True)
        self.id = view["id"]
        self.url = view["url"]
        self.fields = {}
        for f in gh("project", "field-list", str(self.number), "--owner", self.owner,
                    "--format", "json", "--limit", "100", json_out=True)["fields"]:
            self.fields[f["name"]] = f

    def option(self, field, name):
        for o in self.fields[field].get("options", []):
            if o["name"] == name:
                return o["id"]
        die("field %s has no option %r" % (field, name))

    def add(self, issue_url):
        return gh("project", "item-add", str(self.number), "--owner", self.owner,
                  "--url", issue_url, "--format", "json", json_out=True)["id"]

    def set_select(self, item_id, field, value):
        gh("project", "item-edit", "--id", item_id, "--project-id", self.id,
           "--field-id", self.fields[field]["id"],
           "--single-select-option-id", self.option(field, value))

    def set_text(self, item_id, field, value):
        gh("project", "item-edit", "--id", item_id, "--project-id", self.id,
           "--field-id", self.fields[field]["id"], "--text", value)

    def items(self):
        return gh("project", "item-list", str(self.number), "--owner", self.owner,
                  "--format", "json", "--limit", "1000", json_out=True)["items"]


# --- tracked and decided ---------------------------------------------------

def tracked(cfg):
    """{upstream PR URL: issue number} over all `upstream` issues."""
    issues = gh("issue", "list", "-R", cfg["tracking_repo"], "--label", "upstream",
                "--state", "all", "--limit", "2000", "--json", "number,body",
                json_out=True)
    out = {}
    for i in issues:
        for url in UPSTREAM_LINE.findall(i["body"] or ""):
            out[url] = i["number"]
    return out


def decided():
    if not DECISIONS.exists():
        return {}
    with DECISIONS.open("rb") as f:
        data = tomllib.load(f)
    out = {}
    for d in data.get("decision", []):
        if d["verdict"] not in VERDICTS:
            die("decisions.toml: %s has unknown verdict %r" % (d["ref"], d["verdict"]))
        out[url_of(d["ref"])] = d
    return out


# --- commands --------------------------------------------------------------

def cmd_setup(cfg, args):
    repo = cfg["tracking_repo"]
    gh("label", "create", "upstream", "-R", repo, "--force", "--color", "5319e7",
       "--description", "Tracks upstream sigrok work (see oxrok/management)")
    for ws in cfg["workstreams"]:
        gh("label", "create", "ws:" + ws, "-R", repo, "--force", "--color", "c5def5",
           "--description", "Upstream workstream: " + ws)

    number = cfg["project_number"]
    if not number:
        p = gh("project", "create", "--owner", cfg["owner"], "--title",
               cfg["project_title"], "--format", "json", json_out=True)
        number = p["number"]
        save_project_number(number)
        cfg["project_number"] = number
        print("created project #%d" % number)
    gh("project", "link", str(number), "--owner", cfg["owner"], "--repo", repo)
    gh("project", "edit", str(number), "--owner", cfg["owner"], "--visibility", "PUBLIC",
       "--description", "Upstream sigrok PRs triaged for oxrok. Managed with "
       "https://github.com/oxrok/management")

    proj = Project(cfg)
    wanted = {
        "Workstream": cfg["workstreams"],
        "Target": cfg["targets"],
        "Upstream repo": [u["repo"].split("/")[1] for u in cfg["upstream"]],
    }
    for name, options in wanted.items():
        if name not in proj.fields:
            gh("project", "field-create", str(number), "--owner", cfg["owner"],
               "--name", name, "--data-type", "SINGLE_SELECT",
               "--single-select-options", ",".join(options))
            print("created field %s" % name)
    if "Upstream PR" not in proj.fields:
        gh("project", "field-create", str(number), "--owner", cfg["owner"],
           "--name", "Upstream PR", "--data-type", "TEXT")
        print("created field Upstream PR")

    # Status is built in; replace its options with ours.
    status = proj.fields["Status"]
    have = [o["name"] for o in status.get("options", [])]
    if have != cfg["statuses"]:
        opts = [{"name": s, "color": STATUS_COLORS.get(s, "GRAY"),
                 "description": STATUS_HELP.get(s, "")} for s in cfg["statuses"]]
        query = """mutation($f: ID!, $o: [ProjectV2SingleSelectFieldOptionInput!]) {
          updateProjectV2Field(input: {fieldId: $f, singleSelectOptions: $o}) {
            projectV2Field { ... on ProjectV2SingleSelectField { id } } } }"""
        gh("api", "graphql", "--input", "-",
           stdin=json.dumps({"query": query, "variables": {"f": status["id"], "o": opts}}))
        print("set Status options: %s" % ", ".join(cfg["statuses"]))
    print("project: %s" % Project(cfg).url)


def upstream_candidates(cfg):
    """Open PRs, and unmerged PRs closed since closed_since, per upstream repo."""
    fields = "number,title,author,state,createdAt,closedAt,mergedAt,url,additions,deletions"
    for u in cfg["upstream"]:
        prs = gh("pr", "list", "-R", u["repo"], "--state", "all", "--limit", "2000",
                 "--json", fields, json_out=True)
        for p in prs:
            if p["mergedAt"]:
                continue
            if p["state"] == "CLOSED" and (p["closedAt"] or "") < cfg["closed_since"]:
                continue
            p["repo"] = u["repo"]
            p["target"] = u["target"]
            yield p


def cmd_intake(cfg, args):
    done = tracked(cfg)
    skip = decided()
    if args.with_seed:
        with SEED.open("rb") as f:
            for it in tomllib.load(f)["item"]:
                for r in it["upstream"]:
                    done.setdefault(url_of(r), 0)
    new = [p for p in upstream_candidates(cfg) if p["url"] not in done and p["url"] not in skip]
    new.sort(key=lambda p: (p["repo"], p["number"]))
    if args.json:
        print(json.dumps(new, indent=1))
        return
    for p in new:
        print("%-40s %s %s +%d-%d %-16s %s" % (
            short_of(p["url"]), p["state"][0], p["createdAt"][:10], p["additions"],
            p["deletions"], p["author"]["login"][:16], p["title"][:80]))
    print("%d untracked, %d tracked, %d decided" % (len(new), len(done), len(skip)),
          file=sys.stderr)


def create_item(cfg, proj, title, workstream, target, status, upstream, notes):
    if workstream not in cfg["workstreams"]:
        die("unknown workstream %r" % workstream)
    if target not in cfg["targets"]:
        die("unknown target %r" % target)
    if status not in cfg["statuses"]:
        die("unknown status %r" % status)
    urls = [url_of(r) for r in upstream]
    if not urls:
        die("an item needs at least one upstream PR")
    body = "\n".join("Upstream: " + u for u in urls)
    body += "\nTarget: %s\nWorkstream: %s\n\n%s\n" % (target, workstream, notes.strip())
    body += ("\n---\nTracked on the [%s](%s) project; see "
             "[oxrok/management](https://github.com/oxrok/management).\n"
             % (cfg["project_title"], proj.url))
    issue_url = gh("issue", "create", "-R", cfg["tracking_repo"], "--title", title,
                   "--body", body, "--label", "upstream", "--label", "ws:" + workstream).strip()
    item = proj.add(issue_url)
    proj.set_select(item, "Status", status)
    proj.set_select(item, "Workstream", workstream)
    proj.set_select(item, "Target", target)
    first = short_of(urls[0])
    proj.set_select(item, "Upstream repo", first.split("#")[0].split("/")[1])
    proj.set_text(item, "Upstream PR", ", ".join(short_of(u) for u in urls))
    if status == "Done":
        gh("issue", "close", issue_url, "--reason", "completed")
    elif status == "Won't do":
        gh("issue", "close", issue_url, "--reason", "not planned")
    print("%s  %s" % (issue_url, title))
    return issue_url


def cmd_add(cfg, args):
    notes = Path(args.notes_file).read_text() if args.notes_file else (args.notes or "")
    proj = Project(cfg)
    have = tracked(cfg)
    for r in args.upstream:
        if url_of(r) in have:
            die("%s is already tracked in #%d" % (r, have[url_of(r)]))
    create_item(cfg, proj, args.title, args.workstream, args.target, args.status,
                args.upstream, notes)


def cmd_seed(cfg, args):
    with SEED.open("rb") as f:
        items = tomllib.load(f)["item"]
    have = tracked(cfg)
    proj = None if args.dry_run else Project(cfg)
    for it in items:
        urls = [url_of(r) for r in it["upstream"]]
        hit = [u for u in urls if u in have]
        if hit:
            print("skip (tracked in #%d): %s" % (have[hit[0]], it["title"]))
            continue
        if args.dry_run:
            print("would create: [%s/%s] %s" % (it["workstream"], it["status"], it["title"]))
            continue
        create_item(cfg, proj, it["title"], it["workstream"], it["target"],
                    it["status"], it["upstream"], it.get("notes", ""))
        for u in urls:
            have[u] = -1


def find_item(proj, issue):
    for it in proj.items():
        c = it.get("content") or {}
        if c.get("number") == issue and c.get("repository", "").endswith(
                proj.cfg["tracking_repo"].split("/")[1]):
            return it
    die("issue #%d is not on the project" % issue)


def cmd_move(cfg, args):
    if args.status not in cfg["statuses"]:
        die("status must be one of: %s" % ", ".join(cfg["statuses"]))
    proj = Project(cfg)
    it = find_item(proj, args.issue)
    proj.set_select(it["id"], "Status", args.status)
    ref = str(args.issue)
    repo = cfg["tracking_repo"]
    state = gh("issue", "view", ref, "-R", repo, "--json", "state", json_out=True)["state"]
    if args.status in ("Done", "Won't do") and state == "OPEN":
        reason = "completed" if args.status == "Done" else "not planned"
        cmd = ["issue", "close", ref, "-R", repo, "--reason", reason]
        if args.comment:
            cmd += ["--comment", args.comment]
        gh(*cmd)
    elif args.status not in ("Done", "Won't do") and state == "CLOSED":
        gh("issue", "reopen", ref, "-R", repo)
        if args.comment:
            gh("issue", "comment", ref, "-R", repo, "--body", args.comment)
    elif args.comment:
        gh("issue", "comment", ref, "-R", repo, "--body", args.comment)
    print("#%d -> %s" % (args.issue, args.status))


def cmd_report(cfg, args):
    proj = Project(cfg)
    items = proj.items()
    table = {}
    for it in items:
        key = (it.get("status") or "(none)", it.get("workstream") or "(none)")
        table.setdefault(key, []).append(it)
    statuses = cfg["statuses"] + ["(none)"]
    wss = cfg["workstreams"] + ["(none)"]
    print("%-15s" % "" + "".join("%13s" % s[:12] for s in statuses))
    for ws in wss:
        row = [len(table.get((s, ws), [])) for s in statuses]
        if any(row):
            print("%-15s" % ws + "".join("%13s" % (n or ".") for n in row))
    print()
    for s in ("In progress", "Triage"):
        rows = [it for it in items if it.get("status") == s]
        if rows:
            print("%s:" % s)
            for it in rows:
                c = it.get("content") or {}
                print("  #%-5s %-14s %s" % (c.get("number", "?"), it.get("workstream", ""),
                                           c.get("title", "")))
    done = tracked(cfg)
    skip = decided()
    untracked = sum(1 for p in upstream_candidates(cfg)
                    if p["url"] not in done and p["url"] not in skip)
    print("\nuntracked upstream PRs (run intake): %d" % untracked)
    print(proj.url)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    p = sub.add_parser("intake")
    p.add_argument("--json", action="store_true")
    p.add_argument("--with-seed", action="store_true",
                   help="also count seed.toml as tracked (to check the seed covers everything)")
    p = sub.add_parser("add")
    p.add_argument("--title", required=True)
    p.add_argument("--workstream", required=True)
    p.add_argument("--target", default="oxrok/oxrok")
    p.add_argument("--status", default="Backlog")
    p.add_argument("--upstream", nargs="+", required=True,
                   help="owner/repo#N or PR URLs")
    p.add_argument("--notes")
    p.add_argument("--notes-file")
    p = sub.add_parser("seed")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("move")
    p.add_argument("issue", type=int)
    p.add_argument("status")
    p.add_argument("--comment")
    sub.add_parser("report")
    args = ap.parse_args()
    cfg = load_config()
    {"setup": cmd_setup, "intake": cmd_intake, "add": cmd_add, "seed": cmd_seed,
     "move": cmd_move, "report": cmd_report}[args.cmd](cfg, args)


if __name__ == "__main__":
    main()
