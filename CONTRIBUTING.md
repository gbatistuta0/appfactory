# Contributing

## Setup
```bash
uv sync
uv run pytest -q
uv run appfactory doctor
```
Python 3.12+. The app template lives in `templates/swiftui-subscription/` (XcodeGen project); it is shipped
inside the wheel as `appfactory/templates`.

## Rules
- English only: code, comments, docs, commit messages.
- No secrets or personal data in commits, tests or fixtures (CI runs gitleaks). Commit with a
  `@appfactory.local` or GitHub `noreply` email; CI checks author emails.
- Keep it simple: prefer the standard library and existing helpers to new code or dependencies.
- Tests must pass on Linux and macOS. Do not call real services in tests.

## Adding a tool
1. Add a function to `src/appfactory/server.py` decorated with `@tool` and a docstring whose first paragraph
   says what it does (it becomes the tool description).
2. If it talks to an optional service, add it to `TOOL_SERVICES` in `server.py` (service names come from
   `SERVICES` in `src/appfactory/config.py`). Tools not listed always run.
3. If it is irreversible or writes to an external account, gate it with `_approval(...)` and default to dry run.
   If its result carries third-party text, add it to `UNTRUSTED_TOOLS`.
4. If it belongs to a pipeline stage, wire it into `pipeline.py` / `gates.py`.
5. Add a test, then regenerate the reference: `python docs/gen_tools.py`.

## Adding a service
Add an entry to `SERVICES` in `config.py` (description, keys, binaries), map its tools in `TOOL_SERVICES`,
and add a row to the README table.

## Pull requests
Small and focused, tests included, `uv run pytest -q` green.
