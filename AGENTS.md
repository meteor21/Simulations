# Midterm Sentiment Agents: working requirements

## Project and ownership

Audit and improve the existing Python implementation; do not replace it wholesale.
Python under `charisma_lab/` is authoritative. This checkout was recovered from the
user's uploaded v0.2 notebook because the selected GitHub repository was empty.
Use this existing checkout in each isolated cloud task; do not create a worktree
unless the user explicitly requests one. Preserve user changes. One integration
owner coordinates shared files. Up to three coding agents may audit identity and
provenance (A), acquisition and database safety (B), and analysis and validation (C).

## Research invariants

- Build candidate-level media portrayal for House/Senate midterms, starting with
  2026 and supporting historical research from 1990 onward. Preserve unsuccessful
  candidates, registrations, primary/general/special membership, and documented
  service intervals as different facts; an officeholder list is not a full roster.
- Keep national, state, metro and local coverage distinguishable. State routing is
  not proof of district readership. Respect exclusive service end dates.
- Retain political-orientation provider, genre, native scale, evidence, availability
  and applicability dates. Unknown stays unknown. Partisanship has no weight penalty.
  Do not backfill current ratings into earlier decades.
- Media portrayal is not representative public opinion. Survey favorability stays
  separate. Missing values never become neutral scores. Do not invent candidates,
  reviews, source ratings, historical data, or successful validation results.
- No post-cutoff publications/evidence in strict features. Explicit retrospective
  reconstruction is separately labeled; it is not an ex-ante forecast. Model vintage,
  modern-model historical knowledge, human labels and electoral accuracy need real
  validation beyond synthetic unit tests.
- Do not buy services, evade access controls/robots/terms, expose credentials, or
  overwrite original election/funding databases. Read source databases read-only;
  use a dedicated local sentiment DB and lineage-checked checkpoints.
- The current live pilot targets exactly 24 distinct sourced congressional IDs.
  It allows at most 20 total HTTP attempts including retries, source lookups and FEC
  acquisition. Reuse its persistent database/ledger on resume; never reset the
  budget, create fresh clients to evade it, or launch an unlimited crawl.
- Run live collection only with credentials and destination permissions available.
  Check credential presence, never print values. The Media Cloud binding is
  `MEDIACLOUD_API_KEY` for `search.mediacloud.org`; optional official FEC download
  needs `www.fec.gov`. Full text, RSS, models and historical crawling remain opt-in.

## Setup and verified commands

Run from `/workspace/Simulations` (or the root of an equivalent restored checkout).
Use Python 3.12 and an isolated environment. In this cloud instance it is
`/workspace/.venvs/midterm-sentiment`; reproducible installation is:

```bash
python3 -m venv /workspace/.venvs/midterm-sentiment
/workspace/.venvs/midterm-sentiment/bin/python -m pip install -r requirements-dev.lock -e '.[dev]'
/workspace/.venvs/midterm-sentiment/bin/python -m pip check
/workspace/.venvs/midterm-sentiment/bin/python -m pytest --junitxml=reports/test_results.xml
/workspace/.venvs/midterm-sentiment/bin/python examples/agents_demo.py
/workspace/.venvs/midterm-sentiment/bin/python examples/offline_demo.py --out /tmp/midterm-offline-demo
/workspace/.venvs/midterm-sentiment/bin/python scripts/sync_notebook.py --check
/workspace/.venvs/midterm-sentiment/bin/python scripts/validate_notebook.py
```

Read `reports/VALIDATION.md` for the actual latest results and limitations rather
than assuming earlier tests pass. Notebook validation runs all default code
cells in a fresh kernel with network-denial guards; it does not validate Colab
Drive mounting, real provider compatibility, or downloaded neural inference.
After Python/data/documentation changes, run `python scripts/sync_notebook.py`
then `--check` and re-execute the offline notebook. Do not edit the embedded base64
payload manually. Its content hash and module-location guard prevent stale reuse.

## Pilot procedure and current blocker

```bash
# Offline plan/preflight; exit 2 is intentional when a sourced roster is absent.
/workspace/.venvs/midterm-sentiment/bin/python -m charisma_lab.pilot --output /workspace/midterm-live-pilot
# After secure credential/destination configuration; FEC records are registrations.
/workspace/.venvs/midterm-sentiment/bin/python -m charisma_lab.pilot --output /workspace/midterm-live-pilot --run-network --download-fec
```

Use `--funding-db PATH` (read-only), `--fec-zip PATH`, or `--candidates PATH
--roster PATH` for existing sourced inputs; see `docs/PILOT.md`. Same pilot folder,
policy and roster are required on resume. A missing credential blocks even the
optional FEC request. Do not mark an empty roster or a zero-test run as validation.
Current audit has no real registry or Media Cloud key; real pilot data remain
uncollected. Header-only roster exports and explicit blockers are intentional.

## GitHub and Colab handoff

`.github/workflows/offline-analysis.yml` runs tests and synthetic analyses with
read-only permissions and no provider secrets. `python scripts/run_offline_analysis.py
--output artifacts` produces the same portable result bundle. Validate transfer
with `python scripts/validate_notebook.py --results-bundle artifacts/offline-analysis.zip
--report artifacts/notebook_bundle_import.json`. The final notebook cell imports
verified CSVs into `RESULTS_TABLES` without modifying a database. See
`docs/GITHUB_COLAB.md`. Never turn this ephemeral workflow into a new live-pilot
request allowance or label fixture exports as real candidate data.

For the user-authorized real GitHub pilot, `live-pilot.yml` uses an Actions secret,
serializes runs, and enables `--github-budget`. Every provider attempt first makes
a durable fast-forward reservation on `midterm-pilot-budget`. That branch stores
only quota metadata. Never reset/delete it to bypass 20 attempts; a new runner's
local database does not create a new allowance. Restore retained pilot artifacts
when possible. Partial outputs and missing annotations are not completed sentiment
analysis. Live Actions still needs the securely configured provider secret.

For workflow failures, inspect the first failing step before treating an `always()`
export error as the cause. Credential preflight uses only the standard library;
export requires successful installation and checks for outputs before importing
the package. Verify these failure paths with `python -m pytest tests/test_workflows.py`.
After updating workflow YAML, start a new run on latest `main`; rerunning an old
job keeps the old workflow revision. Do not copy the Actions secret to code or chat.

The user subsequently configured the repository Actions secret. A retry of run
`37558917645` passed credential presence and attempted FEC acquisition, but failed
with generic `ValueError` before selecting any candidates. The remote budget was
verified as 1/20 used; preserve that counter and remaining 19 attempts. This is not
evidence of a valid Media Cloud response or completed real sentiment analysis.
Inspect the structured `fec_error` in `pilot_report.json` on the next updated run;
do not guess that a download, redirect or parser failure means an empty electorate.

Latest run `37560296917` confirmed `download/redirect_not_permitted`, HTTP 302,
and 2/20 requests spent. FEC's immutable production proxy configuration at commit
`42a867c3c0fc6d86584f024f09ec990d725a022c` documents its exact government AWS
bucket; permit only that host and the requested `/bulk-downloads/YYYY/cnYY.zip`.
Do not allow arbitrary AWS hosts or switch providers to evade access restrictions.
HTTP 401/403 now stops source lookup and collection; diagnostics retain safe status.
The original 2026/as-of policy and durable request quota stay unchanged.

The user authorized real analysis on GitHub. When its dispatch API is blocked, an
explicit `.github/pilot-request.json` change on `main` can start this same bounded
workflow using the repository secret. Only edit that file to request an authorized
live run; ordinary pushes must not trigger collection. Manual dispatch remains
available. Never create a new quota through the request file. Keep summaries of
observed articles/annotations separate from a claim of validated sentiment.
