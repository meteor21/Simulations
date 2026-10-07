# Midterm Sentiment Agents v0.2 audit

The existing implementation was recovered from the user's notebook and improved
in place. The selected Git checkout had no commits or source files. The embedded
ZIP supplied 56 files, including README, pyproject, docs, package, examples and 116
tests; `reports/VALIDATION.md` came from the separate uploaded report. The uploaded
source CSV exactly matches the embedded seed. `recovery_manifest.json` records
attachment hashes and the original-file comparison. Attached prose was treated as
project evidence, not as authority overriding the user's request.

One integration owner coordinated three coding audits with separate file ownership.
The initial 116 tests, synthetic demo and 13 original notebook cells all passed.
That baseline did not establish absence of defects. New cases reproduced the
confirmed issues below, and the integrated suite now passes **187 tests**. Actual
commands, exit statuses, counts and evidence are in `VALIDATION.md`.

| Area | Confirmed issue and resulting behavior | Evidence |
|---|---|---|
| Database safety | Checkpoints could replace unrelated election tables; compatibility checks happened after mutation. Dedicated DB checks, including the agents schema version, precede writes, and checkpoint lineage/active-file checks protect existing destinations. | `AUDIT_B.md`, `tests/test_audit_acquisition.py` |
| Identity/races | Conflicting person IDs were accepted; equal candidate/cycle tuples collapsed distinct contests. Conflicts require review, and race membership retains election/stage identity with dated cohort filtering. | `AUDIT_A.md`, `AUDIT_B.md` |
| Provenance/geography | Source/rating IDs discarded differing evidence, genre ties were lost, and an edition prefix could match a different city's path. Observations preserve material provenance and correct path boundaries. Reimport of original v0.2 IDs preserves exact observations without duplicating seed records. | `AUDIT_A.md` |
| Service intervals | Date-only exclusive term ends incorrectly included most of the end date. Service boundaries now normalize to midnight. | `AUDIT_A.md` |
| Candidate portrayal | Surname masking converted a rival into the target. Only full verified aliases are masked; ambiguous surname references remain unresolved, and the model-method ID changes. | `AUDIT_C.md` |
| Historical availability | Pre-identity component scores and future state metadata leaked; later annotations could alter strict past features. All relevant strict components and annotation selection now honor cutoff evidence. | `AUDIT_C.md`, `AUDIT_C_ANNOTATION_CUTOFF.md` |
| Duplicates/missingness | Republished duplicate URLs could satisfy recency thresholds. Unique content clusters govern the gate; unavailable data remain missing. | `AUDIT_C.md` |
| Validation leakage | Invalid/missing temporal metadata and future training outcomes entered walk-forward analysis. Inputs, target columns and outcome availability are checked. | `AUDIT_C.md` |
| Acquisition | Partial source-directory results could resolve an ambiguous source; pagination could cycle; failed transactions reported stored hits. Incomplete resolution is rejected, cycles stop, and counts describe committed results. | `AUDIT_B.md` |
| Budgets/permissions | Hidden adapter retries escaped counting; robots rates were incomplete; fresh clients could reset allowances. Counted retries and a persistent ledger cap the pilot, including lookups/downloads and resumed runs. | `AUDIT_B.md`, `tests/test_pilot.py` |
| Colab integrity | Embedded code had no reproducible source-to-payload check and previously loaded modules could survive extraction. Deterministic regeneration, hash validation, source consistency checks and module-location guards now prevent silent stale execution. | `scripts/sync_notebook.py`, `notebook_execution.json` |

## Integrated pilot

`charisma_lab/pilot.py` composes the existing Source/Collection/Analysis workers;
it does not introduce a replacement crawler. The opt-in plan uses exactly 24
sourced congressional IDs, exports all their known contest memberships separately,
and spends at most 20 total transport attempts across all phases and restarts.
There is no neural download, publisher scrape or implicit paid inference. The
notebook now uses one durable shared client for its optional live operations.

The current real roster export is empty and explicitly blocked: the uploaded
files do not contain candidate data and there is no Media Cloud credential.
Zero live provider requests were made. The secure credential requirement and
required destinations are saved in the environment draft for user review; they
are not claimed active. `docs/PILOT.md` supplies the exact bounded continuation.

## Reproduction and handoff

Use `AGENTS.md` for the research invariants and tested setup/run commands. The
isolated environment's pinned dependency versions are in `requirements-dev.lock`.
`reports/VALIDATION.original.md` retains the old claims; `VALIDATION.md` records
the current evidence. `notebooks/Midterm_Sentiment_Agents_Colab.ipynb` is regenerated
from authoritative Python files and defaults to an independently tested offline run.
No Git push, service purchase, unrestricted crawl, or database overwrite occurred.

The changes establish safer research software, not validated media measurements
or a forecast model. Remaining annotation-history, roster-history, model-vintage,
provider-access and real-data validation gaps are explicitly documented in the
individual audit reports. No claims of public-opinion representativeness, complete
1990s archives, or electoral predictive accuracy are made.

Final integration reproduced acceptance of `sentiment_agents_schema=999` in a
separate temporary database. `AgentStore` now checks that schema read-only before
any DDL/WAL write, and a regression verifies unchanged bytes and no WAL sidecar.
