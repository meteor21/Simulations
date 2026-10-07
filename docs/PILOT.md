# Bounded live pilot

The existing workers are reused by `python -m charisma_lab.pilot`. The pilot targets
24 distinct House/Senate candidate IDs in one selected even cycle (default 2026).
It exports candidate provenance and registration/contest status before search.
All selected candidates' contest rows are exported separately so a primary,
general or special election is not erased by the one-search-target-per-ID limit.
The default window is September 1–October 6, 2026; this narrow window tests the
machinery, not representativeness or historical backfile completeness.

## Offline preparation

From the repository root, after the isolated installation in `AGENTS.md`:

```bash
python -m charisma_lab.pilot --output /workspace/midterm-live-pilot
```

An empty registry produces **exit 2**, a header-only
`selected_congressional_cohort.csv`, `selected_contest_memberships.csv`,
`pilot_plan.json` and `pilot_report.json`, with zero HTTP attempts. No names are
invented. To prepare using actual existing data, choose one input route:

```bash
python -m charisma_lab.pilot --output /workspace/midterm-live-pilot --funding-db /path/to/original.sqlite
python -m charisma_lab.pilot --output /workspace/midterm-live-pilot --fec-zip /path/to/cn26.zip
python -m charisma_lab.pilot --output /workspace/reviewed-roster-pilot --candidates /path/to/candidates.csv --roster /path/to/roster.csv
```

The last route needs documented identities and contest memberships using the
existing templates. Election results are not required, and neither winners nor
incumbents are favored. FEC and funding routes remain registration discovery;
they do not certify ballot membership. Retrospectively observed registry metadata
are explicitly labeled. Actual historical forecast cohorts need dated full rosters.

## Live prerequisites and run

Configure `MEDIACLOUD_API_KEY` securely in the environment, scoped to
`search.mediacloud.org`. Permit that host and, only for an optional official FEC
ZIP, `www.fec.gov`. Do not put the key in shell arguments, reports, code or chat.
The program reads the existing binding without printing or persisting it.

```bash
python -m charisma_lab.pilot --output /workspace/midterm-live-pilot --run-network --download-fec
```

A missing key blocks all requests, including FEC. If a registration database is
already imported, the FEC download is unnecessary. Requests use TLS verification;
a policy/access denial stops the affected operation and is reported without
credential-bearing exception text. Credentials do not establish paid-service
approval; use only the existing permitted provider access.

One `RequestLedger` atomically charges every transport attempt **before** sending,
including failures and retries. Downloads, source-directory pages, search pages,
and any notebook publisher/robots/RSS requests share it. Its hard limit is 20
across restarts, with conservative charging if a process crashes mid-request.
The CLI resolves at most six sources with one page each and runs at most fourteen
search jobs; pagination and retries still consume the same allowance. Persistent
page jobs and downloaded FEC ZIP caching avoid repeated completed operations.

Resume the **same** directory/database, dates, provider and cohort. Do not copy an
older checkpoint over its budget ledger, reset request counts, run simultaneous
notebook writers, or create another directory to continue the same pilot after
20 attempts. A new, separately authorized study needs an explicit new scope.
The notebook uses the same persistent limiter but a separate database: it is an
alternative entry point, not another allowance to spend on the same pilot.

Full-text scraping, RSS, officeholder acquisition, model downloads and historical
collection are disabled by the CLI. Optional notebook switches share the request
ledger but require separate publisher permissions and may consume the remaining
allowance before any search occurs. Do not enable them for the initial pilot.
No running service or background crawler is needed.

## Inspect outputs

`pilot_report.json` reports attempts, missing inputs, source-resolution failures
and job status. `exports/` contains coverage, source provenance and reviewed-only
features; insufficient coverage and absent annotations stay missing. A completed
HTTP request, an empty search, or a blocked local source panel is not proof of a
working or representative news corpus. The current run has **zero live requests**,
no real registry and no provider credential; live compatibility is unvalidated.

## GitHub execution

The manual `Real 24-candidate pilot` Actions workflow runs the same CLI with
`--github-budget`. Every provider attempt must first reserve its count on a
separate small Git branch, so a fresh runner or missing artifact cannot reset the
20-request total. Database state and result tables stay in Actions artifacts.
See `GITHUB_COLAB.md` for secret setup, execution, artifact retention, and import.
