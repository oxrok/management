#!/usr/bin/env python3
"""Pin GitHub Actions to commit SHAs and stop checkouts persisting credentials.

Usage: tools/pin_actions.py [--dry-run] WORKFLOW.yml...

For every `uses: owner/repo@ref` that is not already a 40-hex SHA, the ref is
resolved through the GitHub API and rewritten as `owner/repo@<sha> # <version>`,
where <version> is the most specific tag at that commit (so Dependabot can bump
it) or the branch name. Actions that read their own ref name as an input get the
input added (`dtolnay/rust-toolchain@stable` becomes a SHA plus
`toolchain: stable`; `taiki-e/install-action@nextest` becomes a SHA plus
`tool: nextest`). Every `actions/checkout` step gets `persist-credentials: false`
unless it already says otherwise.

Needs the gh CLI. Edits in place; review the diff.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ghlib import die, gh  # noqa: E402

USES = re.compile(r"^(?P<lead>\s*(?:-\s+)?uses:\s+)(?P<repo>[\w.-]+/[\w.-]+)(?P<sub>/[^@\s]+)?@(?P<ref>[^\s#]+)(?P<rest>.*)$")
SHA = re.compile(r"^[0-9a-f]{40}$")

# Actions whose ref name is an input; pin to the SHA and pass the ref as that input.
REF_IS_INPUT = {
    "dtolnay/rust-toolchain": "toolchain",
    "taiki-e/install-action": "tool",
}
# Where to pin those: a branch whose head is the action's current code.
REF_IS_INPUT_PIN = {
    "dtolnay/rust-toolchain": "master",
    "taiki-e/install-action": None,  # the latest release tag
}

_tags_cache = {}


def tags(repo):
    if repo not in _tags_cache:
        out = []
        for page in range(1, 6):
            got = gh("api", "repos/%s/tags?per_page=100&page=%d" % (repo, page), json_out=True)
            out.extend(got)
            if len(got) < 100:
                break
        _tags_cache[repo] = out
    return _tags_cache[repo]


def semver_key(name):
    nums = re.findall(r"\d+", name)
    return (len(nums), [int(n) for n in nums])


def latest_release_tag(repo):
    named = [t["name"] for t in tags(repo) if re.match(r"^v?\d+\.\d+\.\d+$", t["name"])]
    if not named:
        die("%s: no semver tags" % repo)
    return max(named, key=semver_key)


def resolve(repo, ref):
    """(sha, label) for a tag or branch name."""
    by_name = {t["name"]: t["commit"]["sha"] for t in tags(repo)}
    if ref in by_name:
        sha = by_name[ref]
        same = [n for n, s in by_name.items() if s == sha]
        label = max(same, key=semver_key)  # v2.0.12 over v2
        return sha, label
    head = gh("api", "repos/%s/git/ref/heads/%s" % (repo, ref), json_out=True, check=False)
    if head:
        return head["object"]["sha"], ref
    die("%s@%s: not a tag or branch" % (repo, ref))


def indent_of(line):
    return len(line) - len(line.lstrip(" "))


def key_indent(uses_line):
    """Column of the `uses` key (after `- ` if present)."""
    m = re.match(r"^(\s*)(-\s+)?uses:", uses_line)
    return len(m.group(1)) + len(m.group(2) or "")


def step_end(lines, i, kcol):
    """Index after the last line of the step whose `uses:` is at lines[i]."""
    j = i + 1
    while j < len(lines):
        s = lines[j]
        if s.strip() == "" or s.lstrip().startswith("#"):
            j += 1
            continue
        if indent_of(s) < kcol or (indent_of(s) == kcol and s.lstrip().startswith("- ")):
            break
        if indent_of(s) < kcol:
            break
        j += 1
    return j


def ensure_with(lines, i, kcol, key, value):
    """Add `key: value` under the step's `with:` block (creating it) unless the key exists."""
    end = step_end(lines, i, kcol)
    with_idx = None
    for j in range(i + 1, end):
        if indent_of(lines[j]) == kcol and lines[j].strip() == "with:":
            with_idx = j
    if with_idx is not None:
        for j in range(with_idx + 1, end):
            if indent_of(lines[j]) > kcol and re.match(r"\s*%s\s*:" % re.escape(key), lines[j]):
                return False
        lines.insert(with_idx + 1, " " * (kcol + 2) + "%s: %s" % (key, value))
        return True
    lines.insert(i + 1, " " * kcol + "with:")
    lines.insert(i + 2, " " * (kcol + 2) + "%s: %s" % (key, value))
    return True


def process(path, dry_run):
    lines = path.read_text().split("\n")
    changed = []
    i = 0
    while i < len(lines):
        m = USES.match(lines[i])
        if not m:
            i += 1
            continue
        repo, ref = m.group("repo"), m.group("ref")
        kcol = key_indent(lines[i])
        if repo == "actions/checkout":
            if ensure_with(lines, i, kcol, "persist-credentials", "false"):
                changed.append("%s: persist-credentials: false" % repo)
        if SHA.match(ref):
            i += 1
            continue
        if repo in REF_IS_INPUT:
            pin = REF_IS_INPUT_PIN[repo] or latest_release_tag(repo)
            sha, label = resolve(repo, pin)
            if ensure_with(lines, i, kcol, REF_IS_INPUT[repo], ref):
                changed.append("%s: %s: %s" % (repo, REF_IS_INPUT[repo], ref))
        else:
            sha, label = resolve(repo, ref)
        lines[i] = "%s%s%s@%s # %s" % (m.group("lead"), repo, m.group("sub") or "", sha, label)
        changed.append("%s@%s -> %s (%s)" % (repo, ref, sha[:12], label))
        i += 1
    if changed and not dry_run:
        path.write_text("\n".join(lines))
    return changed


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("files", nargs="+")
    args = ap.parse_args()
    for f in args.files:
        for c in process(Path(f), args.dry_run):
            print("%s: %s" % (f, c))


if __name__ == "__main__":
    main()
