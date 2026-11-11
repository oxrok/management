#!/usr/bin/env python3
"""The "Maintenance" org project: what the maintenance tools and skills open.

Commands:
  setup                      the project, its fields, the labels in every repo
  add URL --area A [--status S]   put an issue or PR on the board
  list [--status S]          the items

Fields: Status (Todo, In progress, Done), Area (config.toml `areas`), Target repo
(the [[repo]] short names). Labels in every repo: `maintenance`,
`area:<x>`, and `ci-doctor` (what the CI doctor opened; tools/ci.py `open`).
Project #1, "Upstream intake", is track.py's and is not touched.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ghlib import CONFIG, Project, die, gh, load_config  # noqa: E402

TITLE = "Maintenance"
STATUSES = ["Todo", "In progress", "Done"]
COLORS = {"Todo": "BLUE", "In progress": "ORANGE", "Done": "GREEN"}
HELP = {"Todo": "Opened by a tool or a person, not started",
        "In progress": "Someone is on it", "Done": "Merged or closed"}


def short_names(cfg):
    return [r["name"].split("/")[1] for r in cfg["repo"]]


def save_number(number):
    text = CONFIG.read_text()
    text = re.sub(r"^maintenance_project_number = \d+$",
                  "maintenance_project_number = %d" % number, text, flags=re.M)
    CONFIG.write_text(text)


def cmd_setup(cfg, args):
    owner = cfg["owner"]
    number = cfg["maintenance_project_number"]
    if not number:
        p = gh("project", "create", "--owner", owner, "--title", TITLE,
               "--format", "json", json_out=True)
        number = p["number"]
        save_number(number)
        cfg["maintenance_project_number"] = number
        print("created project #%d" % number)
    gh("project", "edit", str(number), "--owner", owner, "--visibility", "PUBLIC",
       "--description", "CI, docs, dependency and security upkeep of the oxrok repos. "
       "Managed with https://github.com/oxrok/management")
    for r in cfg["repo"]:
        gh("project", "link", str(number), "--owner", owner, "--repo", r["name"], check=False)
        gh("label", "create", "maintenance", "-R", r["name"], "--force", "--color", "d4c5f9",
           "--description", "Upkeep opened by the maintenance tools (oxrok/management)")
        for area in cfg["areas"]:
            gh("label", "create", "area:" + area, "-R", r["name"], "--force",
               "--color", "bfdadc", "--description", "Maintenance area: " + area)
        gh("label", "create", "ci-doctor", "-R", r["name"], "--force", "--color", "f9d0c4",
           "--description", "Opened by the CI doctor; its CI-Doctor: lines name the failures")
    proj = Project(owner, number)
    if proj.ensure_select_field("Area", cfg["areas"]):
        print("created field Area")
    if proj.ensure_select_field("Target repo", short_names(cfg)):
        print("created field Target repo")
    if proj.set_status_options(STATUSES, COLORS, HELP):
        print("set Status options: %s" % ", ".join(STATUSES))
    print("project: %s" % proj.url)


def cmd_add(cfg, args):
    m = re.match(r"^https://github\.com/([\w.-]+)/([\w.-]+)/(issues|pull)/\d+$", args.url)
    if not m:
        die("not an issue or pull request URL: %s" % args.url)
    if m.group(1) != cfg["owner"] or m.group(2) not in short_names(cfg):
        die("%s/%s is not one of the repos in config.toml" % (m.group(1), m.group(2)))
    if args.area not in cfg["areas"]:
        die("area must be one of: %s" % ", ".join(cfg["areas"]))
    if args.status not in STATUSES:
        die("status must be one of: %s" % ", ".join(STATUSES))
    proj = Project(cfg["owner"], cfg["maintenance_project_number"])
    item = proj.add(args.url)
    proj.set_select(item, "Status", args.status)
    proj.set_select(item, "Area", args.area)
    proj.set_select(item, "Target repo", m.group(2))
    print("%s -> %s [%s, %s]" % (args.url, proj.url, args.area, args.status))


def cmd_list(cfg, args):
    proj = Project(cfg["owner"], cfg["maintenance_project_number"])
    for it in proj.items():
        if args.status and it.get("status") != args.status:
            continue
        c = it.get("content") or {}
        print("%-12s %-9s %-14s %s#%s %s" % (it.get("status", ""), it.get("area", ""),
                                            it.get("target repo", ""), c.get("repository", ""),
                                            c.get("number", "?"), c.get("title", "")[:70]))
    print(proj.url)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    p = sub.add_parser("add")
    p.add_argument("url")
    p.add_argument("--area", required=True)
    p.add_argument("--status", default="Todo")
    p = sub.add_parser("list")
    p.add_argument("--status")
    args = ap.parse_args()
    cfg = load_config()
    {"setup": cmd_setup, "add": cmd_add, "list": cmd_list}[args.cmd](cfg, args)


if __name__ == "__main__":
    main()
