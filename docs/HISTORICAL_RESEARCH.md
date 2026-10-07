# Historical plan: 1990 onward

The executable model supports dates from 1990. It does not assert that open-web article text has uniform coverage over that period.

## Phase 1: establish the denominator
For each cycle, assemble all eligible House/Senate contests and candidates at the chosen historical cutoff, including losing and withdrawn/primary candidates where relevant. Official FEC candidate master downloads provide registration discovery, not a verified ballot. Use explicit stage and known_at fields. Your existing funding database can be reused without making the missing 1990s records appear present.

Separately import dated service terms to analyze coverage during office. Query the union of service intervals, not only the two years immediately before a reelection campaign. Office-only analyses exclude unsuccessful first-time candidates by construction; do not use that population to stand in for all election candidates.

## Phase 2: audit archive availability
Inventory publisher, source edition, geography, ownership/network affiliation where verified, first/last documented available coverage, archive provider, rights, gaps and extraction quality. A modern source directory is useful for discovery but insufficient for historical validity. Older source profiles and ideology assessments need evidence for the relevant period.

Media Cloud: discover URLs/metadata only for collected periods. Its source coverage begins when it began collecting a source. GDELT DOC: recent discovery only; no 1990s full-text promise. RSS: current incremental updates, not a historical backfile. Publisher/ProQuest/other licensed archives: import permitted source exports with per-title/date coverage. No automated account login or vendor-specific bulk export contract is fabricated.

## Phase 3: pilot intervals before mass collection
Use one earlier midterm cohort and the current cohort; sample both chambers and multiple source environments. Compare archive availability, name variants, OCR/transcription quality in supplied historical texts, and headline/body annotation accuracy. This package performs no automatic OCR.

Do not rate source reliability by whether an article's supported side later won. Do not select articles with queries about a desired scandal/success. Use candidate-name searches and explicit issue tagging after retrieval. Preserve the retrieval query, pagination and no-result jobs.

## Phase 4: longitudinal features
Create monthly snapshots with separate national/subnational scores, scope counts, bias strata, 30/90/180/731-day windows and service-period indicators. Momentum is the last 30 days minus the preceding 30 days where each interval meets coverage gates. Analyze missingness and outlet turnover alongside any time trend. These are observational associations, not an identified causal effect of an officeholder.

## Phase 5: evaluation
Build a human-labeled political portrayal set covering candidates, outlets, decades and office types. Use temporal splits by election cycle, not random state or article rows. Strict availability mode is only one safeguard: review historical model/version availability, sampling decisions, redistricting, archive survival, candidate identity, survey-release timing and uncertainty before claiming real-time historical forecasting performance. Today's language model may know historical outcomes even when names are masked. Retrospective reconstruction remains useful, but label it explicitly.

Current default minimum coverage often yields missing congressional scores. This is preferable to silently assigning neutral scores. Imputation, hierarchy and shrinkage may later be modeled with explicit uncertainty; they are not silently added to this release.
