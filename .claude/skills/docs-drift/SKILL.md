---
name: docs-drift
description: Bring oxrok's status prose (README counts and tables, docs/ROADMAP.md status line, docs/DEVICES.md coverage, CHANGELOG Unreleased, oxrok-ui's pin, the website's version strings) back in line with the facts tools/drift.py computes, as a draft PR by the bot. Use when asked to check the docs for stale numbers, refresh the README status, run the drift sweep, or after a release or a batch of ports.
---

# Docs drift

Run from the root of the management repo. `AGENTS.md` ("Maintenance") has
the rules: prose follows facts, never the other way; you write only on an
`agent/` branch, as the bot.

## 1. Fresh checkouts and the check

```
git -C ../../oxrok fetch -q origin && git -C ../../ui fetch -q origin && git -C ../../website fetch -q origin
python3 tools/drift.py check
```

(The paths are `config.toml`'s `[[repo]] path`.) Each line is
`file:line: prose says X; facts say Y`. The block "not decidable here"
lists dated counts with no fact source and stamps older than two weeks;
those are for a human unless step 2 says otherwise. The tool needs an
`oxrok` and `oxrok-emu` binary under the oxrok checkout's `target/`; if it
warns that one is missing, build it there first (`cargo build -p oxrok -p
oxrok-emu`) rather than skipping the checks.

If the check exits 0 with no findings, say so and stop.

## 2. Fix the prose

Work on `agent/docs-drift-<YYYY-MM-DD>` from `origin/main` of the repo the
finding is in. For each finding:

- **Counts and dates in a sentence**: write the fact's number and move the
  stamp (`On 2026-11-09`, `Status: 2026-11-09.`) to today. Keep the
  sentence's shape and the ASCII-only, terse style the repo uses.
- **Table rows** (cases, gcov): write the fact's values. If a driver is in
  `tests/emu` and absent from the table, add a row in the right table
  (hardware, stand-in, or the emulator-only table) in the existing order;
  do not drop rows.
- **DEVICES.md without a section for a driver**: do not invent hardware
  facts. Add a short section from `docs/drivers.toml`'s `behaviour`,
  `limits` and `evidence` lines for that driver, and say in the PR body
  that it was derived from drivers.toml.
- **CHANGELOG Unreleased missing a new driver**: add it to the existing
  "Drivers:" line under "### Added".
- **oxrok-ui pin or website version behind the latest release**: that is a
  release fan-out, not a drift fix. Report it; do not bump it here unless
  the user asked.
- **Undecidable items**: a "full run" count or a `cargo test` count can
  only be refreshed by running them; do so only if the user asked and the
  box allows it (see oxrok's `CONTINUE.md` for the load rules). Otherwise
  list them in the report.

Never edit `docs/drivers.toml`, `tests/emu`, or anything under `src/` from
this skill. If a fact looks wrong (a driver with 0 cases that has a model),
that is a finding for the report, not a prose edit.

## 3. Verify, push, PR

```
python3 tools/drift.py check            # the fixed findings are gone
cd ../../oxrok && python3 tools/site-data . >/dev/null   # still builds the site data
```

Then commit (`docs: refresh status counts to <date>`), and:

```
python3 tools/bot.py push ../../oxrok agent/docs-drift-<date>
python3 tools/bot.py pr --repo oxrok/oxrok --head agent/docs-drift-<date> --draft \
  --title "docs: refresh status counts (<date>)" --body-file <body.md> \
  --label maintenance --label area:docs
python3 tools/board.py add <pr-url> --area docs
```

The body is the list of findings the PR fixes, verbatim from the tool,
and the undecidable items it leaves. One PR per repo.

## 4. Report

What drifted, what the PR fixes, what is left for a human (with the
file and line), and whether the tool warned about a missing binary.
