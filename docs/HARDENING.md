# Hardening checklist

The baseline every org repository is held to, and where each one stands.
Update the table when something changes; the tools do not read it.

Repos: `oxrok`, `oxrok-ui`, `oxrok-website`, `vusb`, `management`. The
forks (`oxrok-util`, `firmware-fx2lafw`, `oxrok-firmware`, `oxrok-dumps`)
have no workflows and no automation; they get the rulesets when they get a
workflow.

## Baseline

1. **Actions pinned to commit SHAs**, release as a trailing comment, by
   `tools/pin_actions.py`. Dependabot keeps them current.
2. **`persist-credentials: false`** on every `actions/checkout`. A step that
   needs to push gets its own token in its own step.
3. **Dependabot** (`.github/dependabot.yml`): weekly, grouped, labelled
   `deps`; `cargo` where there is a `Cargo.toml`, `github-actions` everywhere.
4. **Secret scanning and push protection** on; `delete_branch_on_merge`;
   `allow_auto_merge` off.
5. **Two main-branch rulesets** from `rulesets/`, applied by
   `tools/rulesets.py apply`:
   - `main: protection`, no bypass: no deletion, no force push, required
     status checks (`config.toml` `[[repo]] checks`). Required checks hold
     for direct pushes too, so main changes only through a pull request
     whose checks passed.
   - `main: review`, bypass for org admins on pull requests only: one
     approving review, extra approval for unattributed changes, merge
     methods `merge` and `squash`. An admin can merge their own PR without
     a review; nobody can push to main; a bot PR needs the admin's review.
6. **The bot is never a bypass actor**, has no org role, and holds only
   Contents, Pull requests, Issues and Metadata on the installed repos.
7. **Default workflow token permissions: read** (org setting), and each
   workflow declares `permissions:` for what it needs.
8. **No static API keys in Actions secrets** until a skill reaches the
   `workflow_dispatch` rung of `docs/AGENT-POLICY.md`; then only the bot's
   App credentials, in an environment restricted to `main`.

## Status (2026-11-09)

| item | oxrok | oxrok-ui | oxrok-website | vusb | management |
| --- | --- | --- | --- | --- | --- |
| 1 pins | PR #70 | PR #6 | PR #2 | PR #1 | yes |
| 2 no persisted creds | PR #70 | PR #6 | PR #2 | PR #1 | yes |
| 3 Dependabot | PR #70 | PR #6 | PR #2 | PR #1 | yes |
| 4 scanning, branch delete | yes | yes | yes | yes | yes |
| 5 rulesets | yes | yes | yes | yes | yes |
| 6 bot not bypass | yes, once the App exists | | | | |
| 7 read-only token default | yes (org) | | | | |
| 8 no API keys in secrets | yes | yes | yes | yes | yes |

"PR #n" means the change is in that open pull request. The ruleset pair
was applied on 2026-11-09 and oxrok's earlier single ruleset ("main
branch": PR with one review, squash only, admin bypass always) removed.

## Known gaps

- oxrok's emulator tier skips when the runner has no vhci-hcd, and a
  skipped job satisfies a required check. The emulator jobs are therefore
  not in `checks`; `tools/ci.py` reports skipped runs instead.
- CodeRabbit is installed on the org and reads every PR. It is a reader
  with comment rights; it is not a reviewer the rulesets count.
- The forks have issues disabled and no CI, so nothing in this repo runs
  against them.
