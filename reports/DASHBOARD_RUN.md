# Published real analysis visualizations

The real analysis ran on GitHub and its visual report is publicly available at:

https://github.com/meteor21/Simulations/tree/analysis-dashboard

The first publication workflow [38097810150](https://github.com/meteor21/Simulations/actions/runs/38097810150)
completed successfully in 1 minute 1 second on source/request commit `b8ace01`.
It restored the original real collection `37680664034`, reanalyzed its saved
checkpoint, checked the actual desktop/mobile dashboard in Chromium, verified
the real Colab bundle import, and published report commit
`f8580f9d507885bcce87238f9911825f9f730970` on `analysis-dashboard`.
The public report returned HTTP 200 with its three SVG charts linked.
Concurrent offline CI [38097810204](https://github.com/meteor21/Simulations/actions/runs/38097810204)
also succeeded; the integrated Python suite has **315 passing tests**.

## What the real data shows

| Observation | Verified result |
|---|---:|
| Selected congressional registrations | 24 |
| Saved distinct news URLs in the original window | 3 |
| National / state / metro / local / unknown source scope | 3 / 0 / 0 / 0 / 0 |
| Candidates with at least one unreviewed search association | 16 |
| Candidate-to-URL search associations | 24 |
| Completed search jobs / blocked / errors | 6 / 0 / 0 |
| Reviewed candidate-specific annotations | 0 |
| Candidates with usable sentiment scores | 0 |
| URLs using retrospectively applied, historically unverified source profiles | 3 |
| Cumulative provider allowance | 16 of 20 used |
| Provider requests made by analysis/publication | 0 |

The window remains **September 1–October 6, 2026**. The 16 linked candidates do
not have verified mentions merely because they were associated with a search
batch. Eight identities have no saved search-linked URLs. Missing scores remain
null; no sentiment, public-opinion estimate or forecasting accuracy is invented.
National source scope does not verify candidate-state relevance, and its historical
applicability for these three articles is explicitly flagged as unverified.

The interactive dashboard supports name/FEC-ID search, chamber/state/coverage
filters, candidate evidence and missingness details, URL/candidate chart units,
and attempted-source versus relevant-catalog views with provenance dates. The
rendered GitHub report includes the same substantive counts, SVG charts and table.
The page is self-contained and loads no third-party JavaScript or external data.

## Verification and publication boundary

The published branch was fetched by its exact commit and the real public HTML/data
were checked again locally in Chromium. All 16 initial interaction/layout tests
passed, with zero script errors and zero external page requests. Visual inspection
prompted one usability correction: selecting a candidate now scrolls and focuses
its evidence panel into view. A seventeenth browser assertion verifies visibility
against the real 24-candidate dataset. Five renderer regressions and all 14 default
notebook cells passed after that change. The notebook's embedded Python was regenerated.

The dashboard contains only selected candidate identity fields, publisher URL/date
metadata, sourced geography, derived missingness/counts and request accounting.
Article titles/bodies, private reviews, secrets and SQLite are excluded. The report
branch is independently owned and updated without force-pushing or touching the
original database, `main`, or the live request-budget branch.

## Standalone site prerequisite

The workflow's Pages check returned **Pages is not enabled**. The visual report is
published; a GitHub Pages website has **not** been claimed as deployed. The normal
workflow token can deploy an enabled site but cannot enable Pages itself.

Set **Source → GitHub Actions** at
https://github.com/meteor21/Simulations/settings/pages, then rerun **Publish real
analysis dashboard**. Its already prepared deploy job will publish the interactive
site and verify the served HTML without new provider requests. Until then, download
the report branch's `index.html` and open it locally for the same interactive view.

All report/data outputs and browser/Colab verification files are also retained in
the `midterm-dashboard-38097810150` Actions artifact for 14 days. The original
collection artifacts remain under their existing retention policy.
