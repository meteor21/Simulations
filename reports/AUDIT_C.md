# Audit C: candidate portrayal and historical validity

Audit scope: the recovered Python v0.2 implementation in `charisma_lab/agents_analysis.py`, `annotate.py`, `scoring.py`, `history.py`, `agents_bias.py`, and `evaluate.py`, its existing tests, and the research/data-contract documents. All observations below come from local synthetic fixtures. No provider requests, publisher scraping, model downloads, or neural-model inference were performed by this audit worker.

## Confirmed defects and fixes

1. **Candidate sentiment attribution could be changed by masking.** Before the fix, `target_context('Senator Alex Rowan was praised. Rival Sam Rowan was condemned.', ['Alex Rowan'])` produced `Senator TARGET_CANDIDATE was praised. Rival Sam TARGET_CANDIDATE was condemned.` Blind surname replacement incorrectly anonymized the rival as the target. Masking now replaces full aliases only and retains ambiguous surname references. The model identity suffix changes from `target-nli-v1` to `target-nli-v2`, so the new annotation method does not silently reuse earlier model annotations. Blank/punctuation aliases now never match instead of producing zero-width matches or an IndexError. This is a safer extraction heuristic, not a validated coreference system.

2. **Strict snapshots leaked scores before the candidate identity was known.** v0.2 set only the combined `media_recency_score` to missing, while still emitting national, local, issue, and other component scores. Strict eligibility now excludes the candidate's portrayals and service terms before `known_at`, so all dependent components remain missing. The legacy `score_candidate`, `news`, `favorability`, and `pedigree` path applies the same identity gate. Explicit retrospective/research modes remain distinct and can reconstruct later-known candidates.

3. **State inference used future registration data.** Inferring a historical local state from `cs_candidate_cycles` ignored `known_at`. Strict inference now filters those rows by the cutoff before resolving a state; a missing state leaves local features missing. A state explicitly supplied by the researcher still needs provenance and an appropriate historical interpretation.

4. **Duplicate URLs could satisfy the recent-coverage threshold.** The previous gate counted URLs with recent dates, so copies of one old article could make coverage appear sufficient. The gate now counts unique content hashes using the earliest observed publication in each cluster. Negative `min_recent_articles` values are rejected. Existing outlet-balanced weights and separate syndication diagnostics remain intact, with no political-orientation penalty.

5. **Walk-forward validation accepted missing temporal/race metadata and target leakage.** Missing `as_of`, election date, cycle, or race ID could survive the original comparisons. The evaluator now rejects missing/invalid metadata, nonintegral cycles, and outcome/identity metadata supplied as predictor features. It also checks that every prior-cycle training outcome predates the earliest test snapshot. An optional `outcome_available_at` column supports actual outcome-release dates; absent that column, election date is an explicit proxy and does not establish a true outcome-publication timestamp. Tests cover both delayed elections and delayed outcome availability.

## Executed commands and results

From `/workspace/Simulations`, using `/workspace/.venvs/midterm-sentiment/bin/python`:

```bash
# After adding regression cases, before modifying production code:
/workspace/.venvs/midterm-sentiment/bin/python -m pytest tests/test_audit_analysis.py --junitxml=/tmp/analysis-regressions-before.xml
# 13 failed, 1 passed in 1.40s; failures established the defects above.

# Final targeted verification after code changes (two additional regression cases included):
/workspace/.venvs/midterm-sentiment/bin/python -m pytest tests/test_audit_analysis.py tests/test_agents.py tests/test_core.py tests/test_history_eval.py tests/test_workers.py --junitxml=reports/audit_c_tests.xml
# 126 passed in 1.69s.

/workspace/.venvs/midterm-sentiment/bin/python examples/offline_demo.py --out /tmp/midterm-audit-c-offline
# Exit 0; synthetic SYN-A standing decreases 76.889029 -> 51.081849.
# Favorability 70.000000 -> 45.284371; portrayal 80.000000 -> 27.294089.
# Pedigree remains 80.667087; all SYN-B components remain missing.
```

The pre-fix JUnit evidence is preserved as `reports/audit_c_regressions_before.xml`. The targeted test run is `reports/audit_c_tests.xml`. An intermediate run reported 123 passes and one expected integration failure while worker B was changing the existing database-safety test; the final run above passed after that coordinated change. The integration owner records the full-suite and notebook verification separately in `reports/VALIDATION.md`.

## Verified retained behavior and limits

Existing tests pass for separate survey favorability (approval is not substituted), missing observations staying missing, future-published articles being excluded even in retrospective mode, current political-orientation ratings not labeling historical periods, model-provisional ratings being excluded, right/left outlets receiving equal importance weights, national/state/metro/local routing, dated service with exclusive end, exact-content deduplication, and historical result/pedigree cutoffs. `history.py` already clips overlapping service intervals, filters future results, requires pre-election baseline training, retains recorded losses, and leaves incomplete outperformance missing; no confirmed defect required a change there. `agents_bias.py` rejects candidate-query corpora for independent ideology estimation and emits unapproved, dated proposals rather than approved ratings.

These tests establish software behavior, not sentiment accuracy or electoral prediction gains. Strict mode gates candidate, document-version, survey, source-profile, source-rating, service, and pedigree data availability. The integration follow-up in `reports/AUDIT_C_ANNOTATION_CUTOFF.md` additionally enforces annotation creation/review availability before the cutoff. These guards still do **not** certify historical language-model training availability or prevent a modern model from remembering outcomes; model vintage and provenance need a separate audit for a real historical forecast claim. Exact content hashes do not solve paraphrased wire stories, OCR variants, syndication lineage, or correlated outlets. Validating a real portrayal model still requires a dated human-labeled political corpus, candidate disambiguation review, source/decade stratification, and declared temporal evaluation horizons.
