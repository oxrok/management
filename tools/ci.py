#!/usr/bin/env python3
"""Read a repository's CI history and hand an agent a bounded digest of it.

The agent never reads raw logs. This tool fetches them, strips the colour
codes and timestamps, keeps the first error block of each failed job (at most
40 lines), classifies it, and groups equal failures across runs into clusters.

Commands:
  runs      --repo R [--branch main] [--since 7d] [--limit 40]
  failures  --repo R [--branch main] [--since 7d] [--limit 40] [--json]
  rerun     --repo R RUN_ID [--timeout 3600]     rerun the failed jobs, wait, report
  flake     --repo R --signature S --job J [--issue N]   record a flake in flakes.toml
  flakes                                          list flakes.toml
  report    --repo R [--branch main] [--since 14d]        pass rate and top clusters
  open      --repo R                              open ci-doctor PRs and issues, by signature

A pull request or issue the CI doctor opens carries the label `ci-doctor` and
one line `CI-Doctor: <owner/repo> | <signature>` per cluster it tackles.
`failures` marks a cluster with an open item as `tracked by`, so a second
run of the doctor leaves it alone. Only that line and the title are read.

Kinds: compile (rustc), test (nextest/cargo test), lint (fmt, clippy, deny),
infra (runner, network, package install), skipped (the emulator tier did not
run because the runner had no vhci-hcd), other.

Logs are cached under ~/.cache/oxrok-management/logs by job id.
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ghlib import ROOT, die, gh, load_config, repo_entry, strip_ansi  # noqa: E402

CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "oxrok-management" / "logs"
FLAKES = ROOT / "flakes.toml"
EXCERPT_LINES = 40

LABEL = "ci-doctor"
MARKER = re.compile(r"^CI-Doctor: ([\w.-]+/[\w.-]+) \| (.{1,250})$", re.M)
# Where a ci-doctor item for a repo can live: the repo, the tracking repo
# (issues), and this one (flakes.toml PRs).
HOME_REPOS = ("oxrok/oxrok", "oxrok/management")

RUN_FIELDS = "databaseId,conclusion,status,createdAt,headSha,headBranch,event,displayTitle,url"

# (kind, pattern) in priority order; the first match in a log is the error block's start.
PATTERNS = [
    ("compile", re.compile(r"^error\[E\d+\]:")),
    ("compile", re.compile(r"^error: could not compile")),
    ("compile", re.compile(r"^error: linking with")),
    ("test", re.compile(r"^\s*FAIL \[")),
    ("test", re.compile(r"^thread '.*' panicked at")),
    ("test", re.compile(r"^test .* \.\.\. FAILED")),
    ("test", re.compile(r"^(FAIL|FAILED|error: test failed)")),
    ("lint", re.compile(r"^Diff in ")),
    ("lint", re.compile(r"^error: (?!could not compile|linking|test failed|process didn't exit|command).+")),
    ("lint", re.compile(r"^error\[(deny|license|bans|advisories)")),
    ("infra", re.compile(r"(E: (Unable to|Failed to fetch)|apt-get.* (failed|returned)|Temporary failure resolving)")),
    ("infra", re.compile(r"(504 Gateway|502 Bad Gateway|503 Service|Connection reset|Could not resolve host|curl: \(\d+\))")),
    ("infra", re.compile(r"(The runner has received a shutdown signal|lost communication with the server|The operation was canceled|exceeded the maximum execution time)")),
    ("infra", re.compile(r"(No space left on device|Killed process|out of memory|signal: 9)")),
    ("skipped", re.compile(r"skipped: no vhci-hcd")),
    ("other", re.compile(r"##\[error\]")),
]

LOG_LINE = re.compile(r"^(?P<job>[^\t]*)\t(?P<step>[^\t]*)\t(?P<ts>\S+)\s?(?P<text>.*)$")


def since_to_dt(s):
    m = re.match(r"^(\d+)([hd])$", s)
    if not m:
        die("--since takes e.g. 24h or 7d")
    n, unit = int(m.group(1)), m.group(2)
    delta = dt.timedelta(hours=n) if unit == "h" else dt.timedelta(days=n)
    return dt.datetime.now(dt.timezone.utc) - delta


def list_runs(repo, workflow, branch, since, limit):
    runs = gh("run", "list", "-R", repo, "--workflow", workflow, "--branch", branch,
              "--limit", str(limit), "--json", RUN_FIELDS, json_out=True)
    cutoff = since_to_dt(since).isoformat()
    return [r for r in runs if r["createdAt"] >= cutoff and r["status"] == "completed"]


def run_jobs(repo, run_id):
    return gh("run", "view", str(run_id), "-R", repo, "--json", "jobs", json_out=True)["jobs"]


def failed_log(repo, run_id, job_id):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / ("%s-%d.log" % (repo.replace("/", "_"), job_id))
    if f.exists():
        return f.read_text()
    text = gh("run", "view", str(run_id), "-R", repo, "--job", str(job_id), "--log-failed",
              check=False)
    if text is None:
        # A failed fetch is not an empty log: leave the cache alone and try again next time.
        print("warning: could not fetch the log of job %d" % job_id, file=sys.stderr)
        return ""
    f.write_text(text)
    return text


def clean_lines(raw):
    out = []
    for line in raw.split("\n"):
        m = LOG_LINE.match(line)
        text = m.group("text") if m else line
        text = strip_ansi(text).rstrip()[:240]  # one line of a dumped buffer stays one line
        if text:
            out.append(text)
    return out


def excerpt(lines):
    """(kind, first error line, excerpt lines) from a cleaned log."""
    # The runner's own cleanup and deprecation notices say nothing about the failure.
    for i, line in enumerate(lines):
        if line.startswith("Post job cleanup.") or line.startswith("##[warning]Node.js"):
            lines = lines[:i]
            break
    for kind, pat in PATTERNS:
        for i, line in enumerate(lines):
            if pat.search(line):
                return kind, line, lines[i:i + EXCERPT_LINES]
    tail = lines[-EXCERPT_LINES:]
    return "other", (tail[0] if tail else "(empty log)"), tail


def normalize(line):
    """A failure signature: the first error line with the volatile parts folded."""
    s = re.sub(r"0x[0-9a-f]+", "0xN", line)
    s = re.sub(r"\b[0-9a-f]{7,40}\b", "SHA", s)
    s = re.sub(r"\d+(\.\d+)?(ms|s|m)\b", "T", s)
    s = re.sub(r"\[\s*[\d.]+s\]", "[T]", s)
    s = re.sub(r":\d+:\d+\b", ":L:C", s)
    s = re.sub(r"(?<![E\w])\d+", "N", s)  # keep rustc codes (E0308) and digits inside names
    return s.strip()[:200]


def job_key(name):
    """A job name with its matrix slice folded, so shards cluster together."""
    return re.sub(r"\b\d+/\d+\b", "i/n", name)


def collect(repo, workflow, branch, since, limit):
    runs = list_runs(repo, workflow, branch, since, limit)
    clusters = {}
    skipped_runs = []
    for run in runs:
        # A green run can still have skipped the emulator tier, so look at every run's jobs.
        jobs = run_jobs(repo, run["databaseId"])
        emu = [j for j in jobs if j["name"].startswith("emulator (oxrok")]
        if emu and all(j["conclusion"] == "skipped" for j in emu):
            skipped_runs.append(run["databaseId"])
        if run["conclusion"] not in ("failure", "timed_out", "cancelled"):
            continue
        for job in jobs:
            if job["conclusion"] not in ("failure", "timed_out", "cancelled"):
                continue
            lines = clean_lines(failed_log(repo, run["databaseId"], job["databaseId"]))
            kind, first, lines = excerpt(lines)
            if job["conclusion"] in ("timed_out", "cancelled"):
                kind = "infra"
                first = "job %s" % job["conclusion"]
            sig = "%s | %s" % (job_key(job["name"]), normalize(first))
            c = clusters.setdefault(sig, {
                "signature": sig, "kind": kind, "job": job_key(job["name"]), "jobs": set(),
                "runs": [], "first_seen": run["createdAt"], "last_seen": run["createdAt"],
                "excerpt": lines, "first_line": first})
            c["jobs"].add(job["name"])
            c["runs"].append({"id": run["databaseId"], "url": run["url"],
                              "created": run["createdAt"], "sha": run["headSha"][:10],
                              "title": run["displayTitle"][:70], "job_id": job["databaseId"]})
            c["first_seen"] = min(c["first_seen"], run["createdAt"])
            c["last_seen"] = max(c["last_seen"], run["createdAt"])
    latest = runs[0]["databaseId"] if runs else None
    out = []
    for c in clusters.values():
        c["jobs"] = sorted(c["jobs"])
        c["count"] = len(c["runs"])
        c["on_latest_run"] = any(r["id"] == latest for r in c["runs"])
        c["runs"].sort(key=lambda r: r["created"], reverse=True)
        out.append(c)
    out.sort(key=lambda c: (not c["on_latest_run"], -c["count"], c["signature"]))
    return runs, out, skipped_runs


def load_flakes():
    if not FLAKES.exists():
        return []
    with FLAKES.open("rb") as f:
        return tomllib.load(f).get("flake", [])


def save_flakes(flakes):
    lines = ["# Known CI flakes, kept by tools/ci.py flake. A flake is a failure that",
             "# passed on a rerun with no change; its signature is ci.py's cluster key.", ""]
    for fl in flakes:
        lines.append("[[flake]]")
        for k in ("signature", "job", "first_seen", "last_seen"):
            lines.append("%s = %s" % (k, json.dumps(fl[k])))
        lines.append("count = %d" % fl["count"])
        if fl.get("issue"):
            lines.append("issue = %d" % fl["issue"])
        if fl.get("note"):
            lines.append("note = %s" % json.dumps(fl["note"]))
        lines.append("")
    FLAKES.write_text("\n".join(lines))


def printable(text, n):
    return "".join(ch for ch in text if ch.isprintable())[:n]


def open_items(repo):
    """Open ci-doctor PRs and issues that name a cluster of `repo`'s:
    [{"ref", "kind", "title", "signatures"}], read from the marker lines only."""
    out = []
    for where in dict.fromkeys((repo, *HOME_REPOS)):
        for kind in ("pr", "issue"):
            items = gh(kind, "list", "-R", where, "--label", LABEL, "--state", "open",
                       "--limit", "100", "--json", "number,title,body", json_out=True,
                       check=False) or []
            for it in items:
                sigs = [printable(m.group(2).strip(), 250)
                        for m in MARKER.finditer(it.get("body") or "") if m.group(1) == repo]
                if sigs:
                    out.append({"ref": "%s#%d" % (where, it["number"]), "kind": kind,
                                "title": printable(it["title"], 80), "signatures": sigs})
    return out


def tracked_by(items, signature):
    return ["%s %s" % (i["kind"], i["ref"]) for i in items if signature in i["signatures"]]


# --- commands ----------------------------------------------------------------

def cmd_runs(cfg, args):
    entry = repo_entry(cfg, args.repo)
    runs = list_runs(entry["name"], entry["ci"], args.branch, args.since, args.limit)
    for r in runs:
        failed = []
        if r["conclusion"] != "success":
            failed = [j["name"] for j in run_jobs(entry["name"], r["databaseId"])
                      if j["conclusion"] in ("failure", "timed_out", "cancelled")]
        print("%d %-8s %s %s %-40s %s" % (r["databaseId"], r["conclusion"], r["createdAt"][:16],
                                          r["headSha"][:8], r["displayTitle"][:40],
                                          "; ".join(failed)))


def cmd_failures(cfg, args):
    entry = repo_entry(cfg, args.repo)
    runs, clusters, skipped = collect(entry["name"], entry["ci"], args.branch, args.since,
                                      args.limit)
    known = {f["signature"] for f in load_flakes()}
    items = open_items(entry["name"])
    for c in clusters:
        c["known_flake"] = c["signature"] in known
        c["tracked_by"] = tracked_by(items, c["signature"])
    if args.json:
        print(json.dumps({"repo": entry["name"], "branch": args.branch, "runs": len(runs),
                          "failed_runs": sum(1 for r in runs if r["conclusion"] != "success"),
                          "emulator_skipped_runs": skipped, "clusters": clusters}, indent=1))
        return
    failed = sum(1 for r in runs if r["conclusion"] != "success")
    print("# %s %s: %d runs since %s, %d failed, %d clusters" % (
        entry["name"], args.branch, len(runs), args.since, failed, len(clusters)))
    if skipped:
        print("\nEmulator tier skipped (no vhci-hcd on the runner) in %d run(s): %s" % (
            len(skipped), ", ".join(str(s) for s in skipped)))
    for n, c in enumerate(clusters, 1):
        flags = []
        if c["on_latest_run"]:
            flags.append("ON LATEST RUN")
        if c["known_flake"]:
            flags.append("known flake")
        if c["tracked_by"]:
            flags.append("tracked by " + ", ".join(c["tracked_by"]))
        print("\n## %d. [%s] %s  (%d run%s, %s..%s)%s" % (
            n, c["kind"], c["job"], c["count"], "s" if c["count"] != 1 else "",
            c["first_seen"][:10], c["last_seen"][:10],
            "  " + ", ".join(flags) if flags else ""))
        print("signature: %s" % c["signature"])
        print("jobs: %s" % ", ".join(c["jobs"]))
        for r in c["runs"][:5]:
            print("run %d %s %s %s" % (r["id"], r["created"][:16], r["sha"], r["title"]))
        if c["count"] > 5:
            print("... and %d more" % (c["count"] - 5))
        print("```")
        for line in c["excerpt"]:
            print(line[:240])
        print("```")


def cmd_rerun(cfg, args):
    entry = repo_entry(cfg, args.repo)
    repo = entry["name"]
    before = {j["name"]: j["conclusion"] for j in run_jobs(repo, args.run_id)
              if j["conclusion"] in ("failure", "timed_out", "cancelled")}
    if not before:
        die("run %d has no failed jobs" % args.run_id)
    gh("run", "rerun", str(args.run_id), "-R", repo, "--failed")
    print("rerunning %d failed job(s) of %d: %s" % (len(before), args.run_id,
                                                    ", ".join(sorted(before))))
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        time.sleep(60)
        view = gh("run", "view", str(args.run_id), "-R", repo, "--json",
                  "status,conclusion,jobs", json_out=True)
        if view["status"] == "completed":
            break
    else:
        die("timed out waiting for run %d" % args.run_id)
    for j in view["jobs"]:
        if j["name"] in before:
            verdict = "FLAKE (passed on rerun)" if j["conclusion"] == "success" else \
                "REAL (%s again)" % j["conclusion"]
            print("%-50s %s" % (j["name"], verdict))
    print("run %d: %s" % (args.run_id, view["conclusion"]))


def cmd_flake(cfg, args):
    today = dt.date.today().isoformat()
    flakes = load_flakes()
    for fl in flakes:
        if fl["signature"] == args.signature:
            fl["last_seen"] = today
            fl["count"] += args.count
            if args.issue:
                fl["issue"] = args.issue
            if args.note:
                fl["note"] = args.note
            break
    else:
        fl = {"signature": args.signature, "job": args.job, "first_seen": today,
              "last_seen": today, "count": args.count}
        if args.issue:
            fl["issue"] = args.issue
        if args.note:
            fl["note"] = args.note
        flakes.append(fl)
    save_flakes(flakes)
    print("recorded: %s (count %d)" % (fl["signature"], fl["count"]))


def cmd_flakes(cfg, args):
    for fl in load_flakes():
        print("%-10s %-10s %3d  #%-5s %s" % (fl["first_seen"], fl["last_seen"], fl["count"],
                                            fl.get("issue", "-"), fl["signature"]))


def cmd_open(cfg, args):
    entry = repo_entry(cfg, args.repo)
    items = open_items(entry["name"])
    if not items:
        print("no open %s items for %s" % (LABEL, entry["name"]))
    for i in items:
        print("%s %s: %s" % (i["kind"], i["ref"], i["title"]))
        for s in i["signatures"]:
            print("  %s" % s)


def cmd_report(cfg, args):
    entry = repo_entry(cfg, args.repo)
    runs, clusters, skipped = collect(entry["name"], entry["ci"], args.branch, args.since,
                                      args.limit)
    total = len(runs)
    ok = sum(1 for r in runs if r["conclusion"] == "success")
    print("%s %s, last %s: %d runs, %d passed (%d%%), emulator skipped in %d" % (
        entry["name"], args.branch, args.since, total, ok,
        100 * ok // total if total else 0, len(skipped)))
    for c in clusters[:10]:
        print("%3d  %-8s %-45s %s" % (c["count"], c["kind"], c["job"][:45],
                                      c["first_line"][:80]))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, since="7d"):
        p.add_argument("--repo", required=True)
        p.add_argument("--branch", default="main")
        p.add_argument("--since", default=since)
        p.add_argument("--limit", type=int, default=40)

    common(sub.add_parser("runs"))
    p = sub.add_parser("failures")
    common(p)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("rerun")
    p.add_argument("--repo", required=True)
    p.add_argument("run_id", type=int)
    p.add_argument("--timeout", type=int, default=3600)
    p = sub.add_parser("flake")
    p.add_argument("--repo", required=True)
    p.add_argument("--signature", required=True)
    p.add_argument("--job", required=True)
    p.add_argument("--issue", type=int)
    p.add_argument("--count", type=int, default=1)
    p.add_argument("--note")
    sub.add_parser("flakes")
    p = sub.add_parser("open")
    p.add_argument("--repo", required=True)
    common(sub.add_parser("report"), since="14d")
    args = ap.parse_args()
    cfg = load_config()
    {"runs": cmd_runs, "failures": cmd_failures, "rerun": cmd_rerun, "flake": cmd_flake,
     "flakes": cmd_flakes, "report": cmd_report, "open": cmd_open}[args.cmd](cfg, args)


if __name__ == "__main__":
    main()
