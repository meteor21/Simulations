# Real analysis visualizations on GitHub

**Publish real analysis dashboard** reruns the analysis from an existing retained
checkpoint and publishes three SVG charts plus a candidate table directly on the
repository's `analysis-dashboard` branch. The self-contained interactive HTML adds
candidate search, chamber/state/coverage filters, evidence details, and source
lookup/provenance views. It loads no third-party libraries or external data.

The analysis is fixed to the original September 1–October 6, 2026 collection window.
It makes **zero new provider requests**. The saved pilot has 24 FEC registrations,
3 news URLs and no reviewed candidate-specific labels. It is a partial metadata
pilot; sentiment scores remain missing. Future nonnull features must retain their
own cutoff/state/cycle/lookback evidence, separately from these metadata counts.

## Run and publish

In **Actions → Publish real analysis dashboard → Run workflow**, set
`source_run_id` to the original real collection run, currently `37680664034`.
Both its original results and database artifacts must still be retained. Missing
artifacts stop the job; it never substitutes synthetic data or launches a crawl.

When API dispatch is unavailable, an explicitly authorized update to
`.github/dashboard-request.json` on `main` starts the same workflow:

```json
{
  "format": "midterm-dashboard-request-v1",
  "source_run_id": "37680664034",
  "request_id": "a-new-explicit-publication-request"
}
```

The workflow installs locked dependencies, runs projection/publication tests,
reanalyzes the checkpoint, builds the visualizations, verifies the real page in
desktop and mobile Chromium, and executes the real Colab result import. It then
publishes to the separate `analysis-dashboard` branch using its GitHub token. Its
ownership marker protects unrelated existing branches; updates preserve history
and never force-push. Neither the live request file nor budget branch is modified.

Open [the rendered GitHub visual report](https://github.com/meteor21/Simulations/tree/analysis-dashboard).
Save that branch's `index.html` and open it in a browser for the interactive view.
`candidate_coverage.csv` and `data.json` contain the selected public metadata.
The `midterm-dashboard-<run-id>` Actions artifact also includes the real Colab bundle,
browser screenshots and validation reports; retention is 14 days.

## GitHub Pages

If the repository already has **Settings → Pages → Source → GitHub Actions**, the
workflow uploads the same site, deploys it using the official Pages action, and
checks the served HTML. Its deployment URL appears in the `github-pages` environment
and job notice. A published report branch or HTML artifact alone is not a deployed
Pages site.

If Pages is absent or uses another source, the rendered GitHub report is still
published and the job records the exact prerequisite. Set the source at
https://github.com/meteor21/Simulations/settings/pages and run the workflow again.
The normal GitHub workflow token can deploy an enabled site but cannot enable it
from scratch; no extra provider key is needed and no token should be pasted in chat.

## Reproduce locally from an analyzed checkpoint

Use the existing isolated Python environment and a dedicated empty output folder:

```bash
python -m charisma_lab.dashboard --pilot artifacts/analyzed-pilot --output artifacts/dashboard --repository meteor21/Simulations --analysis-run-id RUN_ID --code-revision COMMIT_SHA
node scripts/validate_dashboard.mjs --site artifacts/dashboard --report artifacts/dashboard_browser.json --screenshots artifacts/dashboard-screenshots
```

The browser check requires Node 24 and Chromium or Google Chrome. `CHROMIUM_PATH`
can select an installed binary. It tests filter results, candidate details, source
switching, explicit empty states, missing scores, responsive layout, script errors
and absence of external requests. Loopback HTTP is used only for this local test.

## Interpretation and public data

- FEC registrations are not verified contestants. Identity provenance is retained.
- URL counts are unreviewed search associations, not verified candidate mentions.
- National, state, metro, local and unknown scope remain distinct. A source's
  geographic scope does not establish candidate-state relevance or district readership.
- Profiles applied retrospectively without verified historical applicability are
  counted and flagged. Source ratings are not inferred or retrospectively assigned.
- Missing sentiment is not neutral. Media portrayal is separate from survey favorability.
- Published data excludes article titles/bodies, private reviews, credentials,
  response bodies, unrelated candidate identities and the raw database.

The default notebook demonstration remains synthetic; the published dashboard is
built only from the selected real checkpoint. Regenerate the notebook after Python
or documentation changes using `scripts/sync_notebook.py`.
