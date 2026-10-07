"""Durably reserve pilot requests in a tiny, separate Git branch before HTTP.

Only quota metadata is committed. Normal fast-forward pushes provide compare-and-
swap behavior: a concurrent reservation cannot overwrite a newer counter. No key,
database, candidate data, or article text is written to the branch.
"""
from __future__ import annotations
import json
import subprocess
from pathlib import Path
from .network import BudgetExceeded
from .util import dumps

BRANCH = 'refs/heads/midterm-pilot-budget'


class GitRequestBudget:
    def __init__(self, repository, *, policy, limit=20):
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError('GitHub pilot limit must be 1..20')
        self.repository = Path(repository)
        self.policy = json.loads(dumps(policy))
        self.limit = limit
        self.last_known = None

    def _git(self, *args, input=None, check=True):
        result = subprocess.run(['git', *args], cwd=self.repository, input=input,
                                text=True, capture_output=True)
        if check and result.returncode:
            # Remote URLs/credential helpers can appear in Git diagnostics. Do not log them.
            raise RuntimeError('Persistent GitHub budget operation failed; no provider request sent')
        return result

    def reserve(self):
        for _ in range(3):
            probe = self._git('ls-remote', '--exit-code', 'origin', BRANCH, check=False)
            if probe.returncode == 2:
                parent = None
                record = {'format': 'midterm-request-budget-v1', 'limit': self.limit,
                          'policy': self.policy, 'used': 0}
            elif probe.returncode == 0:
                self._git('fetch', '--no-tags', 'origin', BRANCH)
                parent = self._git('rev-parse', 'FETCH_HEAD').stdout.strip()
                record = json.loads(self._git('show', parent + ':budget.json').stdout)
                if (record.get('format') != 'midterm-request-budget-v1' or record.get('limit') != self.limit
                    or record.get('policy') != self.policy or type(record.get('used')) is not int
                    or not 0 <= record['used'] <= self.limit):
                    raise ValueError('Remote pilot budget is incompatible or corrupt; do not reset it')
            else:
                raise RuntimeError('Cannot read persistent GitHub budget; no provider request sent')
            self.last_known = record['used']
            if record['used'] >= self.limit:
                raise BudgetExceeded('This GitHub pilot has spent its total request allowance')
            record['used'] += 1
            blob = self._git('hash-object', '-w', '--stdin', input=dumps(record) + '\n').stdout.strip()
            tree = self._git('mktree', input=f'100644 blob {blob}\tbudget.json\n').stdout.strip()
            command = ['-c', 'user.name=github-actions[bot]', '-c',
                       'user.email=41898282+github-actions[bot]@users.noreply.github.com', 'commit-tree', tree]
            if parent: command += ['-p', parent]
            command += ['-m', f'Reserve provider request {record["used"]}/{self.limit}']
            commit = self._git(*command).stdout.strip()
            result = self._git('push', '--porcelain', 'origin', commit + ':' + BRANCH, check=False)
            if result.returncode == 0:
                self.last_known = record['used']
                return record['used']
            # No force push: reread on a race, fail closed on permission/network failure.
        raise RuntimeError('Unable to persist request reservation; no provider request sent')
