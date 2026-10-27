# Agent instructions for swe-harness

These apply to any coding agent (Codex, OpenCode, Cursor, Gemini CLI, Claude Code, ...).

## Driving the harness
Prefer the `swe-harness` MCP tools. If they aren't available, use the CLI (`uv run swe-harness ...`); the
same functions sit behind both.

- Start runs with `run_bench`. It returns a run_id at once; check progress with `run_status` (pass `since`
  to get only new events). Don't busy-poll: check every 10-30 s for dry runs, less often for live ones.
- Read results with `get_report` (summary first; `detail=full` only if needed) and `explain_episode` for why
  one task was blocked or merged.
- Dry runs (`executor=scripted`) are free. Run them without asking.
- Live runs (`claude`, `codex`, `opencode`) spend money. State the tasks, the variants and the per-call
  budget, ask the owner once, and only then pass `confirm_live=true`.
- Never edit `workflows/reference.yaml` to make a number look better. Propose a new variant with
  `propose_variant` and compare it against the reference.
- A gate-bypass merge in the reference workflow is a harness bug. Report it first, before anything else.

## Changing the code
- One decision per change, with an ADR in `docs/adr/` for any behaviour change.
- Tests run offline with fictional data only. Never put real personal data in the repo, commits or PR text.
- Run `uv run ruff check .` and `uv run pytest -q`, and check the exit codes directly (never through a pipe).
- Never loosen the merge rule, verdict parsing or the scorer's policy to make a test pass.
