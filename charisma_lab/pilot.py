"""Opt-in 24-candidate Media Cloud pilot with a durable 20-attempt ceiling.

The budget includes failed attempts, retries, FEC downloads and source lookups.
No network access happens when preparing an offline plan or checking credentials.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from itertools import zip_longest
from pathlib import Path

from .agents import RunBudget, SentimentWorkflow
from .agents_analysis import FeatureConfig
from .agents_collect import select_cohort
from .agents_sources import download_fec_cycles, import_bias, import_profiles
from .agents_store import AgentStore
from .importers import FecAcquisitionError, import_fec_zip, import_funding, import_candidates, import_roster
from .network import AccessBlocked, BudgetExceeded, HttpClient
from .util import dumps, iso, now, dt


class RequestLedger:
    """Atomically reserve each HTTP attempt before sending, surviving process restarts.

    A failed/crashed attempt remains charged conservatively. Never reset this ledger
    to resume the same pilot. Independent processes cannot exceed its SQLite limit.
    """
    def __init__(self, store, limit=20, *, policy=None):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
            raise ValueError('Pilot request limit must be an integer from 1 through 20')
        self.store = store
        self.limit = limit
        record = dumps({'limit': limit, 'policy': policy or {}})
        with store.con:
            existing = store.con.execute("SELECT value FROM cs_meta WHERE key='pilot_request_policy'").fetchone()
            store.con.execute("INSERT OR IGNORE INTO cs_meta VALUES('pilot_request_policy',?)", (record,))
            saved = store.con.execute("SELECT value FROM cs_meta WHERE key='pilot_request_policy'").fetchone()[0]
            if saved != record:
                raise ValueError('Existing pilot policy differs; do not reset or increase its budget')
            if not existing:
                store.con.execute("INSERT OR IGNORE INTO cs_meta VALUES('pilot_requests_used','0')")
            self.used  # Fail closed if a persisted counter is absent or corrupted.

    @property
    def used(self):
        row = self.store.con.execute("SELECT value FROM cs_meta WHERE key='pilot_requests_used'").fetchone()
        if not row or not str(row[0]).isascii() or not str(row[0]).isdecimal() or not 0 <= int(row[0]) <= self.limit:
            raise ValueError('Pilot counter missing or corrupt; do not reset it to obtain more requests')
        return int(row[0])

    def reserve(self):
        with self.store.con:
            self.used
            result = self.store.con.execute("""UPDATE cs_meta SET value=CAST(value AS INTEGER)+1
                WHERE key='pilot_requests_used' AND CAST(value AS INTEGER) < ?""", (self.limit,))
            if result.rowcount != 1:
                raise BudgetExceeded('The persistent pilot request budget is exhausted; no request sent')


ROSTER_COLUMNS = ['candidate_id', 'name', 'cycle', 'office', 'state', 'district', 'party',
                  'election_id', 'stage', 'roster_status', 'target_election_year', 'known_at', 'source_url']


def export_roster(cohort, path):
    with Path(path).open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=ROSTER_COLUMNS, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(cohort)


def prepare_pilot(store, output, *, cycle=2026, start='2026-09-01', as_of='2026-10-06', roster_only=False):
    """Export actual observed candidates only; never substitute synthetic people."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if cycle < 1990 or cycle % 2:
        raise ValueError('Choose an even congressional cycle from 1990 onward')
    if dt(start, end_of_day=False) >= dt(as_of):
        raise ValueError('Pilot start must precede cutoff')
    rows = select_cohort(store, cycles=[cycle], roster_only=roster_only, max_candidates=None)
    cohort = []
    seen = set()
    for row in rows:
        if row['candidate_id'] not in seen:
            cohort.append(row)
            seen.add(row['candidate_id'])
        if len(cohort) == 24:
            break
    export_roster(cohort, output / 'selected_congressional_cohort.csv')
    # One search target per candidate does not erase that candidate's other races.
    export_roster([r for r in rows if r['candidate_id'] in seen],
                  output / 'selected_contest_memberships.csv')
    plan = SentimentWorkflow(store).collector.plan_campaign(
        cohort, start, as_of, dry_run=True, max_initial_jobs=1000) if cohort else []
    result = {'cycle': cycle, 'start': start, 'as_of': as_of, 'mode': 'retrospective',
              'required_candidates': 24, 'selected_candidates': len(cohort),
              'membership': 'documented_contest' if roster_only else 'registration_discovery_only',
              'status': 'prepared' if len(cohort) == 24 else 'blocked_missing_candidate_registry',
              'max_total_http_attempts': 20, 'plan': plan,
              'warning': 'Media portrayal is not survey favorability. Missing is not neutral. '
                         'This machinery pilot is not representative or forecast-ready.'}
    (output / 'pilot_plan.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return cohort, result


def run_pilot(output, *, run_network=False, download_fec=False, funding_db=None, fec_zip=None,
              candidates=None, roster=None, cycle=2026, start='2026-09-01', as_of='2026-10-06', github_budget=False):
    output = Path(output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    policy = {'cycle': cycle, 'start': start, 'as_of': as_of, 'provider': 'mediacloud',
              'candidate_limit': 24, 'roster_only': bool(roster)}
    if iso(as_of) > now():
        raise ValueError('Live/offline pilot cutoff cannot be in the future')
    with AgentStore(output / 'pilot.sqlite') as store:
        ledger = RequestLedger(store, policy=policy)
        root = Path(__file__).resolve().parents[1]
        import_profiles(store, root / 'data/source_profiles.csv')
        import_bias(store, root / 'data/source_bias_seed.csv')
        if funding_db:
            import_funding(store, funding_db, cycles=[cycle])
        if fec_zip:
            import_fec_zip(store, fec_zip, cycle)
        if candidates:
            import_candidates(store, candidates)
        if roster:
            import_roster(store, roster)
        # Check presence only. Never write a credential or exception text to reports.
        token = os.environ.get('MEDIACLOUD_API_KEY')
        report = {'started_at': now(), 'network_requested': run_network,
                  'credential_present': bool(token), 'http_attempts_before': ledger.used,
                  'provider': 'mediacloud', 'limits': {'candidates': 24, 'total_requests': 20},
                  'blockers': []}
        if github_budget:
            from .github_budget import GitRequestBudget
            remote_budget = GitRequestBudget(root, policy=policy)
            def reserve():
                ledger.reserve()
                remote_budget.reserve()
        else:
            reserve = ledger.reserve
        client = HttpClient(max_requests=20, before_request=reserve)
        report['persistent_github_budget'] = github_budget
        if run_network and not token:
            report['blockers'].append('MEDIACLOUD_API_KEY is absent; configure it securely for search.mediacloud.org')
        if run_network and token and download_fec and not store.rows(
                "SELECT 1 FROM cs_candidate_cycles WHERE cycle=? AND office IN ('H','S') LIMIT 1", (cycle,)):
            try:
                report['fec'] = download_fec_cycles(store, client, [cycle], output / 'downloads')
            except FecAcquisitionError as exc:
                report['fec_error'] = exc.details
                report['blockers'].append('FEC acquisition failed: ' + exc.details['stage'] + '/' + exc.details['reason'])
            except Exception as exc:
                report['blockers'].append('FEC acquisition failed: ' + type(exc).__name__)
        cohort, plan = prepare_pilot(store, output, cycle=cycle, start=start, as_of=as_of, roster_only=bool(roster))
        if len(cohort) != 24:
            report['blockers'].append(f'Need 24 sourced congressional candidates; available: {len(cohort)}')
        cohort_signature = dumps(cohort)
        saved = store.rows("SELECT value FROM cs_meta WHERE key='pilot_cohort'")
        if ledger.used and saved and saved[0]['value'] != cohort_signature:
            report['blockers'].append('Candidate roster changed after requests were charged; resume the original cohort')
        if run_network and not report['blockers']:
            with store.con:
                store.con.execute("INSERT OR IGNORE INTO cs_meta VALUES('pilot_cohort',?)", (cohort_signature,))
            workflow = SentimentWorkflow(store)
            national = list(dict.fromkeys(d for p in plan['plan'] if p['scope'] == 'national' for d in p['detail']['selected_domains']))
            local = list(dict.fromkeys(d for p in plan['plan'] if p['scope'] == 'subnational' for d in p['detail']['selected_domains']))
            priority = [d for pair in zip_longest(national, local) for d in pair if d]
            try:
                report['source_resolution'] = workflow.sources.resolve(client, token, max_sources=6, max_pages=1, domains=priority)
                denied = next((r['http_status'] for r in report['source_resolution']
                               if r.get('http_status') in {401, 403}), None)
                if denied:
                    raise AccessBlocked('Media Cloud source lookup denied; collection was not started.',
                                        http_status=denied, reason='access_denied')
                report['collection_plan'] = workflow.collector.plan_campaign(
                    cohort, start, as_of, run_label='bounded-pilot', max_initial_jobs=1000)
                report['run'] = workflow.run(cohort, as_of, run_network=True, token=token,
                    client_override=client, fetch=False, feature_config=FeatureConfig(mode='retrospective', reviewed_only=True),
                    budget=RunBudget(max_requests=20, max_search_jobs=14, max_fetch_articles=0, max_annotation_pairs=0))
                collection = report['run'].get('collection', {})
                if collection.get('blocked') or collection.get('errors'):
                    report['blockers'].append('Collection has blocked/failed jobs; inspect queue and run.collection')
                if ledger.used >= ledger.limit:
                    report['blockers'].append('Persistent 20-request allowance reached; no further requests permitted for this pilot')
                if any(p['status'] in {'blocked_unresolved_source_ids', 'partial_source_resolution', 'no_source_panel'}
                       for p in report['collection_plan']):
                    report['blockers'].append('Source panel incomplete; inspect source_resolution and collection_plan')
            except AccessBlocked as exc:
                detail = 'Live operation blocked: AccessBlocked'
                if exc.http_status is not None:
                    detail += f' (HTTP {exc.http_status}); verify provider API access'
                report['blockers'].append(detail)
            except Exception as exc:
                report['blockers'].append('Live operation stopped: ' + type(exc).__name__)
        report['status'] = 'blocked' if report['blockers'] else ('executed' if run_network else 'offline_prepared')
        report['selected_candidates'] = len(cohort)
        report['observations'] = {
            'unique_article_urls': store.rows('SELECT COUNT(*) AS n FROM cs_articles')[0]['n'],
            'candidate_annotations': store.rows('SELECT COUNT(*) AS n FROM cs_annotations')[0]['n'],
        }
        report['http_attempts_total'] = ledger.used
        report['http_attempts_this_run'] = ledger.used - report['http_attempts_before']
        report['provider_attempts_sent_this_run'] = client.requests_used
        if github_budget:
            report['github_requests_reserved'] = remote_budget.last_known
            report['http_attempts_total'] = max(ledger.used, remote_budget.last_known or 0)
        report['finished_at'] = now()
        workflow = SentimentWorkflow(store)
        report['queue'] = workflow.collector.queue_status()
        workflow.export(output / 'exports')
        (output / 'pilot_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='Dedicated pilot folder; reuse to resume the same 20-request budget')
    parser.add_argument('--run-network', action='store_true')
    parser.add_argument('--download-fec', action='store_true', help='One shared-budget official registration ZIP; needs --run-network and provider credential')
    parser.add_argument('--github-budget', action='store_true', help='Reserve every request on the persistent midterm-pilot-budget Git branch before sending')
    parser.add_argument('--funding-db', type=Path, help='Existing federal_candidate_cycle database, opened read-only')
    parser.add_argument('--fec-zip', type=Path, help='Previously obtained official candidate master ZIP')
    parser.add_argument('--candidates', type=Path, help='Explicit sourced candidate identities; pair with --roster')
    parser.add_argument('--roster', type=Path, help='Sourced contest memberships, including losing contestants')
    parser.add_argument('--cycle', type=int, default=2026)
    parser.add_argument('--start', default='2026-09-01')
    parser.add_argument('--as-of', default='2026-10-06')
    report = run_pilot(**vars(parser.parse_args()))
    print(json.dumps(report, indent=2))
    if os.environ.get('GITHUB_ACTIONS') == 'true' and report.get('fec_error'):
        print('::error title=FEC acquisition failed::' + json.dumps(report['fec_error'], sort_keys=True))
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        observations = report.get('observations', {})
        print('::notice title=Bounded pilot result::' + json.dumps({
            'status': report.get('status'), 'selected_candidates': report.get('selected_candidates', 0),
            'http_attempts_total': report.get('http_attempts_total', 0),
            'unique_article_urls': observations.get('unique_article_urls', 0),
            'candidate_annotations': observations.get('candidate_annotations', 0)}, sort_keys=True))
        for result in report.get('source_resolution', []):
            if result.get('http_status') in {401, 403}:
                print('::error title=Media Cloud access denied::HTTP ' + str(result['http_status']) +
                      '; source lookup stopped. Verify the provider key and account API access.')
    return 2 if report['blockers'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
