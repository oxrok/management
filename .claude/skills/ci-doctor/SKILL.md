---
name: ci-doctor
description: Diagnose a repository's failing CI (oxrok, oxrok-ui, oxrok-website, vusb) from a bounded digest of the failed runs, tell real breakage from flakes and runner trouble, fix what has an evident fix on an agent/ branch as a draft PR by the bot, record flakes, and report. Use when asked why CI is red, to look at failed runs, to run the CI doctor, or to check CI health.
---

# CI doctor

Run from the root of the management repo. `AGENTS.md` ("Maintenance") has
the rules this procedure relies on: you read the digest the tool makes, not
raw logs; you write only on an `agent/` branch, as the bot; main is never
pushed.

## 1. Digest

```
python3 tools/ci.py failures --repo oxrok --since 7d
```

One section per cluster: a kind (`compile`, `test`, `lint`, `infra`,
`skipped`, `other`), the job, how many runs it hit and when, whether it is
on the latest run, the runs, and the first error block (at most 40 lines).
A cluster marked `known flake` is in `flakes.toml` already. A cluster
marked `tracked by <kind> <repo>#<n>` has an open pull request or issue
labelled `ci-doctor` whose `CI-Doctor:` line names its signature: someone
(you, an earlier run, a person) is already on it. A line about
the emulator tier being skipped means the runner had no vhci-hcd and that
run proved nothing about the emulator: always carry that into the report.

Read the cluster, not more. If the excerpt is not enough to decide, look
at the source the error names in the repo checkout (`config.toml`,
`[[repo]] path`), not at the log.

## 2. Decide each cluster

- **Real** (`compile`, `lint`, a `test` that names a line in the tree):
  it fails for a reason in the code. A compile error on one OS only is
  still real.
- **Flake**: the same job passed on a rerun of the same commit with no
  change. When unsure and the cluster is on the latest run, rerun once:

  ```
  python3 tools/ci.py rerun --repo oxrok <run-id>
  ```

  It waits and says `FLAKE` or `REAL` per job.
- **Infra**: package mirrors, 5xx from GitHub, runner lost, timeouts,
  disk. Nothing to fix in the tree; note it.

## 3. Act

**Tracked already** (`tracked by` in the digest): open nothing for it, and
do not work on it. Report it with the link. If the cluster is still on the
latest run while its PR is open, that is expected; if you think the PR
does not fix it, say so in the report, not in a second PR. `python3
tools/ci.py open --repo <repo>` lists the open items and their signatures.

**Everything you open** carries the label `ci-doctor` (with `maintenance`
and `area:ci`) and ends its body with one line per cluster it tackles,
exactly:

```
CI-Doctor: <owner/repo> | <signature>
```

`<owner/repo>` is the repo whose CI failed (also for a flakes.toml PR in
this repo); `<signature>` is the cluster's `signature:` line, copied. That
line is how the next run knows the cluster is taken.

**Real, with an evident fix** (a type mismatch, a missing import, a
format or clippy complaint, a golden the change plainly meant to update):

1. The repo checkout is a person's working tree, so do not switch its
   branch. Work in a worktree:
   `git -C <repo-dir> fetch -q origin && git -C <repo-dir> worktree add -b agent/ci-<slug> <scratch>/ci-<slug> origin/main`,
   and remove it when the PR is open (`git worktree remove`).
2. Make the smallest change that fixes it. Do not refactor around it.
3. Run the gate that failed, locally: for oxrok `cargo fmt --all --check`,
   `cargo clippy --workspace --all-targets --all-features`, or the test the
   excerpt names (`cargo nextest run -p oxrok <name>`); for the others the
   matching `make check` / `make test`. A fix you could not run locally is
   a draft PR that says so in its body.
4. Commit with a message that names the run (`CI run <id>`), then:

   ```
   python3 tools/bot.py push <repo-dir> agent/ci-<slug>
   python3 tools/bot.py pr --repo <owner/repo> --head agent/ci-<slug> --draft \
     --title "ci: <what>" --body-file <body.md> --label maintenance --label area:ci \
     --label ci-doctor
   python3 tools/board.py add <pr-url> --area ci
   ```

   The body carries the cluster: signature, the runs, the excerpt, what
   you ran locally and its result.

**Real, without an evident fix** (a golden mismatch whose right side you
cannot tell, an emulator model that did not start): open an issue, not a
guess.

```
python3 tools/bot.py issue --repo oxrok/oxrok --title "ci: <job>: <first error line>" \
  --body-file <body.md> --label maintenance --label area:ci --label ci-doctor
python3 tools/board.py add <issue-url> --area ci
```

**Flake**: record it and, the first time, open an issue the same way.

```
python3 tools/ci.py flake --repo oxrok --signature "<signature>" --job "<job>" --issue <n>
```

Commit `flakes.toml` in this repo on a branch and open a PR for it (same
`bot.py` flow, `--label area:ci --label ci-doctor`, and the cluster's
`CI-Doctor:` line).

**Infra**: nothing in a repo. If it repeats across days, an issue.

## 4. Report

Lead with what is on the latest run and whether main is buildable. Then,
per cluster: kind, decision, what you did (PR or issue link, or "noted").
Say in one line whether the emulator tier ran. Say what you could not
decide and why. Do not paste logs into the report; the digest is enough.

## In the workflow

`.github/workflows/ci-doctor.yml` runs this skill on a GitHub runner. You
are there when the prompt says so. The procedure is the same, except:

- The digest is made before you start, by the workflow:
  `checkouts/ci-doctor-digest.md` is step 1's output. Read it; do not run
  `ci.py failures` again.
- The session ends when you stop. Run every command in the foreground
  and wait for it (cargo may take many minutes; the timeout allows it).
  Never put one in the background or wait for a notification: none comes.
- The repo is the one the prompt names, checked out at
  `checkouts/<short name>` (`checkouts/oxrok`). Put worktrees under
  `checkouts/` too: `git -C checkouts/oxrok worktree add -b agent/ci-<slug>
  checkouts/ci-<slug> origin/main`. For a flakes.toml change, a worktree of
  this repo: `git worktree add -b agent/ci-flake-<slug> checkouts/ci-flake-<slug>
  origin/main`, then `python3 checkouts/ci-flake-<slug>/tools/ci.py flake ...`.
- You hold no write credential. Do not call `bot.py` or `board.py`, and
  `ci.py rerun` will fail: a cluster you would rerun is undecided; report
  it as that. Instead of `bot.py pr`/`issue`, record the write:

  ```
  python3 tools/plan.py pr --repo <repo> --dir checkouts/ci-<slug> \
    --signature "<signature>" --title "ci: <what>" --body-file <body.md>
  python3 tools/plan.py issue --repo oxrok --signature "<signature>" \
    --title "ci: <job>: <first error line>" --body-file <body.md>
  ```

  (`--for-repo <repo>` on a flakes.toml PR whose `--repo` is management.)
  plan.py adds the labels and the `CI-Doctor:` lines itself; leave them
  out of the body. A separate job opens them as the bot after checking
  them again; one that touches `.github/workflows/` or `rulesets/` is
  refused, so do not try.
- Write body files under `checkouts/`, not elsewhere.
- Your report is the workflow's log. Keep it to the format of step 4 and
  end with `python3 tools/plan.py show`.

## Never

- Push to main, or to any branch not starting with `agent/`.
- Run anything with `--dangerously-skip-permissions` or equivalent.
- Change `.github/workflows/` to make a failure go away. A workflow fix is
  a PR like any other, explained.
- Delete, skip or bless a failing test or golden to get green. A failing
  case is a finding.
