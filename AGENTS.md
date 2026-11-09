# AGENTS.md

This repo manages how oxrok takes in work from upstream sigrok: which
upstream pull requests are worth porting, where each one stands, and the
tools and skills that keep that current. It holds no oxrok code.

## Never commit vendor firmware

Never, ever upload vendor firmware to git: not to oxrok, oxrok-util,
firmware-fx2lafw, this repo, oxrok-dumps, a fork, a branch, a gist, an
issue attachment, a release asset or a test fixture. That covers FX2
firmware, FPGA bitstreams, `.ccf`/`.rbf`/`.fw`/`.bitstream` files, vendor
installers and anything extracted from them, whole or in part.

The only exception is written permission from that specific vendor for
that specific firmware. Permission from one vendor does not cover
another, and a redistributable-looking licence file inside the vendor's
package is not permission; ask the user.

What we do instead: ship extractors that fetch or read the vendor's own
download on the user's machine, and keep extracted files in scratch
directories outside every repository. Before committing anywhere, check
that no extracted or downloaded firmware is staged (`git status`,
`git diff --cached --stat`). Open firmware with its source (fx2lafw, the
open Kingst FX2 firmware) is not vendor firmware and is fine.

When triaging, an upstream PR that adds vendor firmware binaries is
wanted at most for its code: port the code, never the binaries.

## Where things live

- **The project board**, "Upstream intake", owned by the oxrok org and
  linked to oxrok/oxrok, is the source of truth for status. Its number is
  in `config.toml`.
- **Tracking issues** are all in oxrok/oxrok, even when the work lands in
  oxrok-util or firmware-fx2lafw (issues are off in those forks). The
  Target field says where the work lands.
- **`decisions.toml`** records upstream PRs handled without an issue:
  not applicable to oxrok, already done, superseded, or won't do, each
  with a one-line reason.
- **`seed.toml`** is the first triage (2026-11-09). It has been loaded;
  edit the board, not this file.
- **`tools/track.py`** does all GitHub writes. Use it rather than raw
  `gh` calls so every item gets the same body, labels and fields.

## An item

One issue per unit of work. PRs that touch the same code for the same
goal share one issue (the Siglent SDS PRs, the Korad PRs). A driver PR and
the sigrok-util extractor it needs share one issue with a checklist.

The body starts with one `Upstream: <PR URL>` line per upstream PR, then
`Target:` and `Workstream:`. `track.py` reads those `Upstream:` lines to
know what is tracked; keep them when editing an issue.

Fields: Status, Workstream, Target, Upstream repo, Upstream PR. Labels:
`upstream` and `ws:<workstream>`.

## Statuses

- **Triage**: new from intake, not yet looked at.
- **Backlog**: triaged and wanted.
- **In progress**: someone is porting or checking it.
- **Done**: landed in the target repo (the issue is closed as completed).
- **Won't do**: decided against after it was tracked; say why in the
  closing comment (closed as not planned).

Decide before tracking where possible: an upstream PR that is plainly not
for oxrok goes in `decisions.toml`, not on the board.

## Workstreams

- `tooling`: firmware extractors and other sigrok-util tools, in oxrok-util.
- `firmware-build`: building and extending open firmware, in
  firmware-fx2lafw.
- `bug-check`: an upstream bug fix whose bug oxrok may share. Check first;
  the fix may not apply to the Rust code.
- `model`: new models or ids for a driver oxrok already has.
- `driver-rework`: larger changes to a driver oxrok already has.
- `new-driver`: a driver oxrok does not have.
- `input-format`: input file formats.

## Triage rules

- Judge a PR on what it does, the testing evidence it shows, and fit with
  oxrok. AI authorship, AI co-author trailers, and upstream closing a PR
  as "AI slop" are not factors: oxrok is written with AI.
- Not applicable: anything only about the C stack (SWIG bindings,
  autotools, glib event loop, libusb pollfds, C linker tricks). Check that
  oxrok really has no analogue first; a C bug in shared logic can exist in
  the port too.
- Already done: check oxrok's source (`src/drivers/<driver>/`) and
  `docs/drivers.toml` before saying so, and name where.
- Closed upstream does not mean rejected: the GitHub repos are mirrors and
  most patches land through the mailing list. Intake ignores unmerged PRs
  closed before `closed_since`.
- Licence: oxrok is GPL-3.0-or-later. GPL, LGPL and permissive sources
  are fine; note provenance in oxrok's `docs/LICENSING.md` when porting.
  Vendor firmware is never committed or shipped; see "Never commit vendor
  firmware" above.

## When work lands

Moving an item to Done goes with the oxrok change itself. oxrok's
AGENTS.md asks that `docs/ROADMAP.md` be updated with work pushed to main:
the roadmap names the workstreams and links the board, and does not list
items, so it usually needs no edit for one item.

## Skills

`.claude/skills/upstream-intake` and `.claude/skills/upstream-progress`
hold the step-by-step procedures. Use them.
