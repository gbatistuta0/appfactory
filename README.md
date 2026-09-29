# AppFactory

[![CI](https://github.com/gbatistuta0/appfactory/actions/workflows/ci.yml/badge.svg)](https://github.com/gbatistuta0/appfactory/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)
![MCP](https://img.shields.io/badge/MCP-server-8A2BE2.svg)

An MCP server that lets your coding agent take a SwiftUI iOS subscription app from idea to the App Store.

**What it does:** idea harvesting and validation, design, SwiftUI code from a template, Supabase backend,
App Store Connect + RevenueCat setup, localization, analytics, ASO, screenshots and TestFlight. Every stage
has a gate the agent must pass. You do the final App Store submission.

## Quickstart

Requires a Mac, Python 3.12+ and [uv](https://docs.astral.sh/uv/).

### 1. Add the MCP to your agent

One line, no installer. The server command is `uvx --from git+https://github.com/gbatistuta0/appfactory appfactory-mcp`.

| Agent | How |
|---|---|
| Claude Code | `claude mcp add --scope user appfactory -- uvx --from git+https://github.com/gbatistuta0/appfactory appfactory-mcp` |
| Codex CLI | `~/.codex/config.toml`: `[mcp_servers.appfactory]` with `command = "uvx"`, `args = ["--from", "git+https://github.com/gbatistuta0/appfactory", "appfactory-mcp"]` |
| Gemini CLI | `~/.gemini/settings.json`: `"mcpServers": {"appfactory": {"command": "uvx", "args": ["--from", "git+https://github.com/gbatistuta0/appfactory", "appfactory-mcp"]}}` |
| Cursor | `~/.cursor/mcp.json`: same shape as Gemini |

### 2. Ask your agent: "Set up AppFactory"

The agent calls `setup_status`, asks which services you want, and turns them on. Keys never go through the chat:
for secrets it opens a local page in your browser (127.0.0.1 only, one-time token) where you type them; they are
stored in `~/.appfactory/config.toml` (mode 0600). `appfactory doctor` shows what is configured.

Then try this first prompt. It needs no accounts:

> Find 3 underserved iOS app niches in Health & Fitness and validate the best one

## Works with

Claude Code, Codex CLI, Gemini CLI and Cursor. The run playbook is served by the MCP server itself (tool
`playbook()`, prompt `appfactory_run`, resource `appfactory://playbook`), so any MCP-capable agent can follow it.

## Choose what you use

Every service is optional. Tools for a disabled service do nothing and the pipeline skips those stages
(`appfactory services enable|disable NAME`).

| Service | What it enables | Needs |
|---|---|---|
| research | Idea harvesting, ASO research (always on) | nothing |
| apple | App Store Connect: apps, in-app purchases, metadata, TestFlight | ASC API key, `asc` CLI |
| xcode | Local builds, simulator, archives | Xcode, `xcodegen` |
| supabase | Backend: database, edge functions, credits | access token, `supabase`, `deno` |
| revenuecat | Subscriptions and entitlements | RevenueCat secret key |
| ai | AI features through a server-side proxy | optional provider keys |
| firebase | Firebase Analytics setup | `firebase` CLI |
| github | A repo and issues per app | `gh` |
| design | Screen design through the claude-design MCP | claude-design MCP |
| maestro | End-to-end UI tests on the simulator | Maestro, Java 17+ |
| lottie | Lottie animations | `node` |

Details and credential steps: [docs/SETUP.md](docs/SETUP.md).

## Safety

- **Approvals.** Irreversible or outward actions (submission, store/backend/RevenueCat writes, GitHub pushes,
  uploads) do not run when an agent calls them. They wait for `appfactory approve <id>` in your terminal.
- **Dry run by default** for deploys, repo creation, uploads and issue writes.
- **Secrets stay local** and are scrubbed from every tool result.
- **Untrusted content** (App Store listings, reviews) is labelled as data, not instructions.

Full threat model and limits: [SECURITY.md](SECURITY.md).

## How a run works

1. **Interview.** Before any work the agent calls `run_options()`, asks you about every optional part, and saves
   your answers. Anything you turn off is skipped.
2. **Pipeline with gates.** `scaffold, design, features, backend, store setup, localize, analytics, ASO,
   metadata, screenshots, TestFlight`. A stage is done only when `pipeline_mark` passes its gate; blockers stop
   the run with a `NEEDS_HUMAN.md`.
3. **You submit.** App Store submission is always human, in the App Store Connect web UI.

## Docs

- [docs/SETUP.md](docs/SETUP.md): credentials and per-app choices
- [docs/PIPELINE_PLAYBOOK.md](docs/PIPELINE_PLAYBOOK.md): the why, order and gotchas of every stage
- [docs/TOOLS.md](docs/TOOLS.md): every tool (generated)
- [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), [AGENTS.md](AGENTS.md)

## License

[MIT](LICENSE)

<!-- mcp-name: io.github.gbatistuta0/appfactory -->
