# AppFactory

[![CI](https://github.com/gbatistuta0/appfactory/actions/workflows/ci.yml/badge.svg)](https://github.com/gbatistuta0/appfactory/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/appfactory.svg)](https://pypi.org/project/appfactory/)
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

Like any MCP server. Research works with no keys at all:

| Agent | Command |
|---|---|
| Claude Code | `claude mcp add appfactory -s user -- uvx appfactory@latest` |
| Codex CLI | `codex mcp add appfactory -- uvx appfactory@latest` |
| Gemini CLI | `gemini mcp add appfactory uvx appfactory@latest` |
| Cursor | `~/.cursor/mcp.json`: `{"mcpServers": {"appfactory": {"command": "uvx", "args": ["appfactory@latest"]}}}` |

### 2. Add keys for the services you use

Keys are environment variables on the MCP entry, named `APPFACTORY_<KEY>`. For example, App Store Connect in
Claude Code:

```bash
claude mcp add appfactory -s user \
  -e APPFACTORY_ASC_KEY_ID=ABC123DEFG \
  -e APPFACTORY_ASC_ISSUER_ID=00000000-0000-0000-0000-000000000000 \
  -e APPFACTORY_ASC_KEY_FILEPATH=~/keys/AuthKey_ABC123DEFG.p8 \
  -e APPFACTORY_TEAM_ID=TEAMID1234 \
  -- uvx appfactory@latest
```

You don't need to know the names up front: say **"Set up AppFactory"** (or just start a run). The agent asks
which services you want, one by one, and gives you the exact command for your agent with the keys that are
still missing. Keys never go through the chat. Every variable is listed in [docs/SETUP.md](docs/SETUP.md).

Then try this first prompt. It needs no accounts:

> Find 3 underserved iOS app niches in Health & Fitness and validate the best one

## Works with

Claude Code, Codex CLI, Gemini CLI and Cursor. The run playbook is served by the MCP server itself (tool
`playbook()`, prompt `run`, resource `appfactory://playbook`), so any MCP-capable agent can follow it.

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
