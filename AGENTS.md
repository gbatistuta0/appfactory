# AGENTS.md

AppFactory is an MCP server that takes a SwiftUI iOS subscription app from idea to the App Store.

## Running the factory
1. Load the playbook: tool `playbook()` (or prompt `appfactory_run` / resource `appfactory://playbook`) and follow it.
2. Before any work, ask the user about every optional part (`run_options()`) and save the answers. Skip whatever they turn off.
3. A stage is done only when `pipeline_mark` passes its gate. App Store submission always stays with the human.

## Working on this repo
- `appfactory setup` / `appfactory doctor`; tests: `uv run pytest -q`.
- English only. No secrets or personal data in commits.
