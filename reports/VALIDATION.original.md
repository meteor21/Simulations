# Midterm Sentiment Agents v0.2 — validation report

Build date: October 6, 2026. This report describes tests actually executed in the development container. It does not claim live nationwide collection or political-sentiment accuracy.

## Executed checks

| Check | Result |
|---|---|
| Automated Python tests | **116 passed, 0 failed, 0 errors** |
| Entire notebook default offline path | **13 code cells executed; 25 total cells; zero errors** |
| Three-worker integration | Synthetic source, search-provider and model fixtures; successful planning, collection, annotation and export |
| Real seed source profiles imported | **63**: 12 national, 50 state-focused, 1 metro |
| Distinct state codes in seed | **50** |
| Dated source-rating records imported | **6** attributed AllSides category snapshots, October 6, 2026 |
| Live real candidate-news articles collected in this runtime | **0** |
| Actual downloaded neural-model inference validated | **No** |
| Colab Drive mounting and live APIs validated | **No** |

`test_results.xml` contains the test names and machine-readable outcomes. `notebook_execution.json` records the executed offline notebook check. All generated notebook code cells were syntax checked. The source code and seed tables embedded in the notebook match this release's package.

## Tests cover

The retained 71 v0.1 tests plus 45 new tests check source geography and edition prefixes; candidate H/S scope; registry versus contest membership; identity crosswalk conflicts; current-versus-historical source and ideology evidence; unknown versus center; provisional ratings excluded from approved strata; matched full names and ambiguity review; retrospective versus strict cutoffs; future publication exclusion; version and duplicate handling; national/local routing; candidate-state restrictions; equal outlet weights with no ideology penalty; missing components; scope coverage gates; exclusive service end dates; local state inferred only from a documented active office; historical plan limits; job idempotency; API budget stops; archive availability evidence; independent ideology-sample requirements; safe RSS/Atom parsing; checkpoints and exports.

These checks exercise logic, not representativeness of source coverage or validity of language-model classifications. Fixtures do not establish provider schema stability, credentials, rate limits, permissions, publisher extraction quality or historical backfile access.

## Synthetic demonstration

The invented candidates Alex Rowan (House, MI) and Jordan Vale (Senate, PA) each have fixture national portrayal 80 and local portrayal 20, yielding a media-recency value of 50 under the explicit equal local/national mix. Both have fictional recorded service covering the assessment date. The test lowers coverage gates for its tiny sample. These numbers are not real political data, not a favorability estimate and not a win probability. They do not enter the real working database.

## Network limitation

Direct HTTP attempts from the development runtime failed at DNS/network access, including attempted official FEC/GitHub data acquisition. Web browsing was available for documentation and source-rating verification, but not as an unrestricted bulk Python collection service. No completed real candidate corpus, successful publisher scrape, or full historical roster is claimed. The notebook exposes bounded network operations for execution in Colab with the user's provider access.

## Research limitations requiring a live pilot

The local source seed is a network/partner discovery directory rather than an independently balanced local-news panel. Most states initially have only one configured state-focused source, which does not pass the default two-outlet local scoring gate. Add reviewed independent local publishers; do not lower the gate silently to manufacture coverage. No complete all-district news inventory or statewide readership model is claimed.

Most sources have no approved political-orientation score; they remain Unknown. The six seed labels are current snapshots and do not label historical periods. The optional model-based ideology proposer needs an independent permitted sample and human validation. No external rating provider's numerical score is inferred from its category.

The classifier is an unvalidated target-portrayal baseline. Names are masked after a full-name match, but historical knowledge, source selection, quotation, sarcasm and identity ambiguity remain risks. Automatic annotations remain distinct from reviewed evidence. Confidence output is not calibrated accuracy. Media portrayal, polling favorability, political experience and causal electoral influence are different quantities.

The 1990-onward functions require actual archive records. Modern-source survival and archive availability cannot be solved by changing a date parameter. Historical analyses must disclose missing sources, publication/version timing, model vintage, selection, and retrospective reconstruction. No downstream electoral prediction accuracy has been measured in this release.
