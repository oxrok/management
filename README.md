# oxrok management

How oxrok tracks work it takes in from upstream sigrok.

oxrok ports libsigrok, sigrok-cli and their tools to Rust. Upstream's
GitHub repos collect pull requests that never land, or land slowly: new
drivers, models, fixes and firmware tools. This repo is where oxrok
decides which of them it wants and follows them to done.

- **Board:** the "Upstream intake" project of the oxrok org, linked from
  [oxrok/oxrok](https://github.com/oxrok/oxrok/projects).
- **Issues:** in oxrok/oxrok, labelled `upstream` and `ws:<workstream>`.
- **Watched:** sigrokproject/libsigrok, sigrok-util,
  sigrok-firmware-fx2lafw and sigrok-firmware (`config.toml`).

## Use

Needs Python 3.11+ and the GitHub CLI, logged in with the `project` scope
(`gh auth refresh -s project`).

```
python3 tools/track.py intake     # upstream PRs not triaged yet
python3 tools/track.py report     # where everything stands
python3 tools/track.py add ...    # track one item
python3 tools/track.py move 123 "In progress"
```

With Claude Code (or another agent reading `AGENTS.md`), the skills in
`.claude/skills/` run the whole procedure: "do upstream intake", "what's
the upstream status".

## Files

| File | What |
| --- | --- |
| `AGENTS.md` | Rules: statuses, workstreams, how to triage |
| `config.toml` | Watched repos, project number, field values |
| `decisions.toml` | Upstream PRs decided without an issue, with reasons |
| `seed.toml` | The first triage, 2026-11-09 (already loaded) |
| `tools/track.py` | All GitHub reads and writes |
| `.claude/skills/` | `upstream-intake`, `upstream-progress` |

## Licence

GPL-3.0-or-later, as oxrok.
