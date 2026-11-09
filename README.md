# oxrok management

The oxrok org's maintenance hub: how oxrok takes in work from upstream
sigrok, and how its own repositories are kept healthy.

oxrok ports libsigrok, sigrok-cli and their tools to Rust. Upstream's
GitHub repos collect pull requests that never land, or land slowly: new
drivers, models, fixes and firmware tools. This repo is where oxrok
decides which of them it wants and follows them to done. It is also where
the tools and rules live for the upkeep of `oxrok`, `oxrok-ui`,
`oxrok-website` and `vusb`: CI health, status prose that drifts from the
facts, dependency updates, branch protection, and what an agent may do
while helping with any of that.

- **Boards:** [Upstream intake](https://github.com/orgs/oxrok/projects/1)
  and [Maintenance](https://github.com/orgs/oxrok/projects/2), both of the
  oxrok org.
- **Issues:** upstream items in oxrok/oxrok, labelled `upstream` and
  `ws:<workstream>`; maintenance items in the repo they concern, labelled
  `maintenance` and `area:<x>`.
- **Watched:** sigrokproject/libsigrok, sigrok-util,
  sigrok-firmware-fx2lafw and sigrok-firmware (`config.toml`).

## Use

Needs Python 3.11+ and the GitHub CLI, logged in with the `project` scope
(`gh auth refresh -s project`). Writes made on an agent's behalf go
through `tools/bot.py` as the GitHub App `oxrok-bot`; its setup is in that
tool's help.

```
python3 tools/track.py intake     # upstream PRs not triaged yet
python3 tools/track.py report     # where everything stands
python3 tools/track.py add ...    # track one item
python3 tools/track.py move 123 "In progress"

python3 tools/ci.py failures --repo oxrok --since 7d   # CI failures, clustered
python3 tools/ci.py report --repo oxrok                # pass rate, top clusters
python3 tools/drift.py check                           # status prose vs facts
python3 tools/board.py list                            # the Maintenance board
python3 tools/rulesets.py apply all                    # the main-branch rulesets
```

With Claude Code (or another agent reading `AGENTS.md`), the skills in
`.claude/skills/` run the whole procedure: "do upstream intake", "what's
the upstream status", "run the CI doctor", "check the docs for drift".

## Files

| File | What |
| --- | --- |
| `AGENTS.md` | Rules: statuses, workstreams, how to triage; the maintenance rules |
| `docs/AGENT-POLICY.md` | What an agent may read and write, and how a skill is promoted to a workflow |
| `docs/HARDENING.md` | The baseline every repo is held to, and where each one stands |
| `config.toml` | Watched upstream repos, the org's repos, project numbers, field values |
| `decisions.toml` | Upstream PRs decided without an issue, with reasons |
| `seed.toml` | The first triage, 2026-11-09 (already loaded) |
| `flakes.toml` | Known CI flakes, by failure signature |
| `rulesets/` | The two main-branch rulesets, applied by `tools/rulesets.py` |
| `tools/track.py` | Upstream intake: all its GitHub reads and writes |
| `tools/ci.py`, `tools/drift.py` | CI digests; status prose against facts |
| `tools/bot.py`, `tools/board.py` | Writes as the bot; the Maintenance board |
| `tools/rulesets.py`, `tools/pin_actions.py` | Branch rules; SHA-pinned actions |
| `tools/ghlib.py`, `tools/check.py` | Shared helpers; the repo's own CI check |
| `.claude/skills/` | `upstream-intake`, `upstream-progress`, `ci-doctor`, `docs-drift` |

## Licence

GPL-3.0-or-later, as oxrok.
