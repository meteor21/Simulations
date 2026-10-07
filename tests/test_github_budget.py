import json
import subprocess
import pytest
from charisma_lab.github_budget import GitRequestBudget, BRANCH
from charisma_lab.network import BudgetExceeded


def git(folder, *args):
    return subprocess.check_output(['git', *args], cwd=folder, text=True, stderr=subprocess.DEVNULL).strip()


def repositories(tmp_path):
    remote = tmp_path / 'remote.git'
    remote.mkdir()
    git(remote, 'init', '--bare')
    clones = []
    for name in ('first', 'second'):
        folder = tmp_path / name
        folder.mkdir()
        git(folder, 'init')
        git(folder, 'remote', 'add', 'origin', str(remote))
        clones.append(folder)
    return remote, clones


def test_remote_budget_survives_fresh_runner_and_caps_total(tmp_path):
    remote, (first, second) = repositories(tmp_path)
    a = GitRequestBudget(first, policy={'cycle': 2026}, limit=2)
    assert a.reserve() == 1
    b = GitRequestBudget(second, policy={'cycle': 2026}, limit=2)
    assert b.reserve() == 2
    with pytest.raises(BudgetExceeded): a.reserve()
    record = json.loads(git(remote, 'show', BRANCH + ':budget.json'))
    assert record['used'] == 2
    assert record['policy'] == {'cycle': 2026}
    assert git(remote, 'ls-tree', '--name-only', BRANCH) == 'budget.json'
    assert not (first / 'budget.json').exists()


def test_remote_policy_cannot_be_changed_to_reset_budget(tmp_path):
    remote, (first, second) = repositories(tmp_path)
    GitRequestBudget(first, policy={'cycle': 2026}, limit=1).reserve()
    with pytest.raises(ValueError, match='incompatible'):
        GitRequestBudget(second, policy={'cycle': 2028}, limit=1).reserve()
    assert json.loads(git(remote, 'show', BRANCH + ':budget.json'))['used'] == 1


def test_unreachable_remote_fails_closed(tmp_path):
    folder = tmp_path / 'checkout'
    folder.mkdir()
    git(folder, 'init')
    git(folder, 'remote', 'add', 'origin', str(tmp_path / 'missing.git'))
    with pytest.raises(RuntimeError, match='Cannot read'):
        GitRequestBudget(folder, policy={}).reserve()
