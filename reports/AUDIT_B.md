# Acquisition, request limits, and database audit

Audited the recovered Python implementation, preserving its adapters, sequential workers, SQLite schema, and queue model. All checks in this report are offline. No provider, source-directory, publisher, model-download, or credential-bearing requests were made by this audit agent.

## Confirmed defects and corrections

- **Destructive checkpoint replacement.** A temporary-database reproduction showed `Store.backup(elections.sqlite)` deleted an existing `election_results` table. Checkpoints now require matching project database lineage before replacing an existing file. Other project databases, unrecognized legacy checkpoints, and active SQLite sidecars are refused. Unique temporary files replace the fixed `.tmp` name, preserving user files. New checkpoints retain the origin database's `cs_meta.database_id`; repeated checkpoints to that owned destination work. For a legacy checkpoint without lineage, use a new destination; do not overwrite the old file.
- **Mutation before schema rejection.** Opening a database marked schema 999 created `cs_articles` before raising an incompatibility error. Existing files are now inspected read-only before WAL mode or schema DDL. Unrelated election/funding databases are refused as writable stores; import them through the existing read-only import path. The old test that permitted inserting project tables into an unrelated database now asserts rejection and unchanged bytes instead.
- **Hidden adapter retries.** A supplied `requests.Session` could contain an HTTP adapter with retries outside `requests_used`. Adapters now have retry counts disabled, leaving retries to the explicit counted loop. TLS verification is explicit. `HttpClient(..., before_request=callback)` allows the pilot to reserve durable budget immediately before every attempted request; a failed reservation sends nothing. Reservations consumed by a crash remain consumed conservatively.
- **Incomplete source-directory resolution.** The resolver previously accepted one exact homepage match even if it stopped at `max_pages` with additional pages remaining. It now reports `incomplete_directory_search` and leaves the source unresolved. This prevents a partial directory search from claiming uniqueness.
- **Pagination cycles.** Tokens A → B → A could silently close the queue with incomplete results because the old job already existed. Returning to an existing cursor now records an explicit error and does not mark that page complete.
- **Rolled-back hit counts.** A malformed second item could roll back the complete page while the returned report still counted its first item. Hit counts now advance only after the page transaction commits.
- **Robots request-rate.** Publisher `Request-rate` was ignored when no `Crawl-delay` was supplied. The stricter interval now applies, while the parsed robots policy remains cached within the scraper instance.
- **RSS iterable consumption and limits.** A generator of candidate IDs was consumed repeatedly inside the candidate-row comprehension, dropping later candidates. The selector is now materialized once and checked before network access. Negative item limits are rejected; zero items produce no request.
- **Identity and race boundaries (coordinated with audit A).** Conflicting candidate/person reassignment is refused. Cohorts preserve election ID and stage rather than collapsing primary/general or regular/special membership, and optional `as_of` checks both candidate and membership availability. Date-only service boundaries are interpreted at midnight with an exclusive end (the storage normalization is coordinated with audit A).

- **Dated annotation provenance (coordinated with audit C).** `Store.annotation` now accepts `annotated_at`, `annotation_basis`, and `annotation_evidence_url`. Historical timestamps require explicit verified-record or synthetic-fixture evidence; provenance is stored in diagnostics. This enables strict scoring to reject annotations that were unavailable at the historical cutoff rather than backdating modern labels silently.

## Actual commands and results

Working directory: `/workspace/Simulations`.

Before source edits, a Python reproduction created separate temporary SQLite files and tested the old backup and incompatible-schema behavior. Its actual output was:

```text
Backup preserved election_results: False
Rejected schema nevertheless created cs_articles: True
```

The initial targeted run after implementation found the intentional legacy-contract conflict described above: `test_unrelated_table_preserved` still expected writable access to an unrelated database. That test was corrected to the user-required read-only database contract. New test scaffolding initially had two missing optional-extractor mocks and one SQL placeholder error; these were corrected without requiring an optional package download.

Final acquisition-focused command:

```sh
/workspace/.venvs/midterm-sentiment/bin/python -m pytest \
  tests/test_audit_acquisition.py tests/test_workers.py tests/test_core.py tests/test_agents.py \
  -q -o addopts=''
```

Actual result at that integration stage: **126 passed in 0.52s**, including **20 new acquisition cases**. These cover retry accounting and durable reservations, hidden adapter retries, redirects plus robots sharing one counter, rejected cross-domain redirects, robots policy caching/rate limits, preservation of database files, safe repeat checkpoints, conflicts, truncated directory pages, cyclic pagination, page rollback, dated multi-race cohorts, RSS generators, and zero-item limits. HTTP responses and DNS permission checks are mocked explicitly; the tests establish local control flow, not live provider availability or extraction quality.

After the annotation-provenance follow-up, the additional regression and the acquisition suite were rerun:

```sh
/workspace/.venvs/midterm-sentiment/bin/python -m pytest tests/test_audit_acquisition.py -q -o addopts=''
```

Actual result: **21 passed in 0.13s**. The integration owner runs the final combined suite after all coordinated annotation-cutoff changes.

## What is retained and what is not established

The existing design commits each successful provider page and its next cursor together, deduplicates queued payloads, caches fetched article bodies, and logs fetch outcomes. Exhausted request budgets return interrupted jobs to `pending`; access/schema failures require explicit correction and requeue. A manual interrupted-job reset must only run after confirming there is no other writer. There is no general persistent HTTP response cache or claim that rerunning source discovery costs zero requests; resolved source IDs and successful queued pages provide the persisted reuse. The pilot's persistent request ledger is integrated separately by the integration owner.

Robots, every article redirect, source lookup, timeout retry, and rate-limit retry use the supplied shared client. Provider adapters do not auto-follow redirects. A per-client limit alone is not a lifetime pilot cap: all resumed pilot phases must use the durable reservation callback and the same ledger, as the pilot implementation does. Requests outside this client, such as manual downloads, cannot be counted by it and must not be added to the bounded live workflow.

Publisher extraction still requires explicit permitted domains and publisher terms/rights, honors robots, rejects login/access-denied responses, and does not bypass restrictions. DNS public-address checks are preflight checks; they do not pin the transport address against a malicious DNS rebinding race. The pilot disables publisher scraping. Optional extraction/model packages are not needed for the offline demonstrations or these tests. Provider schemas, content completeness, production API pagination, and publisher extraction remain unverified live until the controlled pilot is authorized and credentials are available.
