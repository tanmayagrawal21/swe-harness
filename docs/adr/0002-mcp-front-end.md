# ADR 0002: Conversational access through a stdlib MCP server, not a custom UI

## Context
The owner wants to talk to the harness, not only run a CLI, and it must work with any agent tool, not just
one vendor's. MCP servers often feel slow: package-manager cold starts, heavy SDK imports, tools that
block on long work, and oversized outputs.

## Decision
- Expose the harness as a stdio MCP server. Any MCP client becomes the conversational front end, and the
  deterministic engine stays the orchestrator. The tool list is the trust boundary: there is no merge tool,
  no tool that edits the reference workflow, and live runs require `confirm_live`.
- Standard library only, launched directly from the venv. Long runs are detached processes; tools read small
  files and return capped text. `explain_episode` redacts private terms, because gate comments may quote
  leaked values.
- Agent guidance lives in tool-neutral `AGENTS.md`; `CLAUDE.md` only imports it.
- A results UI, if needed later, is a read-only page generated from `results.json`, not an app.

## Verify
`uv run pytest -q tests/test_mcp_server.py` asserts startup under 2 s and calls under 0.5 s, input validation,
the live-run consent check and redaction. Measured locally: about 50 ms startup, under 60 ms per call.

## Revert
Delete `mcp_server.py`, its entry point, `.mcp.json` and `AGENTS.md`/`CLAUDE.md`; the CLI is unaffected.
