# Integration follow-up: annotation availability

The integration review identified a remaining strict-history leak: an article/version could predate the cutoff while its human review or model inference occurred after the election. Checking only document-version availability allowed that later annotation to change historical scores. This follow-up closes that gap; it supersedes the original audit's statement that annotation timing was not enforced.

## Changes

- Both `eligible_portrayals` and the legacy `news` scorer now exclude annotations whose `annotated_at` is later than the strict cutoff. Filtering happens before selecting one annotation/version per article, preserving an eligible earlier annotation when a later model/rubric also exists.
- Retrospective/research modes retain later annotations and explicitly emit `later_annotations_present`; agent summaries also count `retrospectively_annotated_articles`.
- Worker B added `Store.annotation` arguments `annotated_at`, `annotation_basis`, and `annotation_evidence_url`. No explicit timestamp means the actual current creation time. Historical timestamps require declared, persisted provenance: `verified_annotation_record` with evidence, or explicitly marked synthetic fixtures. Unsupported backdating is rejected.
- Worker A extended CSV annotation imports and documented those optional provenance fields. Real imports do not inherit publication time as annotation time.
- Existing fictional strict tests and the fictional `examples/offline_demo.py` now explicitly declare their hypothetical fixture annotation dates and `synthetic://` evidence. The existing behavioral assertions remain; no strict test was relaxed into retrospective mode to regain a passing result. Automatic annotation workers continue to timestamp inference at actual execution time.

## Regression coverage

Four new analysis test cases cover post-cutoff reviewed human annotations, post-cutoff automatic model annotations, retaining the earlier eligible annotation despite a later model/rubric, and date-only annotation availability interpreted conservatively at the end of the UTC day. They check both strict exclusion and explicit retrospective inclusion. Database-safety tests separately cover rejection of unproven annotation backdating.

## Executed checks

All commands ran from `/workspace/Simulations`:

```bash
/workspace/.venvs/midterm-sentiment/bin/python -m pytest --junitxml=reports/audit_c_annotation_cutoff_tests.xml
# 178 passed in 2.21s.

/workspace/.venvs/midterm-sentiment/bin/python examples/offline_demo.py --out /tmp/midterm-audit-c-annotation-offline
# Exit 0; SYN-A 76.889029 -> 51.081849; SYN-B remains missing.

/workspace/.venvs/midterm-sentiment/bin/python examples/agents_demo.py
# Exit 0; both fictional candidates: national 80, local 20, media 50.
```

No provider requests or model downloads were made. The integration owner regenerates and executes the notebook after these changes.

## Remaining scope limits

A timestamp/evidence reference records the annotation's declared provenance; it cannot independently certify an external reviewer or artifact. Historical model training/revision availability still requires a separate audit before claiming forecasting validity. A new model/rubric should use a distinct `model_id`; the existing `(version_id, candidate_id, model_id)` storage key represents one record for each such combination, so replacing the same key is not an append-only annotation history. A later same-key replacement can remove an earlier label from historical reconstruction, but its later timestamp cannot leak its score into strict results.
