# Verified real pilot and GitHub-to-Colab handoff — October 7, 2026

The FEC redirect failure was fixed by permitting only its documented government
AWS bucket and exact candidate-master object. The original request allowance was
preserved, including the two failed acquisition attempts.

| Evidence | Actual result |
|---|---|
| [Collection 37680664034](https://github.com/meteor21/Simulations/actions/runs/37680664034) | 24 actual FEC congressional registrations, 3 unique news URLs, 0 candidate annotations |
| Collection completion | 6 processed searches, 3 hits, 0 blocked jobs, 0 errors; all 6 jobs marked done |
| Original sole blocker | Incomplete source panel; three state outlets were not found in the provider directory |
| [Saved analysis 37683585456](https://github.com/meteor21/Simulations/actions/runs/37683585456) | **Success**, 41 seconds; `analyzed_partial`; zero new provider requests |
| Real notebook import | **Passed**, all 14 code cells; network denied by validation guards |
| [Offline CI 37683584925](https://github.com/meteor21/Simulations/actions/runs/37683584925) | **Success**, 45 seconds; 265 tests at that revision |
| Current local regression suite | **267 passed**, after two additional partial-completion status tests |
| Durable quota | 16/20 used, 4 remaining; never reset or expanded |

The real collection used code/request revision `8041f94b9ac8b803e228c86d3f89b2461c479215`.
The saved analysis used revision `663a6c6`. The full original report and distinct
collection/analysis code provenance are in its `analysis_report.json` artifact.
Public job notices are preserved as machine-readable evidence in `live_pilot_result.json`.
The local cloud proxy denies GitHub REST API access; no local download of these
real artifacts is claimed. GitHub's analysis job retrieved the retained artifacts
using its own read-only token and verified their actual Colab import.

Media Cloud matched `apnews.com` (106145), `cnn.com` (1095) and `foxnews.com` (1092).
It returned no directory match for `alaskabeacon.com`, `alabamareflector.com`, or
`arkansasadvocate.com`. These failed lookups remain unknown source coverage, not
neutral sentiment or evidence that the outlets published nothing. The bounded run
did not search every seed source or establish balanced national/local coverage.

The cohort is **registration discovery**, not a verified 2026 ballot roster. All
24 source IDs were exported, with their other observed contest memberships retained.
The collection cutoff remains October 6, 2026, with explicitly retrospective
reconstruction. There are no reviewed candidate-specific labels; every unsupported
score remains missing. Media portrayal is not survey favorability or public opinion.
This tiny metadata pilot does not establish sentiment accuracy or forecasting value.

The former fatal status for an incomplete source panel after otherwise successful
searches is now `executed_partial` with warnings. Actual collection errors, access
denial, acquisition failure, invalid policy and exhausted quota still block. No
live requests were spent testing that status correction.

## Reproduce saved-data analysis

Use **Actions → Analyze saved real pilot**, with `source_run_id=37680664034`, while
its two original artifacts remain available. On a GitHub runner after locked setup:

```bash
python scripts/analyze_github_pilot.py --source-run-id 37680664034 --output artifacts/analyzed-pilot --bundle artifacts/real-analysis.zip
python scripts/validate_notebook.py --results-bundle artifacts/real-analysis.zip --report artifacts/real_notebook_import.json
```

This workflow has no Media Cloud secret, cannot resume collection, refuses existing
output databases/bundles and cannot create a fresh request allowance. Missing or
expired original artifacts fail explicitly; there is no crawl fallback.

Download the **midterm-real-analysis-37683585456** artifact from the successful
analysis run. Open the [Colab notebook](https://colab.research.google.com/github/meteor21/Simulations/blob/main/notebooks/Midterm_Sentiment_Agents_Colab.ipynb),
keep network/NLP disabled, run its cells and set `UPLOAD_RESULTS_BUNDLE=True` in the
last cell. Upload the artifact ZIP or its inner `real-analysis.zip`.

The cell verifies checksums and populates:

```python
RESULTS_TABLES['pilot/selected_congressional_cohort.csv']
RESULTS_TABLES['agents/candidate_sentiment_summary.csv']
```

GitHub retains the small result artifact for 30 days. Preserve a personal copy
before expiry. Raw SQLite and news bodies are excluded from the Colab bundle and
Git history; the collection checkpoint remains a separate Actions artifact.
