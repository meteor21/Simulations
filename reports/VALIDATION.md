# Midterm Sentiment Agents v0.2 — reproduced and corrected validation

Audit date: October 6, 2026 (America/New_York). Machine logs use UTC and may show
October 7. The supplied report is retained verbatim as `VALIDATION.original.md`.
No earlier pass claim was accepted without rerunning its checks.

## Current evidence

| Check | Actual result | Evidence |
|---|---|---|
| Original recovered Python package | 116 passed, 0 failed, 0 skipped | `baseline_tests.xml`, `baseline_tests.log` |
| Original offline notebook defaults | 13 code cells / 25 total, all executed in order in a shared Python namespace | `baseline_notebook.json` |
| Corrected integrated suite | **195 passed, 0 failed, 0 errors, 0 skipped** | `test_results.xml`, `test_results.log` |
| Three-worker synthetic demonstration | Both invented candidates: national 80, local 20, media recency 50, in-office true | `agents_demo.json` |
| Legacy synthetic offline demonstration | SYN-A standing 76.889029 → 51.081959; SYN-B stays missing | `offline_demo.log` |
| Corrected notebook defaults | **14/14 code cells**, fresh Jupyter kernel, no errors, zero network attempts | `notebook_execution.json`, `notebook_validation.log` |
| Embedded package consistency | Every selected source file matches the regenerated payload | `python scripts/sync_notebook.py --check` |
| Dependency consistency | No broken requirements | `pip_check.log`; exact versions in `dependency_versions.json` and `../requirements-dev.lock` |
| Real source directory | 63 profiles: 12 national, 50 state-focused, 1 metro; 50 state codes | Existing executed source-seed tests |
| Source ratings | 6 attributed, dated snapshots; unknown/current-vs-historical distinctions retained | Executed seed and provenance tests |
| Pilot preflight | Exit 2 with explicit missing registry; 0 selected real candidates, **0 HTTP attempts** | `pilot_preflight.log`, `pilot/pilot_report.json` |
| Live provider, publisher scrape, downloaded neural inference, Colab Drive | **Not run / not validated** | Missing prerequisites and optional scope below |

The new total includes 79 added regression cases. Existing assertions were not
silently disabled: the old expectation permitting writes into unrelated databases
was corrected to require refusal, and the old blanket-surname masking assertion
was corrected to preserve a rival's identity. Synthetic annotation helpers now
provide explicitly fictional, dated annotation evidence for strict-cutoff tests.
An original-database copy also exposed duplicate source observations after reimport;
exact-value reuse now keeps its 63 profiles/6 ratings unchanged. An integration
regression verifies unsupported agents schema versions are rejected before mutation.
A/C pre-fix regression runs demonstrate failures against the unmodified package;
see the linked audit reports and their machine-readable evidence.

## Actual commands

From `/workspace/Simulations`, Python 3.12.14 in
`/workspace/.venvs/midterm-sentiment`:

```bash
python3 -m venv /workspace/.venvs/midterm-sentiment
/workspace/.venvs/midterm-sentiment/bin/python -m pip install -e '.[dev]' ipykernel
# Initial install used to reproduce the original package baseline.
/workspace/.venvs/midterm-sentiment/bin/python -m pytest --junitxml=reports/baseline_tests.xml
/workspace/.venvs/midterm-sentiment/bin/python examples/agents_demo.py

# Final repeatable setup pins the tested dependency environment.
bash scripts/cloud_setup.sh
/workspace/.venvs/midterm-sentiment/bin/python -m pip check
/workspace/.venvs/midterm-sentiment/bin/python -m pytest --junitxml=reports/test_results.xml
/workspace/.venvs/midterm-sentiment/bin/python examples/agents_demo.py
/workspace/.venvs/midterm-sentiment/bin/python examples/offline_demo.py --out /tmp/midterm-offline-demo
/workspace/.venvs/midterm-sentiment/bin/python scripts/sync_notebook.py
/workspace/.venvs/midterm-sentiment/bin/python scripts/sync_notebook.py --check
/workspace/.venvs/midterm-sentiment/bin/python scripts/validate_notebook.py
/workspace/.venvs/midterm-sentiment/bin/python -m charisma_lab.pilot --output /workspace/midterm-live-pilot
# Last command deliberately exits 2: no sourced candidate registry is present.
```

Command output was redirected into the listed logs with the original exit status
preserved. `setup_repeatability.log` records re-running the saved setup script.
The original notebook was executed without changing any default code cells; the
corrected notebook was additionally tested with HTTP/socket-denial guards. Neither
check exercises Colab-specific storage mounting or a production search response.

## Pilot blockers and exact next steps

No `MEDIACLOUD_API_KEY` is present in the actual process, and the initial environment
configuration declared no credential bindings. There is no real candidate registry,
FEC ZIP, funding database or sourced 24-candidate roster among the uploaded files.
The uploaded CSV is a source catalog, not a candidate roster; it exactly matches
the embedded source-profile seed. Both real roster exports are therefore header-only.
Synthetic fixture people have not been substituted for real candidates.

The initial restricted network policy did not list `search.mediacloud.org` or
`www.fec.gov`. A saved environment draft adds these destinations, the missing secure
Media Cloud credential requirement, the tested `install_script`, and `start_skill`.
This save does not apply runtime changes, provide a credential, or publish a snapshot.
Review/save the draft in environment settings, supply the credential securely,
and publish the prepared environment. Then rerun the bounded pilot command in
`docs/PILOT.md`, or supply existing sourced input files. FEC discovery is permitted
only with the live prerequisites and counts toward the same 20-request allowance.

A synthetic 24-person pilot regression tests selection and exports, and transport
fixtures prove retries plus restarts cannot exceed the durable ceiling. Those are
software tests, **not** a completed 24-real-candidate live pilot. No access denial
was bypassed and no paid service was purchased.

## Research limitations

Media portrayal is not survey favorability or public opinion. Sentiment accuracy,
identity disambiguation accuracy, provider schema compatibility, archive coverage,
and electoral predictive value remain unvalidated on real data. One state source
per state is neither independent local coverage nor a sufficient default local panel.
No political-orientation penalty is applied. Most sources remain unrated.

Strict features now gate article versions, candidate identity, dated source/rating
facts, service evidence **and annotation availability**. Post-cutoff publications
remain excluded even in retrospective mode. Modern model knowledge/training
vintage is not certified historically valid. Same-model annotation replacement can
remove earlier evidence rather than reconstruct an append-only history; a later
replacement cannot enter a strict earlier snapshot. Roster and alias tables are not
complete versioned evidence ledgers; freeze sourced historical input snapshots.
Exact hashes do not solve paraphrased syndication, OCR variation, or correlated
outlet ownership. See `AUDIT.md`, `AUDIT_A.md`, `AUDIT_B.md`, `AUDIT_C.md`, and
`AUDIT_C_ANNOTATION_CUTOFF.md` for confirmed fixes and remaining limits.

The current isolated environment and offline workflow are validated. Publication
and restoration into a new task have not been tested or claimed.

## GitHub-to-Colab handoff follow-up

Five additional transfer tests cover permitted exports, preservation of missing
values, GitHub artifact ZIP wrappers, checksum failures, unsafe archive paths, and
rejection of fixture files labeled real. The notebook now has 14 code cells
(including results import) and 27 total cells. Both default execution and actual
bundle import were validated in a fresh local kernel. `GITHUB_HANDOFF.md` records
current commands/results; earlier audit evidence is preserved in `*.pre_github.*`.
