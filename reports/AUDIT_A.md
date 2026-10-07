# Identity, race membership, geography and political-orientation audit

Audit performed October 6, 2026 (America/New_York). The uploaded v0.2 package was audited in place. No provider requests, election database modifications, invented real candidates, or source-rating purchases were performed by this audit worker. The integration owner captured the unchanged package's 116 passing tests before edits; passing that original suite did not establish the missing edge cases below.

## Confirmed defects and corrections

1. **Conflicting person identities could coexist.** `identity_link` accepted `person:two` when the candidate registry already named `person:one`; alias CSV imports could overwrite either a registry or crosswalk identity. Both paths now reject conflicts for manual review. Additive aliases preserve previously documented full names. The acquisition worker separately guards `Store.candidate`.
2. **Source evidence was silently dropped.** Source-profile IDs omitted observation time, geographic detail, status and several other stored attributes; bias-assessment IDs omitted evidence URL, native numeric rating/scale, confidence and license. `INSERT OR IGNORE` silently lost distinct observations. IDs now cover stored observation fields, repeat identical imports remain idempotent, and profile lookup breaks observation ties deterministically. Source permissions/provider IDs retain their existing separate update rules.
3. **Bias disagreement lost provenance.** Two equally dated, conflicting labels from the same provider collapsed to an insertion-order choice at lookup. All tied latest observations are now returned with their evidence; disagreement yields `Mixed/Disputed` and a NULL ordinal index. An explicit genre rating takes precedence over the provider's `all` fallback. Hostname case/`www.` normalization is consistent on write/read. Native ratings are retained, not averaged or treated as quantitative political distance.
4. **Service dates had incorrect boundaries.** CSV date-only service starts and exclusive ends were interpreted as 23:59:59. They now use midnight UTC, consistent with the existing congress-legislators YAML importer. Evidence availability remains conservatively end-of-day. This prevents attributing almost the whole terminal day to the departed officeholder.
5. **Edition routing matched neighboring names.** `/local/mi` matched `/local/miami/story`. Edition prefixes now match the named path component or its descendants, preserving national/state/metro/local distinctions.
6. **Annotation CSV could not retain historical review evidence.** In coordination with the other workers' strict annotation-time checks, the importer now accepts `annotated_at`, `annotation_basis`, and `annotation_evidence_url`. Historical review timestamps require the store's explicit evidence checks; undated imports receive truthful current creation time.

## Actual validation commands and results

The original package extracted during baseline notebook execution remains separate at `/workspace/midterm-baseline-notebook/midterm_sentiment_code_v0_2`.

```bash
cd /workspace/midterm-baseline-notebook/midterm_sentiment_code_v0_2
PYTHONPATH=/workspace/midterm-baseline-notebook/midterm_sentiment_code_v0_2 \
  /workspace/.venvs/midterm-sentiment/bin/python -m pytest \
  /workspace/Simulations/tests/test_audit_identity.py --import-mode=importlib --tb=no \
  --junitxml=/workspace/Simulations/reports/audit_a_regressions_before.xml
```

Result: **12 failed, 1 passed** against unchanged v0.2. Failures include all four direct reproductions: conflicting person IDs accepted, two rating-evidence URLs stored as one record, date-only exclusive end recorded at 23:59:59, and Miami incorrectly routed to Michigan. The genre-specific fallback test is a passing control for behavior that had depended on tied row order.

```bash
cd /workspace/Simulations
/workspace/.venvs/midterm-sentiment/bin/python -m pytest \
  tests/test_audit_identity.py tests/test_agents.py tests/test_core.py \
  --junitxml=reports/audit_a_tests.xml
```

Result after corrections: **103 passed**, including **13 identity/provenance audit cases**. The integration owner runs the complete suite, offline demonstrations and regenerated notebook separately; see `VALIDATION.md` for final integrated results.

## Race membership and remaining research limits

- FEC/finance input remains `registry_only`; officeholder YAML creates neither ballot membership nor missing losers. Explicit roster input remains necessary to verify contestants. No successful-candidate filter was introduced.
- The acquisition worker owns `select_cohort`: notified and coordinated fixes for preserving `election_id`/`stage` and optional cutoff filtering. Selecting 24 distinct people must not silently discard their distinct primary/general/special contest records in exported research data; the integration owner was notified about pilot export handling.
- The existing identity/alias tables still are not a complete versioned identity-evidence ledger. Alias strings have no separate applicability intervals, crosswalks retain one accepted person per ID, and roster records are keyed by candidate/election rather than an append-only membership history. Strict backtests need dated reviewed inputs and cannot infer past availability from today's registry.
- Geography remains evidence about coverage, not headquarters or voter readership. The seed's one state outlet in most states is insufficient to certify representative local coverage. Current source-rating valid periods and availability continue to prevent retrospective backfilling; no partisan sentiment-weight penalty was added.
- New observation IDs preserve future imports; they cannot recover evidence already discarded by an older database. Reimport the original source evidence when available. No existing database was migrated or rewritten during this audit.
- Correctly modeling complete historical loser rosters, withdrawals, archive survival, changes to historical service records and survey representativeness requires additional sourced data. Synthetic tests establish software behavior, not substantive accuracy or representativeness.

## Integration compatibility follow-up

The integration owner requested an explicit test of importing original v0.2 seed observations into an existing database. A temporary copy of `/workspace/midterm-baseline-notebook/midterm_sentiment_work/Midterm_Sentiment_Agents.sqlite` reproduced counts growing from **63 profiles / 6 ratings** to **126 / 12** under the initial expanded digest implementation. The baseline file was not modified.

Profile and rating imports now look up equality across all stored observation fields before generating a new ID. Exact older observations retain their original IDs, while genuinely different evidence is still stored separately. Repeating the same temporary-copy import now leaves **63 / 6** unchanged. Service-term digest inputs were not expanded, so this digest migration problem did not apply to terms.

Added two regression tests that explicitly seed the old v0.2 digest IDs, verify stable count/ID on reimport, and verify distinct new evidence remains additive. Command `/workspace/.venvs/midterm-sentiment/bin/python -m pytest tests/test_audit_identity.py --junitxml=reports/audit_a_tests.xml` now reports **15 passed**; the latest `audit_a_tests.xml` describes this focused follow-up run.
