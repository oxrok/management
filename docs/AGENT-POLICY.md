# Agent policy

How agents are allowed to work on the oxrok repositories, and how a skill
earns the right to run without a person watching.

## The rule

An agent never holds all three of these at once:

1. **untrusted input**: text written by someone outside the org (an issue,
   a pull request body or title, a commit message from a fork, an upstream
   PR, a web page, a dependency's changelog, a CI log of code from a fork);
2. **a secret worth stealing**: a token with write access, an API key, ssh
   keys to the bench, a publish credential;
3. **a path out**: a push, an issue or comment it can write, a network
   request it can shape.

Every documented compromise of a maintenance agent in 2025 and 2026 was that
combination (see "Read before promoting"). Each skill in this repo is placed
so one leg is missing.

## How the pieces are placed

- **Tools, not the agent, talk to GitHub.** `tools/*.py` do the reads and
  the writes, with fixed shapes: labels from a list, fields from
  `config.toml`, bodies built by the tool. The agent reads what a tool
  prints and calls a tool to act.
- **Digests, not raw text.** `ci.py` hands the agent the first error block
  of a failed job, colour codes and timestamps removed, 40 lines at most.
  `drift.py` hands it facts and the lines that differ. A log is the output
  of our own code, but it can carry anything a test printed; keep it
  bounded.
- **Writes are draft PRs or issues, as the bot.** `bot.py` acts as the
  GitHub App `oxrok-bot`, so a person approves what the agent did. The bot
  is never a bypass actor of a ruleset, and `bot.py push` refuses `main`.
- **The one skill that reads strangers' text is interactive.**
  `upstream-intake` reads upstream PRs. It runs as the user, in a Claude
  Code session the user is watching, and the user runs `track.py` on what
  it proposes. It is not scheduled and will not be until an intake digest
  (a tool that fetches and sanitises upstream PRs into a file) exists.
- **The bench box is not a CI runner.** The machine with ssh keys to the
  testers runs only skills whose inputs are the org's own repos. Nothing
  there reads issues or PRs from outside the org.
- **Never** `--dangerously-skip-permissions`, `--yolo`,
  `--trust-all-tools` or their equivalents in anything automated. The Nx
  compromise of August 2025 drove the victims' own agent CLIs with exactly
  those flags to hunt for secrets.

## Trust tiers

| tier | reads | writes | identity | runs |
| --- | --- | --- | --- | --- |
| 1 | the org's own repos, their CI runs and logs | draft PRs and issues on `agent/` branches | `oxrok-bot` | by hand today; `workflow_dispatch` next; cron later |
| 2 | text from outside the org (issues, external PRs) | labels, one comment, from an allowlist, through a separate job | job token, no secrets | not yet; design in "Later" |
| 3 | the org's repos plus the bench and the emulator testers | draft PRs | `oxrok-bot` | the bench box, by hand or a timer |

`ci-doctor` and `docs-drift` are tier 1. `upstream-intake` is a person's
tool, not a tier. There is no tier 2 skill today.

## The promotion ladder

A skill moves one rung at a time, and only after the criteria below.

1. **By hand** (today): a person runs the skill in Claude Code from this
   repo and watches it. Everything in this repo is here.
2. **`workflow_dispatch`**: a workflow in this repo runs the skill with
   `anthropics/claude-code-action` on a GitHub runner, started by a button.
   Token: the job's `GITHUB_TOKEN` with `contents: read`; the bot's App
   credentials are the only secret and are used only by `bot.py`, in a
   separate job that receives the agent's diff as an artifact. Bash is
   allowed only for the tool scripts; `WebFetch` and `WebSearch` are
   disallowed; `persist-credentials: false`; a timeout.
3. **Scheduled**: the same workflow on `schedule:`.

Criteria to climb:

- the skill ran by hand at least five times, and every edit it made was one
  the person would have made (no "surprising" change, no edit outside the
  files the digest named);
- the tool it relies on is deterministic given the same inputs, and its
  output is bounded;
- its only write path is a draft PR or an issue through `bot.py`;
- the person re-read "Read before promoting" and checked that the
  action's version in use has the fixes named there.

Demotion is immediate on any surprise: back to the rung below, and an
issue in this repo saying what happened.

## Read before promoting

The incidents that shaped this policy. Read the primary write-up, not a
summary, before moving any skill up a rung.

- **Clinejection** (Cline, 2026-01/02): an issue title reached a Claude
  prompt in a triage workflow with Bash allowed; `npm install` from the
  attacker's fork poisoned the Actions cache; a nightly publish job
  restored it and lost the publish tokens; a malicious `cline@2.3.0`
  shipped. Lesson: no Bash on untrusted input, no shared caches with
  release jobs, publish credentials in their own namespace.
- **PromptPwnd** (Aikido, 2025-12): Google's own gemini-cli triage leaked
  `GEMINI_API_KEY` and `GITHUB_TOKEN` through `gh issue edit`. Lesson: an
  agent that can write an issue has a path out.
- **Poisoning Claude Code** (Flatt, 2026-06): `claude-code-action` trusted
  any `[bot]` actor; a forged read error made the agent read
  `/proc/self/environ` and post OIDC credentials through the GitHub MCP
  tool; fixed in 1.0.94. Lesson: pin the action, keep `allowed_bots`
  empty, keep tool allowlists tiny.
- **run-gemini-cli GHSA-wpqr-6v78-jr5g** (2026-04): headless mode trusted
  `.gemini/` settings from the checkout, and `--yolo` ignored the tool
  allowlist. Lesson: a PR can carry agent configuration; the action must
  restore it from the base branch.
- **"Comment and Control"** (JHU, 2026-04) and the Trail of Bits Copilot
  work (2025-08): HTML comments and `<picture>` tags survived sanitising
  and carried the payload. Lesson: sanitising helps and is not a defence.
- **GitHub MCP "toxic agent flow"** (Invariant, 2025-05): a public issue
  made an agent with private-repo access leak private data into a public
  PR. Lesson: an agent's reach is the union of everything its token sees.

Primary sources: `anthropics/claude-code-action` `docs/security.md`;
`openai/codex-action` `docs/security.md`; `google-github-actions/run-gemini-cli`
`docs/trust-guidance.md`; GitHub's "agentic security principles" and the
Copilot coding agent risks page; OWASP Top 10 for Agentic Applications
(ASI01, goal hijack); Simon Willison, "the lethal trifecta".

## Later

- **Tier 2, inbound triage**: when oxrok has inbound issues worth it. Shape:
  a read-only job fetches the issue through a tool that strips HTML
  comments, hidden characters and images and caps the length; the agent
  sees that digest and a fixed menu (labels, a request for the missing
  template fields, a duplicate pointer); a separate job with
  `issues: write` applies the menu. GitHub Agentic Workflows (`gh-aw`) has
  this split built in and is the first thing to evaluate.
- **Intake digest**: the same fetch-and-sanitise step for upstream PRs, so
  intake can be proposed by a scheduled job and applied by a person.
- **Release fan-out**: on `release: published` in oxrok, bump the ui pin,
  the website's versions and screenshots, one draft PR per repo.
