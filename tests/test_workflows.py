"""Execute the pilot workflow's Python steps, including a runner without deps."""
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from charisma_lab.transfer import read_bundle


ROOT = Path(__file__).resolve().parents[1]


def run_workflow_step(name, tmp_path, *, without_dependencies=False, credential=""):
    workflow = yaml.safe_load((ROOT / ".github/workflows/live-pilot.yml").read_text())
    step = next(s for s in workflow["jobs"]["pilot"]["steps"] if s.get("name") == name)
    prefix = "python - <<'PY'\n"
    assert step["run"].startswith(prefix) and step["run"].endswith("PY\n")
    code = step["run"][len(prefix):-len("PY\n")]
    env = dict(os.environ, PYTHONPATH=str(ROOT), GITHUB_SHA="fixture-commit")
    env.pop("MEDIACLOUD_API_KEY", None)
    if credential:
        env["MEDIACLOUD_API_KEY"] = credential
    command = [sys.executable, *(["-S"] if without_dependencies else []), "-"]
    return subprocess.run(command, input=code, text=True, capture_output=True,
                          cwd=tmp_path, env=env, timeout=30)


def test_export_without_outputs_needs_no_installed_dependencies(tmp_path):
    result = run_workflow_step("Export Colab tables even when collection is partial",
                               tmp_path, without_dependencies=True)
    assert result.returncode == 0, result.stderr
    assert "No pilot exports" in result.stdout
    assert not (tmp_path / "artifacts/real-analysis.zip").exists()


def test_partial_collection_still_exports_missing_values(tmp_path):
    exports = tmp_path / "artifacts/live-pilot/exports"
    exports.mkdir(parents=True)
    content = "candidate_id,media_recency_score\nH0TEST001,\n"
    (exports / "candidate_sentiment_summary.csv").write_text(content)
    result = run_workflow_step("Export Colab tables even when collection is partial", tmp_path)
    assert result.returncode == 0, result.stderr
    manifest, files = read_bundle(tmp_path / "artifacts/real-analysis.zip")
    assert manifest["dataset_kind"] == "real"
    assert manifest["source_commit"] == "fixture-commit"
    assert files["agents/candidate_sentiment_summary.csv"].decode() == content


@pytest.mark.parametrize("credential", ["", "   "])
def test_missing_credential_reports_actionable_annotation_without_dependencies(tmp_path, credential):
    result = run_workflow_step("Check secure provider credential", tmp_path,
                               without_dependencies=True, credential=credential)
    assert result.returncode == 1
    assert "::error title=Missing Media Cloud secret::" in result.stdout
    assert "MEDIACLOUD_API_KEY" in result.stdout
    assert "https://github.com/meteor21/Simulations/settings/secrets/actions" in result.stdout


def test_credential_preflight_does_not_echo_key(tmp_path):
    credential = "nonsecret-test-fixture"
    result = run_workflow_step("Check secure provider credential", tmp_path,
                               without_dependencies=True, credential=credential)
    assert result.returncode == 0, result.stderr
    assert credential not in result.stdout + result.stderr
