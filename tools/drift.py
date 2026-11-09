#!/usr/bin/env python3
"""Find status prose that no longer matches the facts it describes.

The facts come from the repos themselves (tools/site-data, `oxrok -L`,
`oxrok-emu list`, the source tree, git tags). The prose is oxrok's README,
docs/ROADMAP.md, docs/DEVICES.md and CHANGELOG.md, oxrok-ui's pin of oxrok,
and the version strings on the website. Facts are never changed from prose;
prose follows facts.

Usage: tools/drift.py check [--oxrok DIR] [--ui DIR] [--website DIR] [--json]
       tools/drift.py facts [--oxrok DIR]

Exit status 1 when anything drifted, so this can become a CI check. Items the
tool cannot decide (a dated count with no fact source) are listed apart.
"""

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ghlib import die, load_config, repo_path  # noqa: E402

DATE = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")
STALE_DAYS = 14


def run(cmd, cwd, env=None):
    e = dict(os.environ)
    e.update(env or {})
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=e)
    if r.returncode != 0:
        die("%s failed in %s:\n%s" % (" ".join(map(str, cmd)), cwd, r.stderr.strip()[-2000:]))
    return r.stdout


def binary(oxrok, name):
    for sub in ("release", "debug"):
        p = oxrok / "target" / sub / name
        if p.exists():
            return p
    env = os.environ.get("OXROK_" + name.upper().replace("-", "_"))
    if env:
        return Path(env)
    return None


def list_section(text, header):
    out = []
    on = False
    for line in text.split("\n"):
        if line.startswith("Supported "):
            on = line.startswith(header)
            continue
        if on and re.match(r"^  \S", line):
            out.append(line.split()[0])
    return out


def latest_release_tag(oxrok):
    tags = run(["git", "tag", "-l", "v*"], oxrok).split()
    rel = [t for t in tags if re.match(r"^v\d+\.\d+\.\d+$", t)]
    if not rel:
        return None
    return max(rel, key=lambda t: [int(x) for x in t[1:].split(".")])


def collect_facts(oxrok, ui, website):
    f = {"date": dt.date.today().isoformat(), "warnings": []}
    site = json.loads(run(["python3", "tools/site-data", "."], oxrok))
    f["meta"] = site["meta"]
    f["drivers"] = {d["key"]: d for d in site["drivers"]}
    f["by_id"] = {}
    for d in site["drivers"]:
        for i in d.get("ids", []):
            f["by_id"][i] = d["key"]
    f["modules"] = sorted(p.name for p in (oxrok / "src" / "drivers").iterdir() if p.is_dir())
    ox = binary(oxrok, "oxrok")
    if ox:
        listing = run([str(ox), "-L"], oxrok)
        f["ids"] = list_section(listing, "Supported hardware drivers")
        f["decoders"] = list_section(listing, "Supported protocol decoders")
    else:
        f["warnings"].append("no oxrok binary under target/ (OXROK_OXROK=path): ids and decoders not checked")
    emu = binary(oxrok, "oxrok-emu")
    if emu:
        f["models"] = [l.split()[0] for l in run([str(emu), "list"], oxrok).split("\n") if l.strip()]
    else:
        f["warnings"].append("no oxrok-emu binary under target/: model count not checked")
    f["oracle_files"] = len(list((oxrok / "tests" / "emu").glob("*/*.oracle")))
    tag = latest_release_tag(oxrok)
    f["tag"] = tag
    if tag:
        at_tag = set(run(["git", "ls-tree", "--name-only", tag, "src/drivers/"], oxrok).split())
        at_tag = {Path(p).name for p in at_tag}
        f["new_modules"] = [m for m in f["modules"] if m not in at_tag]
    else:
        f["new_modules"] = []
    if ui and (ui / "Cargo.toml").exists():
        m = re.search(r'^oxrok = \{[^\n]*version = "=?([\d.]+)"', (ui / "Cargo.toml").read_text(), re.M)
        f["ui_pin"] = m.group(1) if m else None
    if website:
        f["website_versions"] = []
        for rel in ("content/install.md", "content/start.md", "content/zh/install.md",
                    "content/zh/start.md", "content/es/install.md", "content/es/start.md"):
            p = website / rel
            if not p.exists():
                continue
            for n, line in enumerate(p.read_text().split("\n"), 1):
                for m in re.finditer(r"(?:--version |\boxrok )(\d+\.\d+\.\d+(?:-[\w.]+)?)\b", line):
                    f["website_versions"].append((rel, n, m.group(1)))
    return f


class Report:
    def __init__(self):
        self.findings = []
        self.undecided = []

    def drift(self, path, line, prose, fact):
        self.findings.append({"file": str(path), "line": line, "prose": prose, "fact": fact})

    def note(self, path, line, text):
        self.undecided.append({"file": str(path), "line": line, "text": text})


def coverage_pct(driver, model):
    """The gcov percentage site-data recorded: the named model's, else the first."""
    cov = driver.get("coverage") or []
    for c in cov:
        if c.get("model") == model:
            return c.get("pct")
    return cov[0].get("pct") if cov else None


def check_readme(oxrok, f, rep):
    path = oxrok / "README.md"
    lines = path.read_text().split("\n")
    text = "\n".join(lines)

    def lineno(pos):
        return text.count("\n", 0, pos) + 1

    # The status paragraph.
    m = re.search(r"On (20\d\d-\d\d-\d\d) `src/(?:drivers|lib\.rs)` has (\d+) driver\s+modules,\s+with (\d+) driver\s+ids", text)
    if m:
        n = lineno(m.start())
        if int(m.group(2)) != len(f["modules"]):
            rep.drift(path, n, "%s driver modules (on %s)" % (m.group(2), m.group(1)),
                      "%d directories in src/drivers" % len(f["modules"]))
        if "ids" in f and int(m.group(3)) != len(f["ids"]):
            rep.drift(path, n, "%s driver ids (on %s)" % (m.group(3), m.group(1)),
                      "%d ids in `oxrok -L`" % len(f["ids"]))
    else:
        rep.note(path, 0, "no 'On DATE `src/drivers` has N driver modules' sentence found")

    # Tables: a row's first backticked id, "N cases", "gcov P%" or a bare "P%".
    for n, line in enumerate(lines, 1):
        if not line.startswith("| `") or ("cases" not in line and "%" not in line):
            continue
        ids = re.findall(r"`([\w-]+)`", line.split("|")[1])
        if not ids or "no model" in line:
            continue
        key = f["by_id"].get(ids[0], ids[0] if ids[0] in f["drivers"] else None)
        if not key:
            if "family" not in line:
                rep.note(path, n, "table row for `%s`: not a driver id" % ids[0])
            continue
        d = f["drivers"][key]
        cases = re.search(r"\b(\d+) cases\b", line)
        if cases is None:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) == 3 and re.fullmatch(r"\d+", cells[1]):
                cases = re.match(r"(\d+)", cells[1])
        gcov = re.search(r"(?:gcov )?(\d+\.\d+)%", line)
        if cases and d.get("cases") is not None and int(cases.group(1)) != int(d["cases"]):
            rep.drift(path, n, "`%s`: %s cases" % (ids[0], cases.group(1)),
                      "%d cases in tests/emu" % int(d["cases"]))
        cov = coverage_pct(d, ids[0])
        if gcov and cov is not None and "to" not in line and abs(float(gcov.group(1)) - cov) >= 0.05:
            rep.drift(path, n, "`%s`: gcov %s%%" % (ids[0], gcov.group(1)),
                      "gcov %.1f%% in tests/emu" % cov)

    m = re.search(r"there are (\d+) models \(`oxrok-emu list`\)", text)
    if m and "models" in f and int(m.group(1)) != len(f["models"]):
        rep.drift(path, lineno(m.start()), "%s models" % m.group(1),
                  "%d models in `oxrok-emu list`" % len(f["models"]))
    m = re.search(r"there are (\d+) `\.oracle` files", text)
    if m and int(m.group(1)) != f["oracle_files"]:
        rep.drift(path, lineno(m.start()), "%s .oracle files" % m.group(1),
                  "%d tests/emu/*/*.oracle" % f["oracle_files"])

    # Dated counts with no fact source, and stale stamps.
    today = dt.date.fromisoformat(f["date"])
    for n, line in enumerate(lines, 1):
        for d in DATE.findall(line):
            age = (today - dt.date.fromisoformat(d)).days
            if age > STALE_DAYS and not line.startswith("|"):
                rep.note(path, n, "stamp %s is %d days old: %s" % (d, age, line.strip()[:90]))
    m = re.search(r"Counts on (20\d\d-\d\d-\d\d): (\d+) cases passed in a full run", text)
    if m:
        rep.note(path, lineno(m.start()),
                 "full-run count (%s on %s) has no static fact source; rerun to refresh" % (
                     m.group(2), m.group(1)))


def check_roadmap(oxrok, f, rep):
    path = oxrok / "docs" / "ROADMAP.md"
    text = path.read_text()
    m = re.search(r"Status: (20\d\d-\d\d-\d\d)\.", text)
    if not m:
        rep.note(path, 1, "no 'Status: DATE.' line")
        return
    meta = f["meta"]
    m2 = re.search(r"(\d+) of libsigrok's (\d+) `src/hardware` drivers are\s+ported", text)
    if m2:
        n = text.count("\n", 0, m2.start()) + 1
        if int(m2.group(1)) != meta["ported"] or int(m2.group(2)) != meta["libsigrok_total"]:
            rep.drift(path, n, "%s of %s drivers ported" % (m2.group(1), m2.group(2)),
                      "%d of %d (tools/site-data)" % (meta["ported"], meta["libsigrok_total"]))
    m3 = re.search(r"the (\d+) still missing", text)
    if m3:
        n = text.count("\n", 0, m3.start()) + 1
        missing = meta["libsigrok_total"] - meta["ported"]
        if int(m3.group(1)) != missing:
            rep.drift(path, n, "%s still missing" % m3.group(1), "%d not ported" % missing)
    m4 = re.search(r"all (\d+) decoders of libsigrokdecode", text)
    if m4 and "decoders" in f and int(m4.group(1)) != len(f["decoders"]):
        rep.drift(path, text.count("\n", 0, m4.start()) + 1, "all %s decoders" % m4.group(1),
                  "%d decoders in `oxrok -L`" % len(f["decoders"]))


def check_devices(oxrok, f, rep):
    path = oxrok / "docs" / "DEVICES.md"
    text = path.read_text()
    for key, d in sorted(f["drivers"].items()):
        if "not-ported" in d.get("status", []) or "software" in d.get("status", []):
            continue
        if not any("`%s`" % i in text for i in d.get("ids", [key]) + [key]):
            rep.drift(path, 0, "no section mentions `%s`" % key,
                      "driver in docs/drivers.toml with status %s" % ",".join(d["status"]))


def check_changelog(oxrok, f, rep):
    path = oxrok / "CHANGELOG.md"
    text = path.read_text()
    m = re.search(r"## \[Unreleased\](.*?)(?=\n## \[)", text, re.S)
    section = m.group(1) if m else ""
    for mod in f["new_modules"]:
        key = mod.replace("_", "-")
        ids = f["drivers"].get(key, {}).get("ids", [key])
        if not any("`%s`" % i in section for i in ids + [key]):
            rep.drift(path, 0, "Unreleased does not name `%s`" % key,
                      "src/drivers/%s is new since %s" % (mod, f["tag"]))


def check_cross(f, rep, ui, website):
    if not f.get("tag"):
        return
    ver = f["tag"][1:]
    if ui and f.get("ui_pin") and f["ui_pin"] != ver:
        rep.drift(ui / "Cargo.toml", 0, "oxrok pin =%s" % f["ui_pin"], "latest release %s" % ver)
    for rel, n, v in f.get("website_versions", []):
        if v != ver:
            rep.drift(website / rel, n, "oxrok %s" % v, "latest release %s" % ver)


def cmd_check(args):
    cfg = load_config()
    oxrok = Path(args.oxrok) if args.oxrok else repo_path(cfg, "oxrok")
    ui = Path(args.ui) if args.ui else repo_path(cfg, "oxrok-ui")
    website = Path(args.website) if args.website else repo_path(cfg, "oxrok-website")
    ui = ui if ui.exists() else None
    website = website if website.exists() else None
    f = collect_facts(oxrok, ui, website)
    rep = Report()
    check_readme(oxrok, f, rep)
    check_roadmap(oxrok, f, rep)
    check_devices(oxrok, f, rep)
    check_changelog(oxrok, f, rep)
    check_cross(f, rep, ui, website)
    if args.json:
        print(json.dumps({"facts": {k: v for k, v in f.items() if k not in ("drivers", "by_id")},
                          "findings": rep.findings, "undecided": rep.undecided}, indent=1,
                         default=str))
    else:
        for w in f["warnings"]:
            print("warning: %s" % w)
        for d in rep.findings:
            print("%s:%s: prose says %s; facts say %s" % (d["file"], d["line"] or "-",
                                                           d["prose"], d["fact"]))
        if rep.undecided:
            print("\nnot decidable here (a human or a rerun):")
            for u in rep.undecided:
                print("  %s:%s: %s" % (u["file"], u["line"] or "-", u["text"]))
        print("\n%d drift(s), %d undecided; facts as of %s, release %s" % (
            len(rep.findings), len(rep.undecided), f["date"], f["tag"]))
    sys.exit(1 if rep.findings else 0)


def cmd_facts(args):
    cfg = load_config()
    oxrok = Path(args.oxrok) if args.oxrok else repo_path(cfg, "oxrok")
    f = collect_facts(oxrok, None, None)
    out = {k: v for k, v in f.items() if k not in ("drivers", "by_id")}
    out["ids"] = len(f.get("ids", []))
    out["decoders"] = len(f.get("decoders", []))
    out["models"] = len(f.get("models", []))
    out["modules"] = len(f["modules"])
    print(json.dumps(out, indent=1, default=str))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "facts"):
        p = sub.add_parser(name)
        p.add_argument("--oxrok")
        if name == "check":
            p.add_argument("--ui")
            p.add_argument("--website")
            p.add_argument("--json", action="store_true")
    args = ap.parse_args()
    {"check": cmd_check, "facts": cmd_facts}[args.cmd](args)


if __name__ == "__main__":
    main()
