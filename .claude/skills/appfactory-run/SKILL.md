---
name: appfactory-run
description: Use when building or shipping a new SwiftUI iOS subscription app end-to-end with the appfactory MCP (idea → spec → scaffold → design → features → backend → store setup → localize → analytics → ASO → screenshots → TestFlight), when the user says "run the factory" or "/appfactory-run", or when resuming a run after a NEEDS_HUMAN stop.
---

# AppFactory Run (Claude Code wrapper)

The playbook lives in the appfactory MCP server, not here. Load it first and follow it:

1. Call the `playbook` tool of the appfactory MCP server (or read the resource `appfactory://playbook`,
   or use the MCP prompt `run`).
2. Follow it exactly. In Claude Code, subagents are available: dispatch each stage to an Agent with the role
   `orchestrator_next_action` returns, keep at most one worker beside the lead, and never trust a worker's
   "done" over `pipeline_mark`.
