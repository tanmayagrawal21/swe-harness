# ADR 0001: The harness enforces the merge gate; the scorer re-checks it independently

## Context
In the reference project the orchestrating agent once merged 16 PRs itself; a retro review found 8 real
bugs. Later failures came from leaks in default squash messages and from gates that went stale when main
moved. Rules that live only in prompts can be skipped by the agent that holds them.

## Decision
- The orchestrator is code (`engine.py`), not an agent. Agents only commit (author) or post verdicts (gates).
- A verdict counts only if the reply has exactly one verdict line that binds it to the current head SHA
  (at least 7 hex chars). No verdict line, conflicting verdicts, or a silent or crashed gate fail closed.
  (Originally "the first line"; the first live run showed models often reason first, which made 20 of 43
  verdicts unparseable. Binding to the SHA, not line position, is what matters.)
- The merge is executed by the harness on behalf of the configured merger role, only when the workflow's
  merge rule holds, with the workflow's explicit squash message.
- The scorer does not trust the engine. It replays the forge's event log against a fixed policy (the
  reference merge rule) and inspects the final git state. Variants are judged by the same policy, so a
  weaker variant shows its bypasses as numbers.

## Verify
`uv run pytest -q tests/test_score.py tests/test_engine.py` and
`uv run swe-harness bench` (exits non-zero if the reference variant has any gate-bypass merge).

## Revert
Revert this ADR's commits; there is no persistent state outside `runs/`.
