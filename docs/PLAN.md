# Milestone 1 plan

Goal: a small, solid harness that (a) runs a multi-agent SWE workflow described in YAML and
(b) measures it against a benchmark with ground truth, offline and cheaply.

## Decisions

1. **The harness enforces the merge gate, not the agents.** The engine is a deterministic state
   machine (the "orchestrator never writes code" rule becomes structural). Agents only author
   commits and post verdicts. The merge is executed by the harness on behalf of the configured
   merger role, and only when the configured rule holds. See ADR 0001.
2. **The scorer trusts nothing the engine claims.** It replays the append-only event log and the
   final git state, and recomputes every metric against a fixed *benchmark policy* (the reference
   gate rule), independently of the variant being measured. A variant that merges without gates
   therefore shows non-zero gate-bypass merges.
3. **Local forge, no GitHub.** PRs are branches plus metadata in a local git repo. Nothing is pushed.
4. **Adversarial PR injection.** Each task's first PR is pre-written (clean, planted bug, privacy
   leak, unsafe change). Gates must decide; ground truth is hidden tests and a private-terms scan
   that live outside the toy repo. Later rounds are written by the workflow's author role.
5. **Executors are pluggable.** `scripted` (dry, deterministic, free), `claude` (`claude -p`
   stream-json), and a generic CLI executor for Codex/OpenCode (experimental).
6. **Whips are supervision, not polling.** Each agent call is supervised; silence longer than the
   role's threshold cancels and respawns it. Faults (hangs) are injected per task to measure
   detection and recovery time.

## Out of scope for M1

- GitHub forge adapter, QA/auditor scoring, prompt optimisation (google-research/harness2 noted in
  README as a later step).
