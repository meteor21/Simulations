# Simulations — Midterm Sentiment Agents · v0.2

**Audited implementation:** the original 116-test baseline was reproduced before edits.
Confirmed defects now have regression tests; see `reports/VALIDATION.md` and
`reports/AUDIT.md` for current commands, results and remaining limitations.
Python files are the source of truth; regenerate/check Colab with
`python scripts/sync_notebook.py` / `--check`. See `AGENTS.md` for setup and
`docs/PILOT.md` for the persistent 24-candidate, 20-total-request pilot.

## Three cooperating workers for US House/Senate research, 1990 onward
Built for Mete's election simulator. The default target is the 2026 midterms. This package extends, rather than overwrites, Charisma Lab v0.1. Build date: October 6, 2026.

**What has been delivered:** executable Python, a self-contained Colab notebook, a real 63-profile source directory, six sourced current political-orientation ratings, documented input contracts, synthetic integration tests and resumable workers.

**What has not been delivered:** a populated nationwide candidate-news corpus or completed historical charisma scores. The original release reported failed live HTTP requests. The current audit made zero live data-provider requests because the Media Cloud credential and a sourced candidate registry are missing. API contracts were inspected in primary documentation; network responses and local neural inference were tested with fixtures, not live production requests. Surveys and historical archive texts require real data and permissions.

## Start in Colab
Upload `Midterm_Sentiment_Agents_Colab.ipynb`. Its first cell extracts the embedded package. No separate repository or code pasting is necessary. Defaults run without API credentials, using a clearly separated synthetic demonstration, and create the working source tables.

To collect a pilot: set `RUN_NETWORK=True`; set `DOWNLOAD_FEC_IF_MISSING=True` when your existing election/funding database is not available. Supply `MEDIACLOUD_API_KEY` through Colab Secrets or the hidden prompt. The collection cell first resolves relevant source IDs, then plans and runs a bounded batch. Rerun that cell to resume within the same persistent 20-request ceiling; reruns do not reset it. Source-directory requests count against the same request budget, so initial runs may resolve sources without collecting many stories. Full-text retrieval and local model download are separate explicit switches.

The main switches are `RUN_NETWORK`, `RUN_NLP`, `FETCH_FULL_TEXT`, `DOWNLOAD_OFFICEHOLDERS`, and `RUN_HISTORICAL_COLLECTION`. Never raise all limits before inspecting pilot coverage and identity matches. No task keeps running after the notebook process ends.

## The three agents
| Worker | Responsibilities | Persistent outputs |
|---|---|---|
| SourceAgent | Import FEC or existing candidate registry; link biographical identities; service terms; reviewed source geography; provider IDs; rating provenance and dates | Candidate/cycle registry, source profiles, source directory metadata, service history, political-orientation assessments |
| CollectionAgent | Candidate-name batches; month windows; national versus state-routed sources; API pagination; bounded requests/retries; permitted full text; optional RSS; archive imports | Resumable jobs, versioned URLs, candidate/article links, search-coverage audit |
| AnalysisAgent | Candidate-specific portrayal; ambiguity review; source-level political-orientation proposals from an independent corpus; decay; scope/issue/ideology splits; service-period history | Review queue, snapshots, monthly features, coverage flags, standing-index bridge |

The coordinator runs cooperating phases with one SQLite writer. This is a job-based agent workflow, not a collection of independent language models secretly launched in the background. It does not purchase API access or make paid LLM calls implicitly.

## Who is included
Congressional collection accepts H and S, not presidential registrations. Candidates come from your `federal_candidate_cycle` table, official FEC candidate master ZIPs, or explicit reviewed input files. FEC records are registrations, not certified ballot membership. A separate dated `roster.csv` can restrict the cohort to an actual contest. Incumbents' service histories do not supply unsuccessful candidates; preserve both sources.

Default pilot: up to 24 candidate-cycle/office/state/district records from 2026, deterministically interleaved across state/office/party strata. It is a machinery test, not a statistically representative sample or final roster. Set `MAX_CANDIDATES=None` only after reviewing the exported cohort and plan size. Historical FEC downloading supports selected even cycles from 1990 onward. Your prior finance database begins later; the code does not invent the earlier records.

## Source geography and political tendencies
The seed has 12 national profiles, 50 state-focused profiles (one per state) and one metro profile. The 50-state seed comes from States Newsroom's network/partner directory, which is **not** a claim of independent or ideologically balanced outlets. One state source does not represent every House district or reader. Metro/local editions and additional publishers can be added with evidence. Headquarters state is not audience geography.

Six AllSides category snapshots are included with attribution, observation date and source links. Most outlets deliberately remain unrated. Display indices are Left=-2, Lean Left=-1, Center=0, Lean Right=1, Right=2. This is an ordinal project display, not AllSides' native numerical scale, not factual reliability, and not a quantitative left-right distance. Unknown stays NULL. Different providers and news/opinion genres remain distinct. Current labels are never applied to historical article dates before the rating's documented applicability.

For unrated sources, the optional model can propose a rating only from an independent, permitted, source-level political-coverage sample. It rejects candidate-search samples as a general bias sample. Proposals are unvalidated and cannot automatically become approved ratings. Human review is required. Partisanship itself carries **no sentiment-weight penalty**.

## What the sentiment score measures
These are **media-portrayal features, not representative public opinion**. Poll-based favorability remains a separate input. Social posts, campaign releases and official statements are separate channels, not pooled as independent voter opinion or journalism.

Each candidate's text is matched using documented full-name aliases and contextual heuristics. The local baseline masks verified full-name aliases (ambiguous surnames remain unresolved), classifies favorable/unfavorable/neutral-or-mixed portrayal and records evidence, model revision and quote flags. Masking does not remove all historical knowledge or prove absence of hindsight bias. Quote attribution, sarcasm, identity matching and ideology proposals require validation. Headlines-only and body-excerpt outputs are labeled separately. Keyword issue tags are co-occurrence proxies, not issue-specific causal sentiment measurements.

Within each observed outlet, article weights decay as `2 ** (-age_days / 90)`. Outlet means then receive equal weight. National and state-relevant subnational scores remain separate; their provisional 50/50 combination is the recency input when both pass coverage requirements. This 50/50 local/national split is a new configurable design assumption, separate from the existing equal-thirds standing index.

Primary defaults require at least two observed outlets and three distinct text hashes per scope, plus recent coverage. Sparse descriptive scores are preserved as diagnostics; missing primary inputs are not filled with neutral 50. The one-source state seed often will NOT pass the local gate until additional sources are added. Duplicates within an outlet are collapsed; cross-outlet syndication has explicit redundancy diagnostics. Similar-but-not-identical stories are not fully deduplicated.

The bridge computes `(favorability + media_recency + pedigree) / 3` only when all components are available. It never treats the result as a win probability. Population/geography and contest membership must be explicit. The unvalidated research index is not forecast-ready.

## Historical collection and in-office analysis
`CollectionAgent.plan_service` intersects requested dates with documented service intervals, including exclusive term ends. `AnalysisAgent.monthly_history` produces month-end features from 1990 onward with service-period indicators. General-election candidates, primary candidates and officeholders remain distinct concepts. Scheduled future service ends and retrospectively downloaded identities require auditing.

A modern online-news API is not a complete 1990s archive. Media Cloud coverage starts when it began collecting a source and does not deliver article bodies. GDELT DOC is a recent-discovery adapter, not a 1990s text archive. Older years need source-specific archives or permitted exports from licensed databases. The included JSONL importer uses one documented neutral contract; it is not an untested claim to parse every vendor's export format. No paywall or subscription bypass is implemented.

Two temporal modes exist. `strict` requires evidence/version and annotation availability by the cutoff, dated source applicability and candidate availability. `retrospective` can use later-retrieved versions for reconstruction and marks them as such. It still forbids future-published articles and current ideology labels outside their valid periods. Strict mode is a necessary safeguard, not proof of an unbiased backtest: sample selection, model training/revision, source survival, identity changes and missing archives need separate audits. Never mix modes silently.

## Persistence and outputs
The Colab notebook works in a local SQLite file and checkpoints with SQLite's backup API to:
`MyDrive/ElectionSimulator/database/Midterm_Sentiment_Agents.sqlite`.
Original election/funding databases are read only. Do not run competing writers on the same Drive copy.

Outputs include `selected_congressional_cohort.csv`, `source_profiles.csv`, `source_bias_assessments.csv`, `source_coverage.csv`, `observed_source_year_coverage.csv`, `candidate_sentiment_summary.csv`, full nested snapshots in JSONL, `annotation_review.json`, queue statuses and plan audit. Observed source/year counts measure what was retrieved, not the denominator of all published articles. Full article bodies are excluded from routine exports; review excerpts may still be copyrighted and should remain private.

## Local execution
```bash
python -m pip install -r requirements-dev.lock -e '.[dev]'
python -m pytest
python examples/agents_demo.py
```
For optional text extraction install `.[scrape]`; for the local classifier use `.[nlp]`. Live compatibility is still unvalidated in this audit. The model revision is stored when the model is loaded. Retain/pin that revision for reproducibility.

## Research validation before scaling
Review candidate identity matches, a stratified set of target portrayals (time, office, outlet, geography and party), quoted claims and opinion articles. Evaluate against human labels and later election cycles rather than random rows. Assess results separately for well-covered and under-covered candidates; do not select historical cohorts by who later won or became famous. Add independent local sources before treating the local score as stable. No electoral accuracy or causal influence result is claimed by this package.

See `docs/DATA_CONTRACTS.md`, `docs/HISTORICAL_RESEARCH.md`, `docs/SOURCES.md`, `data/README.md` and `reports/VALIDATION.md`.

## GitHub and Colab handoff

GitHub Actions runs the tests and existing offline analyses on pushes to `main`.
Download its results artifact and import it with the final Colab notebook cell.
See [the GitHub → Colab procedure](docs/GITHUB_COLAB.md). Initial results are
synthetic; real collection remains gated by the provider key and sourced roster.

A separate manual **Real 24-candidate pilot** GitHub workflow uses the secure
`MEDIACLOUD_API_KEY` Actions secret and a durable cross-run request counter.
It exports real collection results while keeping absent sentiment labels missing.
See `docs/GITHUB_COLAB.md` for run and storage details.
