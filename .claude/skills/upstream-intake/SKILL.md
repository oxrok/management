---
name: upstream-intake
description: Find new or updated upstream sigrok pull requests (libsigrok, sigrok-util, sigrok-firmware-fx2lafw, sigrok-firmware) that oxrok has not triaged, decide each one, and record it on the oxrok "Upstream intake" project or in decisions.toml. Use when asked to check upstream, do intake, triage sigrok PRs, or look for new PRs worth porting.
---

# Upstream intake

Run from the root of the management repo. Read `AGENTS.md` first: it has
the statuses, workstreams and triage rules this procedure relies on.

## 1. List what is untriaged

```
python3 tools/track.py intake
```

Each line is an upstream PR that no issue names and `decisions.toml` does
not cover. An empty list means intake is done; say so and stop.

## 2. Read each PR

For each one, read enough to decide:

```
gh pr view -R <owner/repo> <N> --json title,body,files,comments,commits
```

Look at: the files it touches (which driver, input, transport), the
testing it reports (on what hardware), what reviewers said, and whether
a later PR supersedes it.

## 3. Compare with oxrok

In a checkout of oxrok/oxrok (`git pull` first):

- the driver: `src/drivers/<driver_with_underscores>/`
- its status and models: `docs/drivers.toml`, `docs/DEVICES.md`
- for transports and formats: `src/usb/`, `src/serial/`, `src/hid/`,
  `src/scpi/`, `src/formats/`

Decide whether oxrok already has it, whether the bug can exist in the
Rust code, and which workstream it belongs to. Name the file and line
when you claim something is already done or already handled.

## 4. Record the decision

Group first: if an open issue already covers the same driver change, add
the PR to that issue instead of opening another one. Edit the issue body
to add an `Upstream: <URL>` line next to the others, and append it to the
item's Upstream PR field on the board.

Wanted, and nothing covers it yet:

```
python3 tools/track.py add --title "<driver>: <what>" --workstream <ws> \
  --target oxrok/oxrok --status Backlog \
  --upstream sigrokproject/libsigrok#<N> [more refs] --notes "<why, what to check>"
```

Use `--status Triage` only if you could not decide; say what is missing.
If the PR includes vendor firmware binaries, say in the notes that only
its code is to be ported, never the binaries (AGENTS.md, "Never commit
vendor firmware").
For sigrok-util and firmware PRs use the target from `config.toml`. When a
driver needs an extractor, put both PRs in one item with a checklist.

Not for the board: add a `[[decision]]` to `decisions.toml` with
`verdict` (`not-applicable`, `already-done`, `wont-do`, `superseded`) and
a one-line `reason`, then commit and push the management repo.

## 5. Finish

Run `python3 tools/track.py intake` again and confirm it prints nothing.
Report to the user: how many PRs came in, which went to the board (with
issue links) by workstream, and which were decided and why. Point out
anything that looks urgent for oxrok (a bug oxrok shares, a fix for a
driver someone is working on).
