# Security

## Threat model

AppFactory tools are driven by coding agents, often unattended, that read untrusted web data (App Store
listings, competitor pages, reviews). A prompt injection in that data could try to make the agent spend money,
leak secrets or make irreversible changes to your App Store, Supabase, RevenueCat or GitHub accounts.

Defenses in the server:

- **Out-of-band approvals.** Irreversible or outward actions (App Store submission, `store_setup` apply, app
  creation, live backend deploys, Supabase SQL/secrets/projects, RevenueCat writes, GitHub repos/pushes/issues,
  App Store uploads, TestFlight, Custom Product Pages) do not run when an agent calls them. They create a pending
  record in `~/.appfactory/approvals/` and the human approves it with `appfactory approve <id>` in a terminal
  (interactive y/N). An approval is single use, bound to the exact arguments and expires after 30 minutes.
  Config `approvals = "off"` disables this, except for App Store submission and destructive SQL (DROP,
  TRUNCATE, ALTER … DROP, GRANT/REVOKE on auth, DELETE/UPDATE without WHERE), which always ask.
- **Dry run by default** for deploys, repo creation, preview uploads and GitHub issue writes.
- **Secrets never in tool results.** Known secret values are replaced with `***` in every tool result and in
  subprocess output. Secrets cannot be set through a tool; enter them with `appfactory setup`.
- **Untrusted content is labelled.** Results carrying third-party text include an `untrusted_content` note and
  the playbook tells agents to treat it as data, never as instructions.

Limits: approvals protect the MCP channel. An agent that can run arbitrary shell commands as your user can read
`~/.appfactory` and could bypass them; restrict shell access (allowlists, sandboxing) for unattended runs.

## Where secrets live

`~/.appfactory/config.toml` (mode 0600), plus Supabase service-role keys in `~/.appfactory/supabase/<ref>.json`
(0600) and your `.p8` key files. Nothing secret is written to app repos, and AI keys go only to server-side
Supabase secrets, never into the app binary.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting on this repository (Security tab → "Report a
vulnerability"). Do not open a public issue for security problems.
