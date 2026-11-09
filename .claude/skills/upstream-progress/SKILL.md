---
name: upstream-progress
description: Report on and update the oxrok "Upstream intake" project - what is in progress, what is next, and moving items between Triage, Backlog, In progress, Done and Won't do as work lands. Use when asked for upstream tracking status, what to work on next, to start or finish an upstream item, or to tidy the board.
---

# Upstream progress

Run from the root of the management repo. `AGENTS.md` has the statuses
and what they mean.

## Status report

```
python3 tools/track.py report
```

It prints counts by workstream and status, the In progress and Triage
items, and how many upstream PRs are untracked. If that last number is
not zero, say so and offer to run the `upstream-intake` skill.

When summarising for the user, lead with what is in progress and anything
stuck there, then what is ready next. Suggested next work, in order:
`bug-check` items (cheap, and they may affect users now), `tooling` and
`firmware-build` items that unblock drivers, then `model` items for
drivers with hardware or emulator coverage, then the rest.

## Starting an item

```
python3 tools/track.py move <issue> "In progress" --comment "<who, where: branch or PR>"
```

Work happens in the target repo (oxrok/oxrok, oxrok/oxrok-util,
oxrok/firmware-fx2lafw) under that repo's own rules. Never commit vendor
firmware or anything extracted from it, anywhere, without the vendor's
written permission (AGENTS.md, "Never commit vendor firmware"): test
extractors in scratch directories, and check `git diff --cached --stat`
before every commit. For oxrok/oxrok,
its AGENTS.md and docs/DRIVER_PORTING.md apply. Reference the issue in
commit messages (`oxrok/oxrok#<issue>`).

## Finishing an item

Only after the change is pushed to the target repo's main branch:

```
python3 tools/track.py move <issue> Done --comment "Landed in <repo>@<sha>: <one line>"
```

For an item with a checklist, tick the boxes in the issue body as each
part lands; move it to Done when all are ticked.

If checking shows the item is not needed (a `bug-check` whose bug oxrok
does not have, a model oxrok already supports):

```
python3 tools/track.py move <issue> "Won't do" --comment "<what was checked, file:line>"
```

## Tidying

- Items In progress with no activity for a month: ask the user whether
  they are still being worked on; move back to Backlog if not.
- Upstream PRs that got merged upstream after we tracked them: the item
  stays, the port is still needed; note it in the issue.
- Upstream PRs superseded by a newer one: intake will list the newer one;
  add it to the existing item rather than opening another.

Do not edit `seed.toml`; it was the first load only.
