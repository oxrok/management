#!/usr/bin/env python3
"""Offline checks for this repo, run in CI: the toml files parse, decisions
have known verdicts and refer to PRs, config names every tool the skills use."""

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERDICTS = {"not-applicable", "already-done", "wont-do", "superseded"}
REF = re.compile(r"^[\w.-]+/[\w.-]+#\d+$")
failures = []


def load(name):
    try:
        with (ROOT / name).open("rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        failures.append("%s: %s" % (name, e))
        return {}


cfg = load("config.toml")
for key in ("owner", "tracking_repo", "project_number", "statuses", "workstreams",
            "targets", "upstream", "repo"):
    if key not in cfg:
        failures.append("config.toml: missing %s" % key)
for r in cfg.get("repo", []):
    for key in ("name", "path"):
        if key not in r:
            failures.append("config.toml: [[repo]] without %s: %r" % (key, r))

seen = set()
for d in load("decisions.toml").get("decision", []):
    ref = d.get("ref", "")
    if not REF.match(ref):
        failures.append("decisions.toml: bad ref %r" % ref)
    if d.get("verdict") not in VERDICTS:
        failures.append("decisions.toml: %s has verdict %r" % (ref, d.get("verdict")))
    if not d.get("reason"):
        failures.append("decisions.toml: %s has no reason" % ref)
    if ref in seen:
        failures.append("decisions.toml: %s decided twice" % ref)
    seen.add(ref)

for it in load("seed.toml").get("item", []):
    if it.get("workstream") not in cfg.get("workstreams", []):
        failures.append("seed.toml: %s: unknown workstream" % it.get("title"))

if (ROOT / "flakes.toml").exists():
    for fl in load("flakes.toml").get("flake", []):
        for key in ("signature", "job", "first_seen", "last_seen", "count"):
            if key not in fl:
                failures.append("flakes.toml: flake without %s: %r" % (key, fl.get("signature")))

for skill in (ROOT / ".claude" / "skills").glob("*/SKILL.md"):
    text = skill.read_text()
    if not text.startswith("---\nname: %s\n" % skill.parent.name):
        failures.append("%s: frontmatter name differs from its directory" % skill)
    for tool in re.findall(r"tools/(\w+\.py)", text):
        if not (ROOT / "tools" / tool).exists():
            failures.append("%s names tools/%s, which does not exist" % (skill.name, tool))

for f in failures:
    print("check:", f)
print("check: %d problem(s)" % len(failures) if failures else "check: ok")
sys.exit(1 if failures else 0)
