# Midterm Sentiment Agents v0.2 — reproduced and corrected validation

Initial audit: October 6, 2026; acquisition/checkpoint follow-up: October 7, 2026.
The supplied report is retained verbatim as `VALIDATION.original.md`.
No earlier pass claim was accepted without rerunning its checks.

## Current evidence

| Check | Actual result | Evidence |
|---|---|---|
| Original recovered Python package | 116 passed, 0 failed, 0 skipped | `baseline_tests.xml`, `baseline_tests.log` |
| Original offline notebook defaults | 13 code cells / 25 total, all executed in order in a shared Python namespace | `baseline_notebook.json` |
| Corrected integrated suite | **265 passed, 0 failed, 0 errors, 0 skipped** | `test_results.xml`, `test_results.log` |
| Three-worker synthetic demonstration | Both invented candidates: national 80, local 20, media recency 50, in-office true | `agents_demo.json` |
| Legacy synthetic offline demonstration | SYN-A standing 76.889029 → 51.081959; SYN-B stays missing | `offline_demo.log` |
| Corrected notebook defaults | **14/14 code cells**, fresh Jupyter kernel, no errors, zero network attempts | `notebook_execution.json`, `notebook_validation.log` |
| Embedded package consistency | Every selected source file matches the regenerated payload | `python scripts/sync_notebook.py --check` |
| Dependency consistency | No broken requirements | `pip_check.log`; exact versions in `dependency_versions.json` and `../requirements-dev.lock` |
| Real source directory | 63 profiles: 12 national, 50 state-focused, 1 metro; 50 state codes | Existing executed source-seed tests |
| Source ratings | 6 attributed, dated snapshots; unknown/current-vs-historical distinctions retained | Executed seed and provenance tests |
| Pilot preflight | Exit 2 with explicit missing registry; 0 selected real candidates, **0 HTTP attempts** | `pilot_preflight.log`, `pilot/pilot_report.json` |
| Bounded real FEC/Media Cloud collection | 24 registrations, 3 unique news URLs, 0 annotations; blocked/partial completeness; **16/20 cumulative attempts** | [Run 37680664034](https://github.com/meteor21/Simulations/actions/runs/37680664034), Git budget branch |
| Publisher scrape, downloaded neural inference, Colab Drive | **Not run / not validated** | Optional scope; reviewed labels remain missing |

The new total includes 149 added regression cases. Existing assertions were not
silently disabled: the old expectation permitting writes into unrelated databases
was corrected to require refusal, and the old blanket-surname masking assertion
was corrected to preserve a rival's identity. Synthetic annotation helpers now
provide explicitly fictional, dated annotation evidence for strict-cutoff tests.
An original-database copy also exposed duplicate source observations after reimport;
exact-value reuse now keeps its 63 profiles/6 ratings unchanged. An integration
regression verifies unsupported agents schema versions are rejected before mutation.
A/C pre-fix regression runs demonstrate failures against the unmodified package;
see the linked audit reports and their machine-readable evidence.

## Actual commands

From `/workspace/Simulations`, Python 3.12.14 in
`/workspace/.venvs/midterm-sentiment`:

```bash
python3 -m venv /workspace/.venvs/midterm-sentiment
/workspace/.venvs/midterm-sentiment/bin/python -m pip install -e '.[dev]' ipykernel
# Initial install used to reproduce the original package baseline.
/workspace/.venvs/midterm-sentiment/bin/python -m pytest --junitxml=reports/baseline_tests.xml
/workspace/.venvs/midterm-sentiment/bin/python examples/agents_demo.py

# Final repeatable setup pins the tested dependency environment.
bash scripts/cloud_setup.sh
/workspace/.venvs/midterm-sentiment/bin/python -m pip check
/workspace/.venvs/midterm-sentiment/bin/python -m pytest --junitxml=reports/test_results.xml
/workspace/.venvs/midterm-sentiment/bin/python examples/agents_demo.py
/workspace/.venvs/midterm-sentiment/bin/python examples/offline_demo.py --out /tmp/midterm-offline-demo
/workspace/.venvs/midterm-sentiment/bin/python scripts/sync_notebook.py
/workspace/.venvs/midterm-sentiment/bin/python scripts/sync_notebook.py --check
/workspace/.venvs/midterm-sentiment/bin/python scripts/validate_notebook.py
/workspace/.venvs/midterm-sentiment/bin/python -m charisma_lab.pilot --output /workspace/midterm-live-pilot
# Last command deliberately exits 2: no sourced candidate registry is present.
```

Command output was redirected into the listed logs with the original exit status
preserved. `setup_repeatability.log` records re-running the saved setup script.
The original notebook was executed without changing any default code cells; the
corrected notebook was additionally tested with HTTP/socket-denial guards. Neither
check exercises Colab-specific storage mounting or a production search response.

## Initial pilot blockers and setup history

At the initial audit no `MEDIACLOUD_API_KEY` was present in the actual process, and the initial environment
configuration declared no credential bindings. There is no real candidate registry,
FEC ZIP, funding database or sourced 24-candidate roster among the uploaded files.
The uploaded CSV is a source catalog, not a candidate roster; it exactly matches
the embedded source-profile seed. Both real roster exports are therefore header-only.
Synthetic fixture people have not been substituted for real candidates.

The initial restricted network policy did not list `search.mediacloud.org` or
`www.fec.gov`. A saved environment draft adds these destinations, the missing secure
Media Cloud credential requirement, the tested `install_script`, and `start_skill`.
This save does not apply runtime changes, provide a credential, or publish a snapshot.
Review/save the draft in environment settings, supply the credential securely,
and publish the prepared environment. Then rerun the bounded pilot command in
`docs/PILOT.md`, or supply existing sourced input files. FEC discovery is permitted
only with the live prerequisites and counts toward the same 20-request allowance.

A synthetic 24-person pilot regression tested selection and exports, and transport
fixtures prove retries plus restarts cannot exceed the durable ceiling. Those are
software tests, **not** live pilot evidence. Subsequent real collection is recorded
below separately. No access denial
was bypassed and no paid service was purchased.

## Research limitations

Media portrayal is not survey favorability or public opinion. Sentiment accuracy,
identity disambiguation accuracy, provider schema compatibility, archive coverage,
and electoral predictive value remain unvalidated on real data. One state source
per state is neither independent local coverage nor a sufficient default local panel.
No political-orientation penalty is applied. Most sources remain unrated.

Strict features now gate article versions, candidate identity, dated source/rating
facts, service evidence **and annotation availability**. Post-cutoff publications
remain excluded even in retrospective mode. Modern model knowledge/training
vintage is not certified historically valid. Same-model annotation replacement can
remove earlier evidence rather than reconstruct an append-only history; a later
replacement cannot enter a strict earlier snapshot. Roster and alias tables are not
complete versioned evidence ledgers; freeze sourced historical input snapshots.
Exact hashes do not solve paraphrased syndication, OCR variation, or correlated
outlet ownership. See `AUDIT.md`, `AUDIT_A.md`, `AUDIT_B.md`, `AUDIT_C.md`, and
`AUDIT_C_ANNOTATION_CUTOFF.md` for confirmed fixes and remaining limits.

The current isolated environment and offline workflow are validated. Publication
and restoration into a new task have not been tested or claimed.

## GitHub-to-Colab handoff follow-up

Five additional transfer tests cover permitted exports, preservation of missing
values, GitHub artifact ZIP wrappers, checksum failures, unsafe archive paths, and
rejection of fixture files labeled real. The notebook now has 14 code cells
(including results import) and 27 total cells. Both default execution and actual
bundle import were validated in a fresh local kernel. `GITHUB_HANDOFF.md` records
current commands/results; earlier audit evidence is preserved in `*.pre_github.*`.

## Failed live Actions run and workflow correction

Public run `37558917645` at commit `5e0940a` failed in credential preflight;
dependency installation and live collection were skipped. Its unconditional export
then imported `charisma_lab`, whose scoring import requires NumPy. This produced
the screenshot's secondary `ModuleNotFoundError`, not a missing dependency in the
project manifest. No provider collection was reached in that run. A later user
screenshot shows the correctly named repository Actions secret now exists;
credential validity and real provider responses still require a new live run.

The export now requires successful installation, checks for output directories
before importing the package, and still exports partial tables after collection
failure. Empty/whitespace credentials produce an explicit GitHub error annotation
with the secure repository settings link, without printing the value. Official
`checkout`, `setup-python` and `upload-artifact` v6 releases were checked against
their repositories and `action.yml` files: all use Node.js 24. Both workflows pin
`ubuntu-24.04` and support replacing artifacts on a job rerun. The durable pilot
budget and collection limit are unchanged.

Actual verification from the isolated environment:

```bash
/workspace/.venvs/midterm-sentiment/bin/python -m pytest tests/test_workflows.py
# Before the fix: 3 failed, 2 passed; reproduces the exact NumPy traceback.
# After the fix: 5 passed, including dependency-free export/preflight execution,
# partial-results transfer preserving missingness, and no credential echo.
/workspace/.venvs/midterm-sentiment/bin/python -m pytest --junitxml=reports/test_results.xml
# Final integrated workflow/FEC correction: 217 passed, 0 failed/skipped.
/workspace/.venvs/midterm-sentiment/bin/python -m pip check
# No broken requirements found.
```

Workflow YAML is included in the regenerated embedded package so its regression
tests also have their inputs in a notebook extraction. Start a new manual workflow
on latest `main`; **Re-run jobs** keeps the old workflow revision. This correction
does not claim that the live pilot or real sentiment analysis has succeeded.

A subsequent retry of the same public run (job `112592603916`) passed credential
presence and reached collection. The user-provided log reports `FEC acquisition
failed: ValueError`, zero selected candidates, one sent HTTP attempt and one remote
reservation. A read-only fetch of `midterm-pilot-budget` confirmed `used=1` with
the original 20-request limit and policy. No additional FEC or Media Cloud requests
were made from this cloud checkout. The older report omitted response status and
parser stage, so the actual remote FEC failure cause cannot be established from it.
This is a new acquisition blocker, distinct from the original skipped-install
export bug. The supplied key's presence is established; API validity is not.

Offline regression fixtures confirmed two FEC implementation defects: a normal
same-domain HTTPS redirect was refused instead of following a separately counted
hop, and a malformed later row left previously imported identities committed.
The importer now commits the entire ZIP atomically, preserves prior identity
metadata, and reads quotes as literal pipe-delimited field data. Downloads follow
at most three redirects within the official HTTPS FEC domain, using the same client
and durable request allowance; unfamiliar hosts and unsafe locations stay blocked.
Only a successfully parsed ZIP becomes a cache entry. Safe structured diagnostics
identify download, archive and parser failures without raw response text, candidate
addresses, credential values or exception details. These fixtures establish the
software fixes; they do not establish which defect caused the uninstrumented live
failure or that the official endpoint will succeed on the next run.

The FEC regression file adds 16 cases, plus one pilot-report integration case.
Together with the five workflow cases this follow-up adds 22 regressions to the
previous 195-test suite. The final suite executed 217 tests successfully. Default
notebook execution and actual bundle import each executed all 14 code cells with
zero errors and network attempts after regeneration; the bundle import report is
`artifacts/notebook_bundle_import.json`. The original live report remains a failed
acquisition attempt, not a completed real-data validation.

## Verified FEC production redirect — October 7 follow-up

Run `37560296917` on `5ce0903` failed after installation succeeded. The supplied
log identifies `download/redirect_not_permitted`, HTTP 302, zero selected candidates,
and two cumulative provider attempts. Read-only Git budget inspection confirmed
`used=2`. This establishes a redirect allowlist failure; the prior same-domain
exception did not cover FEC's production download host.

FEC's [production manifest](https://github.com/fecgov/fec-proxy/blob/42a867c3c0fc6d86584f024f09ec990d725a022c/manifest_prod.yml#L23)
and [rewrite rule](https://github.com/fecgov/fec-proxy/blob/42a867c3c0fc6d86584f024f09ec990d725a022c/nginx.conf#L70-L71)
name the exact government AWS bucket and `/bulk-downloads/` object path. The downloader
now permits that exact host only for the requested cycle's candidate ZIP. HTTPS,
TLS verification, no credentials/query/fragment, the hop limit, and a separate
durable reservation per request remain enforced. Spoofed buckets, other years,
other files and unsafe locations are rejected before the second request.

HTTP denial exceptions retain safe numeric status. Media Cloud source lookup
stops after 401/403; candidate collection cannot start after that denial. No
response bodies or exception text enter those diagnostics. GitHub annotations
publish the sanitized FEC failure and selected-candidate/article/annotation counts.

The user already authorized real analysis on GitHub. The workflow additionally
accepts an explicit `.github/pilot-request.json` change on `main` when the dispatch
API is unavailable. Its standard-library preflight requires the existing
24-candidate/20-request policy. Ordinary code pushes do not start collection, and
the marker neither resets nor expands the durable quota. The first marker is
committed separately after code validation to start the authorized bounded run.

Actual commands/results before starting that run:

```bash
/workspace/.venvs/midterm-sentiment/bin/python -m pytest tests/test_fec_acquisition.py tests/test_pilot.py tests/test_workflows.py
# 58 passed: includes 13 new CDN/source cases and 9 control/diagnostic cases.
/workspace/.venvs/midterm-sentiment/bin/python -m pytest --junitxml=reports/test_results.xml
# 239 passed; original exit status retained with output in test_results.log.
/workspace/.venvs/midterm-sentiment/bin/python scripts/sync_notebook.py
/workspace/.venvs/midterm-sentiment/bin/python scripts/sync_notebook.py --check
/workspace/.venvs/midterm-sentiment/bin/python scripts/validate_notebook.py
```

Read-only upstream software checks also confirm Media Cloud's source-directory
domain lookup, authentication, pagination and story fields. Its
[source filter](https://github.com/mediacloud/web-search/blob/b1db72f07b8a3dc0c334bbfa7324d560fc032967/mcweb/backend/sources/api.py#L415-L445)
searches names, labels and alternative domains. The search adapter sends an ignored
`platform` parameter where GET expects `p`; the current default selects the same
Media Cloud provider, so it is not the cause of this failure. These software-source
checks made no FEC or Media Cloud data-provider requests and do not validate the
user's provider account or real sentiment accuracy. Real run outcomes must be
reported separately from these passing offline checks.

## Actual real collection and retained-checkpoint analysis

After the corrected source passed [GitHub offline CI 37680428871](https://github.com/meteor21/Simulations/actions/runs/37680428871),
the separate request commit `8041f94b9ac8b803e228c86d3f89b2461c479215`
started the already authorized live pilot. [Run 37680664034](https://github.com/meteor21/Simulations/actions/runs/37680664034)
imported FEC records, selected **24 actual congressional registrations**, and saved
**3 unique news URLs**. Its result notice reports zero candidate annotations and
blocked completeness. Four requests remain: a read-only Git fetch confirmed 16
durable reservations, including the two earlier failed acquisition attempts.
The cutoff remains October 6, 2026; discovery is retrospective, and registrations
are not promoted to verified contestants. No sentiment accuracy claim follows from
these news metadata counts.

The cloud proxy denies the GitHub REST API, so it cannot fetch private artifact
reports or dispatch jobs here. The read-only `pilot-analysis.yml` workflow instead
uses GitHub's own injected token to retrieve both artifacts from that exact run,
recompute existing features with **zero provider calls**, export real tables, and
execute the Colab import cell. It preserves the original collection report and
both code revisions in `analysis_report.json`. No Media Cloud secret is bound to
this analysis workflow. Missing/expired artifacts fail without a new crawl fallback.
The new `--analyze-existing` mode requires the saved database, original ledger and
unchanged policy; it cannot download or import new inputs. Zero reviewed annotations
produce missing scores and an explicit `analyzed_partial` result.

Actual local verification:

```bash
/workspace/.venvs/midterm-sentiment/bin/python -m pytest --junitxml=reports/test_results.xml > reports/test_results.log 2>&1
# 265 passed in 2.75s; no failures/errors/skips.
/workspace/.venvs/midterm-sentiment/bin/python scripts/sync_notebook.py
/workspace/.venvs/midterm-sentiment/bin/python scripts/sync_notebook.py --check
/workspace/.venvs/midterm-sentiment/bin/python scripts/validate_notebook.py
/workspace/.venvs/midterm-sentiment/bin/python scripts/run_offline_analysis.py --output artifacts
/workspace/.venvs/midterm-sentiment/bin/python scripts/validate_notebook.py --results-bundle artifacts/offline-analysis.zip --report artifacts/notebook_bundle_import.json
```

Six new checkpoint-mode tests and twenty retained-artifact tests use explicitly
synthetic fixtures. They enforce zero HTTP calls, unchanged counters, required
ledger/policy, original-run matching, bounded sizes, symlink rejection, refusal to
overwrite existing databases/bundles, missing artifact failure, preservation of
original blockers and separate collection/analysis code provenance. They do not
substitute for analysis of the real retained run. Its verified outcome is recorded
separately in `LIVE_PILOT_RUN.md` when the GitHub job completes.
