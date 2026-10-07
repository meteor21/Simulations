# GitHub and Colab handoff validation

The user requested code on GitHub, real analysis on GitHub Actions, and exported
results usable in Colab. Two workflows are prepared:

- `offline-analysis.yml`: automatic on main pushes/PRs, tests plus existing synthetic
  analyses and a Colab result bundle; no provider secret or live data collection.
- `live-pilot.yml`: manual 24-candidate real-data pilot using the secure
  `MEDIACLOUD_API_KEY` Actions binding. It reserves every provider attempt on the
  small separate `midterm-pilot-budget` branch before sending, preserving the
  20-attempt limit across fresh runners. State/results stay in bounded-retention
  artifacts; no dataset or credential is committed to Git.

## Actual local checks

From `/workspace/Simulations`, using `/workspace/.venvs/midterm-sentiment/bin/python`:

```bash
python -m pytest --junitxml=artifacts/test_results.xml
# 195 passed, 0 failed/errors/skipped.
python scripts/run_offline_analysis.py --output artifacts
# 2 synthetic agent summaries, 3 standing rows, 13 files in offline-analysis.zip.
python scripts/sync_notebook.py
python scripts/sync_notebook.py --check
python scripts/validate_notebook.py --report artifacts/notebook_execution.json
# 14/14 default code cells, 27 total cells, zero errors/network attempts.
python scripts/validate_notebook.py --results-bundle artifacts/offline-analysis.zip --report artifacts/notebook_bundle_import.json
# 14/14 cells; actual bundle loaded into RESULTS_TABLES; zero network attempts.
```

The Git-backed budget was tested with separate temporary Git checkouts and a local
bare remote: a new runner observes the prior spend, the ceiling cannot be increased
by changing policy, and an unavailable remote fails closed. These tests never used
the real repository's quota branch and consumed zero live provider requests.
Transfer tests verify checksum validation, safe member paths, GitHub artifact
wrappers, exclusion of databases/private reviews and preservation of missing values.

GitHub API inspection (`gh api repos/meteor21/Simulations`) returned Forbidden in
this cloud session; native `git ls-remote` succeeded. Thus API-dependent secret
installation, dispatch and remote run-status verification are not established here.
Pushing code does not prove an Actions job succeeded. Add the provider key securely
under the repository's Actions secrets and dispatch the real pilot through GitHub.
Any credential exposed in chat should be replaced; none was embedded in code,
configuration, reports or commands during this handoff.

Real collection and model accuracy remain unvalidated. The real workflow computes
only features supported by available reviewed annotations; newly collected stories
do not automatically become validated sentiment labels. Review output missingness,
source resolution, registry-vs-contest status and request counts. Colab's browser
file picker is a user-session step; the same import logic was validated locally.
