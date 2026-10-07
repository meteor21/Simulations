# GitHub analysis → Colab

Git stores code and its history. **GitHub Actions** runs the Python analyses.
**Colab** opens the notebook and imports exported results for further exploration.
The default demonstration is synthetic. The bounded real pilot has collected 24
FEC registrations and 3 news URLs, but no reviewed sentiment annotations. Real
sentiment scores therefore remain missing.

## 1. Keep the project on GitHub

Repository: `meteor21/Simulations`. The `main` branch holds Python source, tests,
source catalogs, audit documentation and the regenerated self-contained notebook.
Raw databases, `.env` files, local environments and generated `artifacts/` stay out
of Git. Do not commit news article bodies, private review excerpts or provider keys.

After Python, data or documentation changes:

```bash
python scripts/sync_notebook.py
python scripts/sync_notebook.py --check
python -m pytest
```

Commit the Python changes and regenerated notebook together. CI rejects a stale
embedded package. Dependency installation uses Python 3.12 and the tested lock file.

## 2. Run analyses on GitHub

Open the repository's **Actions → Offline tests and analysis**. A push to `main`
or a pull request runs it automatically; **Run workflow** also starts it manually.
It installs dependencies, runs tests, checks notebook consistency, executes the
notebook without network data access, runs both existing synthetic analyses and
uploads a results artifact. The job is capped at 15 minutes, uses read-only
repository permissions and has no provider secrets or live collection step.
It uses whatever Actions runner allowance is already available; this workflow does
not buy minutes or change a billing plan. If Actions are unavailable, use local commands.

Download the artifact named `midterm-offline-analysis-<commit>` from a successful
run. It includes `offline-analysis.zip` plus current-run validation evidence.
GitHub retains these artifacts for 14 days. Keep a copy in your own Drive if needed.

For a local equivalent:

```bash
python scripts/run_offline_analysis.py --output artifacts
python scripts/validate_notebook.py --results-bundle artifacts/offline-analysis.zip --report artifacts/notebook_bundle_import.json
```

The results ZIP contains CSV/JSON/JSONL exports and a checksum manifest with
`dataset_kind=synthetic` and the source commit. It excludes SQLite files and private
annotation-review exports. Checksums detect corruption; download only a trusted run.

## 3. Open in Colab and import

Open `notebooks/Midterm_Sentiment_Agents_Colab.ipynb` through Colab's GitHub tab,
or upload the notebook file. The direct link after publication is:

https://colab.research.google.com/github/meteor21/Simulations/blob/main/notebooks/Midterm_Sentiment_Agents_Colab.ipynb

For a private repository, sign into GitHub through Colab or download/upload the
self-contained notebook. No GitHub token needs to be embedded in notebook code.
Keep `RUN_NETWORK=False` and `RUN_NLP=False` for this offline results workflow.
Run the notebook and use its final **Import GitHub analysis results into Colab**
cell: set `UPLOAD_RESULTS_BUNDLE=True`, run that cell and select the downloaded
artifact ZIP (or inner `offline-analysis.zip`).

The cell displays the dataset kind and source commit and loads CSVs into
`RESULTS_TABLES`. Example:

```python
RESULTS_TABLES['agents/candidate_sentiment_summary.csv']
RESULTS_TABLES['standing/synthetic_scores.csv']
```

It reads and verifies the archive in memory; it does not extract arbitrary paths,
execute archive contents or overwrite an election database. The Colab browser
file picker and Drive integration need execution in your Colab session; local
validation exercises the same bundle reader/import cell in a fresh Jupyter kernel.

## 4. Real data and provider access

The current provider is **Media Cloud**: https://search.mediacloud.org/ . Follow
https://www.mediacloud.org/documentation/search-api-guide for API access and key
instructions. Store the key securely as `MEDIACLOUD_API_KEY` in the relevant runtime
(e.g. Colab Secrets). GitHub's offline workflow does not need it. Secrets configured
in Codex, Colab and GitHub are separate; they are not copied automatically.

The pilot in `PILOT.md` shares one persistent 20-request allowance across retries,
lookups and restarts. Run `37680664034` obtained the sourced 24-candidate registry
and saved real news metadata, using 16 of those requests cumulatively. Use the durable
GitHub budget described below; ephemeral runners must not restart that allowance.
Initial candidate membership from FEC is registration discovery, not a certified
ballot roster. Real sentiment also needs permitted texts/metadata and reviewed
candidate-specific annotations; a provider key alone does not create validated scores.

The same `charisma_lab.transfer.create_bundle` function can package selected real
exports with an explicit `dataset_kind='real'` and source commit. Keep synthetic
and real bundles distinct, preserve missingness and retain rights/provenance.

## Real pilot on GitHub Actions

The separate **Real 24-candidate pilot** workflow accepts a manual run or an explicit
Git run request. Add
`MEDIACLOUD_API_KEY` to repository **Settings → Secrets and variables → Actions**,
then open **Actions → Real 24-candidate pilot → Run workflow** on `main`.
The key is supplied to credential preflight and collection through the Actions secret binding.
Use a replacement for any key exposed in chat. Do not paste keys into workflow YAML.

If credential preflight fails, verify that the secret is under **Repository secrets**
with the exact name above; Variables, Colab Secrets and unbound environment secrets
do not supply this workflow. Start **Run workflow** on the latest `main` after a
workflow fix: **Re-run jobs** retains the original run's older workflow revision.
Export is skipped if dependency installation did not succeed, and checks for
available outputs before importing package dependencies. It still exports partial
tables if collection fails after installation. The workflows use Node.js 24 actions
on `ubuntu-24.04` to avoid the obsolete action-runtime and moving-runner warnings.

The job imports official FEC registrations when no sourced registry is present,
selects and exports 24 IDs, resolves sources and collects within the existing
20-request total. It computes the reviewed features actually supported by the data;
missing annotations/coverage remain missing. It does not silently manufacture real
sentiment values or run a paid model. Newly discovered headlines alone are not a
validated candidate-sentiment analysis; reviewed labels or an explicitly validated
annotation method are still needed. Partial collection can produce a failed job
with useful outputs; inspect `pilot_report.json` rather than treating failure as zero news.

For FEC failures, inspect `fec_error` in that report for the sanitized stage,
reason and HTTP status or parser row/field count when available. Normal HTTPS
redirects within the official FEC domain consume a separate reservation for each
hop. The exact government AWS bucket and requested candidate ZIP path documented
in FEC's official production proxy are also permitted; other destinations remain
blocked. Acquisition failure is not
proof of no candidates. A malformed import must not leave a partially committed
roster that a later run could mistake for a completed registry.

For an already authorized live run when the dispatch API is unavailable, commit a
new request ID to `.github/pilot-request.json` on `main`. Only changes to that path
trigger collection on a push; ordinary code/documentation commits do not. Its
format is `midterm-pilot-request-v1`, `candidates` is 24, and
`max_total_provider_requests` is 20. This records an explicit request, never a new
quota: all previously charged attempts remain consumed on `midterm-pilot-budget`.
Do not change this file without authorization to run the live pilot. There is no
scheduled collection. GitHub annotations show safe FEC errors and result counts;
HTTP 401/403 stops source resolution and collection before further denied requests.

GitHub runners are temporary, so the request counter is committed **before every
provider attempt** to the separate `midterm-pilot-budget` branch. That branch holds
only a small `budget.json` file: dates/policy and a counter, no API key or dataset.
Normal fast-forward pushes prevent concurrent updates from losing counts. Do not
force-push, delete or reset that branch to obtain more pilot requests. Jobs are
serialized. A reservation lost to a crash remains consumed conservatively.

The database checkpoint is an Actions artifact named `midterm-live-pilot-state`,
restored on the next run when available. It is never committed to Git. Expired or
missing checkpoints do not reset the remote budget. Results are a separate
`midterm-real-results-<run-id>` artifact containing `real-analysis.zip` and reports;
the Colab import cell accepts its wrapper or the inner ZIP. Artifacts are retained
for 30 days and need some GitHub storage; the workflow is not storage-free. Download
and keep needed results in your own storage before expiry. Colab can load only the
small exported tables, avoiding the collection work/database there.

This workflow requires Actions to have permission to write the budget branch and
read prior artifacts. If repository policy disallows the write, it fails closed
before the provider request. Checkpoints and artifact visibility follow repository
access rules; do not upload licensed article bodies or private reviews casually.

## Analyze saved real data without further provider calls

**Actions → Analyze saved real pilot** downloads the database checkpoint and original
results from one exact collection run. Supply `source_run_id=37680664034`. The job
recomputes available reviewed features offline, exports `real-analysis.zip`, and
executes the Colab import cell with those actual tables. It has no Media Cloud key
binding and makes zero provider requests. The original collection's blockers and
both code revisions remain in `analysis_report.json`; a successful offline analysis
does not mean the source panel or sentiment annotations are complete.

For authorized analysis when dispatch is unavailable, change
`.github/pilot-analysis-request.json` on `main` with
`format=midterm-pilot-analysis-request-v1` and the exact numeric `source_run_id`.
Changing this file never triggers the live-collection workflow.

Download `midterm-real-analysis-<analysis-run-id>` from the successful analysis run.
Import its ZIP, or the inner `real-analysis.zip`, using the notebook's last cell.
The roster is `RESULTS_TABLES['pilot/selected_congressional_cohort.csv']`; the
feature table is `RESULTS_TABLES['agents/candidate_sentiment_summary.csv']`.
Missing reviewed scores stay missing. The separate audit JSON explains partial
coverage and keeps registrations distinguishable from verified contestants.

To reproduce the retained-artifact analysis in an authorized GitHub runtime:

```bash
python scripts/analyze_github_pilot.py --source-run-id 37680664034 --output artifacts/analyzed-pilot --bundle artifacts/real-analysis.zip
python scripts/validate_notebook.py --results-bundle artifacts/real-analysis.zip --report artifacts/real_notebook_import.json
```

Artifacts expire after 30 days. This operation refuses existing output databases or
bundles and fails if either original artifact is missing; it cannot fall back to a
new crawl or a new request allowance.
