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
A cluster marked `known flake` is in `flakes.toml` already. A line about
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
     --title "ci: <what>" --body-file <body.md> --label maintenance --label area:ci
   python3 tools/board.py add <pr-url> --area ci
   ```

   The body carries the cluster: signature, the runs, the excerpt, what
   you ran locally and its result.

**Real, without an evident fix** (a golden mismatch whose right side you
cannot tell, an emulator model that did not start): open an issue, not a
guess.

```
python3 tools/bot.py issue --repo oxrok/oxrok --title "ci: <job>: <first error line>" \
  --body-file <body.md> --label maintenance --label area:ci
python3 tools/board.py add <issue-url> --area ci
```

**Flake**: record it and, the first time, open an issue the same way.

```
python3 tools/ci.py flake --repo oxrok --signature "<signature>" --job "<job>" --issue <n>
```

Commit `flakes.toml` in this repo on a branch and open a PR for it (same
`bot.py` flow, `--label area:ci`).

**Infra**: nothing in a repo. If it repeats across days, an issue.

## 4. Report

Lead with what is on the latest run and whether main is buildable. Then,
per cluster: kind, decision, what you did (PR or issue link, or "noted").
Say in one line whether the emulator tier ran. Say what you could not
decide and why. Do not paste logs into the report; the digest is enough.

## Never

- Push to main, or to any branch not starting with `agent/`.
- Run anything with `--dangerously-skip-permissions` or equivalent.
- Change `.github/workflows/` to make a failure go away. A workflow fix is
  a PR like any other, explained.
- Delete, skip or bless a failing test or golden to get green. A failing
  case is a finding.
