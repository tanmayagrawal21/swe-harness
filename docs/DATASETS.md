# Public datasets to test against

Surveyed 2026-10-27. Entries marked **verified** were checked live; the others come from prior knowledge.
Re-check every license before vendoring anything. Rule for this repo: **ship pointers, generators and
labels, never third-party patches of unclear license, and never real personal data.** Fetch at run time
into `runs/` (gitignored).

## Correctness (reviewer gate)

| rank | source | label | oracle | cost | notes |
|---|---|---|---|---|---|
| 1 | SWE-bench Verified (HF `princeton-nlp/SWE-bench_Verified`, **verified**) + model predictions from `swe-bench/experiments` (**verified**) | resolved / unresolved per model patch; the gold patch is a known-good item | `FAIL_TO_PASS` / `PASS_TO_PASS` tests (labels precomputed) | No docker if we trust the published labels; docker only to spot-check | 500 Python tasks, 12 repos. Real wrong patches from real models: the best "bad PR" source. Experiments entries point to artifacts in the submitter's repo or S3 (`logs/<id>/patch.diff`, `results/results.json`). No license is stated on the experiments repo or the HF card, so keep only pointers |
| 2 | SWE-smith (`SWE-bench/SWE-smith`, MIT, **verified**) | synthetic injected bug vs. its revert | tests that break | Reading is cheap; validating needs docker | 50k+ Python instances, an easier tier |
| 3 | BugsInPy | buggy vs. fixed commit | per-bug tests | per-bug venv | Python, no wrong-patch variants |
| - | Defects4J, APR patch-correctness sets, Multi-SWE-bench, CodeReviewer | | | | Wrong language, too heavy, or no correctness oracle. Deferred |

## Privacy (privacy gate)

**Generate, don't mine.** Real secret and PII corpora (SecretBench, bigcode PII) contain real people's data
and must not be redistributed. Plan:
- Generate fake-but-valid-format values (emails on non-example domains, phone numbers, API-key shapes from the
  gitleaks rules, which are MIT) and plant them in diffs, commit messages and PR text. Ground truth is known by
  construction, and every value is fictional.
- Use the gitleaks / detect-secrets rule test fixtures as a second, independent oracle.

## Unsafe changes (control gate)

| rank | source | label | oracle |
|---|---|---|---|
| 1 | CVEfixes (CC BY 4.0), GitHub Advisory DB (CC0) Python fix commits | the fix commit reversed with `git apply -R` = vulnerability-introducing PR (block); the fix itself = merge | Bandit / Semgrep on added lines; CyberSecEval insecure-code detector (MIT) |
| 2 | SecurityEval (MIT, 121 Python CWE cases) | insecure vs. secure sample | Bandit |
| 3 | Synthetic mutations of the toy repo: `verify=False`, `DEBUG=True`, removed auth decorator, env override of a limit | known by construction | hidden safety tests |

Keep an item only if the oracle flags the block version and not the merge version.

## Plan (milestone 3)

1. **Task sources.** Add a `TaskSource` interface that materialises tasks into a cache outside the repo: seed
   (repo at a commit), PR patch, label, and an oracle that is either a hidden test or a precomputed label.
2. **SWE-bench review tier.** For a small slice (one lightweight repo, roughly 10 gold, 10 resolved and 10
   unresolved model patches), clone the repo at `base_commit` and apply the patch as the PR. Gates review it;
   the precomputed label decides. The scored metrics are bad PRs blocked and good PRs merged. CI is skipped
   because these repos' suites need their own environments.
3. **Privacy generator.** Seeded generator of leak traps across the three surfaces (diff, commit message,
   PR text), plus clean controls with obviously fictional values.
4. **CVEfixes Python slice.** Reversed fix commits with a Bandit oracle, as control-gate items.

Steps 2 and 4 download third-party data (a 2 MB parquet, patch files, git clones) and need the owner's
go-ahead.
