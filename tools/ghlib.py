"""Shared helpers for the management tools: the gh CLI, config, the org projects.

Every tool talks to GitHub through `gh`, so one login and one set of scopes
serve them all. Tools that write as the bot set GH_TOKEN themselves (bot.py).
"""

import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.toml"

ANSI = re.compile(r"(?:\x1b|\^\[)\[[0-9;?]*[A-Za-z]")  # real escapes, and gh's "^[" rendering


def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


def gh(*args, json_out=False, stdin=None, env=None, check=True):
    """Run gh; die on failure unless check=False (then return None)."""
    e = dict(os.environ)
    if env:
        e.update(env)
    r = subprocess.run(["gh", *args], capture_output=True, text=True, input=stdin, env=e)
    if r.returncode != 0:
        if not check:
            return None
        die("gh %s failed:\n%s" % (" ".join(args), r.stderr.strip()))
    return json.loads(r.stdout) if json_out else r.stdout


def load_config():
    with CONFIG.open("rb") as f:
        return tomllib.load(f)


def strip_ansi(text):
    return ANSI.sub("", text)


def repo_entry(cfg, name):
    """The [[repo]] table for a short name ("oxrok") or full name ("oxrok/oxrok")."""
    for r in cfg.get("repo", []):
        if r["name"] == name or r["name"].split("/")[1] == name:
            return r
    die("config.toml has no [[repo]] named %r" % name)


def repo_path(cfg, name):
    """Local checkout of a repo, from its [[repo]] `path` (relative to the repo root)."""
    p = Path(repo_entry(cfg, name)["path"])
    return p if p.is_absolute() else (ROOT / p).resolve()


class Project:
    """An org project (Projects v2), by number."""

    def __init__(self, owner, number):
        if not number:
            die("no project number: run the tool's `setup` first")
        self.owner = owner
        self.number = number
        view = gh("project", "view", str(number), "--owner", owner,
                  "--format", "json", json_out=True)
        self.id = view["id"]
        self.url = view["url"]
        self.fields = {}
        for f in gh("project", "field-list", str(number), "--owner", owner,
                    "--format", "json", "--limit", "100", json_out=True)["fields"]:
            self.fields[f["name"]] = f

    def option(self, field, name):
        for o in self.fields[field].get("options", []):
            if o["name"] == name:
                return o["id"]
        die("field %s has no option %r" % (field, name))

    def add(self, url):
        return gh("project", "item-add", str(self.number), "--owner", self.owner,
                  "--url", url, "--format", "json", json_out=True)["id"]

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

    def ensure_select_field(self, name, options):
        if name in self.fields:
            return False
        gh("project", "field-create", str(self.number), "--owner", self.owner,
           "--name", name, "--data-type", "SINGLE_SELECT",
           "--single-select-options", ",".join(options))
        return True

    def set_status_options(self, statuses, colors=None, help_text=None):
        """Replace the built-in Status field's options."""
        status = self.fields["Status"]
        have = [o["name"] for o in status.get("options", [])]
        if have == statuses:
            return False
        opts = [{"name": s, "color": (colors or {}).get(s, "GRAY"),
                 "description": (help_text or {}).get(s, "")} for s in statuses]
        query = """mutation($f: ID!, $o: [ProjectV2SingleSelectFieldOptionInput!]) {
          updateProjectV2Field(input: {fieldId: $f, singleSelectOptions: $o}) {
            projectV2Field { ... on ProjectV2SingleSelectField { id } } } }"""
        gh("api", "graphql", "--input", "-",
           stdin=json.dumps({"query": query, "variables": {"f": status["id"], "o": opts}}))
        return True
