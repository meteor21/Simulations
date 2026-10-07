# Data contracts and review workflow

## Source profiles
`data/source_profiles.csv` defines domain, name, scope, states_json, geography_json, source_kind, network_group, applicability dates, observation date, evidence, status, optional edition URL prefix, permitted_fetch, optional Media Cloud ID and notes. A domain may have an edition-specific geographic profile. Dates should be full ISO timestamps when intraday timing matters. Date-only inputs normalize conservatively to the end of the date.

Current starter profiles have evidence observed October 6, 2026. They do not certify that the same outlet, ownership, editorial stance or coverage geography existed in 1994. Retrospective use of a current scope is flagged; import historical evidence to replace that assumption.

For additional sources, fill `inputs/extra_source_profiles.csv`, leaving permitted_fetch=0 until terms/permissions and robots access are established. A provider's directory country/state may describe headquarters. Do not automatically turn it into local audience scope. `SourceAgent.discover_collection` returns a review proposal, not an approved profile.

## Political-orientation assessment
Required: domain, provider, label, valid_from, available_at, evidence_url. Optional: valid_to, genre, native_score, native_scale, method, status, confidence_label, sample_n, license_note, metadata_json. Supported labels: Left, Lean Left, Center, Lean Right, Right, Unknown. Keep native scales and provider names; do not silently average ratings with different semantics. Disagreement can be emitted as Mixed/Disputed when multiple providers are selected.

For a historical retrospective human assessment, valid_from/to describes the historical texts assessed while available_at describes when the assessment was actually produced. Such evidence cannot be used by a strict model before available_at. Never backdate it to the historical period merely to make it pass a cutoff.

## Candidate registry and contest roster
Use existing templates `candidates.csv`, `aliases.csv` and `roster.csv`. A candidate_id is not necessarily a lifelong person_id. `sa_identity_links` provides documented identity crosswalks. Full-name aliases and office context reduce false positives, but are not infallible. A surname-only newspaper mention is not automatically resolved.

`roster.csv` needs candidate_id, election_id, cycle, office, state, district, stage, known_at and source_url. Registration-only candidates can be searched for discovery but cannot silently become general-election nominees. Losers and withdrawn candidates need explicit stage and observation dates.

## Service history
`service_terms.csv`: person_id, optional candidate_id, office, state, district, party, start_date, end_date, available_at, evidence_url. Dates are service intervals with exclusive end. Historical/current congress-legislators YAML imports canonical Bioguide identities, terms and documented FEC links. This does not create a full ballot roster, measure performance in office, or verify a scheduled term actually finished.

## Archive article JSONL
One JSON object per line, using the original publisher URL when known:
```json
{"url":"https://publisher.example/archive/item123","title":"Representative Alex Rowan debates the budget","published_at":"1994-09-20T12:00:00Z","candidate_ids":["YOUR_VERIFIED_ID"],"body":"Permitted text from your archive export.","retrieved_at":"2026-10-06T16:00:00Z","available_at":"2026-10-06T16:00:00Z","availability_basis":"retrieved_version","rights_note":"Your actual license/permission note","source_note":"Archive vendor/title/record and export details","archive_record_id":"123","genre":"news"}
```
This example is fictional and must not be used as real evidence. For a documented historical content snapshot, `availability_basis="verified_archive_version"` requires an `archive_evidence_url`, and available_at must reflect evidence of that specific version's availability. An old publication date on a currently retrieved and updated page does not suffice.

## Independent corpus for ideology proposals
`independent_bias_samples.jsonl` fields: domain, url, title, body, published_at, available_at, sampling_frame, rights_note, evidence_url. Accepted frames: outlet_politics_random, outlet_politics_systematic, human_balanced_outlet_sample. The body must be substantive text. Candidate-query frames are rejected. The model's probabilities are uncalibrated heuristic outputs. Their aggregation is a review aid, not an external provider rating or proven political scale.

## Human annotation review
Export `annotation_review.json`. Review whether the person is correctly identified, whether the text is a quotation versus outlet narration, and whether portrayal is positive, negative, neutral/mixed or unresolved. Import documented results through `annotations.csv` with version_id, candidate_id, sentiment in [-1,+1], entity_status, reviewed, evidence and model_id. Preserve the reviewer/rubric version in model_id. No-match and needs-review rows do not qualify for scoring. Do not mark an entire model output reviewed without actually reviewing it.

## Survey and pedigree bridge
Original `surveys.csv` and `pedigree.csv` templates are retained. They must be real source-backed observations. Survey release time, fieldwork time, geography, population, scale and estimate are distinct fields. A report of public discontent is not a favorability survey. The bridge never fabricates absent poll or political-history data.

## Security and rights
Network requests are bounded; publisher pages require a permitted-domain allowlist and robots checks; local/private network addresses and unsafe redirects are blocked. XML feed parsing rejects entity expansion. External pages are classifier input, not commands to execute. No search result can instruct the worker to reveal a key, install software or bypass a paywall. Keep API keys in Colab Secrets or hidden inputs; they are not saved in events or exported files. Observe copyright, database licenses and publisher/API terms independently of robots rules.
