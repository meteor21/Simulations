"""Read-only, metadata-only public projection of an analyzed pilot checkpoint.

This is an explicit publication allowlist, not a serialization of reports or DB
rows. Search associations are not verified mentions, and absent scores stay NULL.
"""
from __future__ import annotations

import csv
import ipaddress
import json
import math
import re
import sqlite3
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .agents_store import AgentStore
from .store import read_only
from .util import dt, iso

SCOPES = ('national', 'state', 'metro', 'local', 'unknown')
RESOLUTIONS = {'exact_root_homepage_match', 'directory_incomplete', 'ambiguous', 'not_found',
               'budget_stop', 'error', 'access_blocked', 'not_requested'}
STATUSES = {'blocked', 'executed', 'executed_partial', 'offline_prepared', 'analyzed', 'analyzed_partial'}
PUBLIC_MESSAGES = {
    'Source panel incomplete; inspect source_resolution and collection_plan',
    'No reviewed candidate-specific sentiment annotations; scores remain missing',
    'Some candidate sentiment scores remain missing',
    'Source coverage remains incomplete; this analysis does not fill missing coverage',
    'Saved collection has blocked/error jobs; inspect the original collection report',
    'Collection has blocked/failed jobs; inspect queue and run.collection',
    'Persistent 20-request allowance reached; no further requests permitted for this pilot',
}
PROVENANCE_HOSTS = {'fec.gov', 'www.fec.gov', 'github.com', 'raw.githubusercontent.com',
                    'statesnewsroom.com', 'www.statesnewsroom.com', 'allsides.com', 'www.allsides.com'}


def _domain(value):
    if not isinstance(value, str):
        return None
    value = value.lower().removeprefix('www.')
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', value) or '.' not in value:
        return None
    if any(value == suffix or value.endswith('.' + suffix)
           for suffix in ('localhost', 'local', 'internal', 'invalid', 'test', 'onion')):
        return None
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    return None  # No literal IP addresses in public links, including public IPs.


def _public_url(value, allowed):
    """Allow HTTP(S) publisher/provenance hosts; discard credentials and queries."""
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 32 for c in value):
        return None
    try:
        parts = urlsplit(value)
        domain = _domain(parts.hostname)
        if (parts.scheme not in {'https', 'http'} or parts.username or parts.password
                or parts.port not in (None, 80, 443) or not domain
                or not any(domain == d or domain.endswith('.' + d) for d in allowed)):
            return None
        # Query strings and fragments can carry session identifiers or API keys.
        return urlunsplit((parts.scheme, parts.hostname.lower(), parts.path or '/', '', ''))
    except ValueError:
        return None


def _messages(report):
    result = []
    for key in ('blockers', 'warnings'):
        for message in report.get(key, []):
            public = message if message in PUBLIC_MESSAGES else 'Additional diagnostic withheld from public export'
            if public not in result:
                result.append(public)
    return result


def _score(value):
    return value if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 100 else None


def _geography(value):
    """Only reviewed geographic labels, never arbitrary provider metadata."""
    result = {}
    for key in ('city', 'metro', 'county', 'district', 'region'):
        item = value.get(key)
        if isinstance(item, str) and re.fullmatch(r"[\w .,'()-]{1,100}", item):
            result[key] = item
    if type(value.get('district_mapping_verified')) is bool:
        result['district_mapping_verified'] = value['district_mapping_verified']
    return result


def _counter(value):
    if type(value) is not int or not 0 <= value <= 20:
        raise ValueError('Missing or invalid saved 20-request accounting')
    return value


class _ReadView:
    def __init__(self, con):
        self.con = con

    def rows(self, sql, params=()):
        return [dict(row) for row in self.con.execute(sql, params)]


def build_dashboard_data(pilot_dir, *, source_repository, analysis_run_id, code_revision):
    """Build deterministic public data; perform no writes, network calls or analysis.

    Only dates in the original persisted collection window qualify. Stored feature
    values are included only at its exact cutoff and with reviewed selected-candidate
    labels. This does not upgrade retrospective analysis to a point-in-time forecast.
    """
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', source_repository):
        raise ValueError('Expected owner/repository')
    if not re.fullmatch(r'[1-9][0-9]*', str(analysis_run_id)):
        raise ValueError('Expected numeric analysis run ID')
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,80}', code_revision):
        raise ValueError('Invalid code revision')
    root = Path(pilot_dir)
    report = json.loads((root / 'analysis_report.json').read_text(encoding='utf-8'))
    original, current = report['original_pilot_report'], report['analysis']
    if report.get('provider_requests_made') != 0 or report.get('analysis_only') is not True:
        raise ValueError('Expected zero-request checkpoint analysis')
    if report.get('source_repository') != source_repository:
        raise ValueError('Source repository does not match retained analysis')
    with (root / 'selected_congressional_cohort.csv').open(newline='', encoding='utf-8-sig') as stream:
        roster = list(csv.DictReader(stream))
    ids = [r['candidate_id'] for r in roster]
    if not ids or len(ids) > 24 or len(set(ids)) != len(ids):
        raise ValueError('Expected 1 through 24 distinct selected congressional candidates')
    roster.sort(key=lambda r: r['candidate_id'])
    with closing(read_only(root / 'pilot.sqlite')) as con:
        con.row_factory = sqlite3.Row
        view = _ReadView(con)
        meta = dict(con.execute("SELECT key,value FROM cs_meta WHERE key IN ('pilot_request_policy','pilot_requests_used')"))
        saved = json.loads(meta['pilot_request_policy'])
        policy = saved['policy']
        if saved['limit'] != 20:
            raise ValueError('Expected original 20-request pilot policy')
        start, cutoff = dt(policy['start'], end_of_day=False), dt(policy['as_of'])
        if start >= cutoff:
            raise ValueError('Invalid original collection window')
        mode = 'retrospective'
        counters = [_counter(int(meta['pilot_requests_used']))]
        for record in (original, current):
            for field in ('http_attempts_total', 'github_requests_reserved'):
                if record.get(field) is not None:
                    counters.append(_counter(record[field]))
        used = max(counters)
        profiles = view.rows("SELECT * FROM sa_source_profiles WHERE status='reviewed' ORDER BY domain,profile_id")
        domains = {_domain(r['domain']) for r in profiles + view.rows('SELECT domain FROM cs_outlets')}
        domains.discard(None)
        provenance_hosts = domains | {_domain(d) for d in PROVENANCE_HOSTS}
        provenance_hosts.discard(None)
        placeholders = ','.join('?' for _ in ids)
        candidates = []
        feature_rows = current.get('run', {}).get('features', [])
        features = {r['candidate_id']: r for r in feature_rows if r.get('candidate_id') in ids}
        for row in roster:
            if row['office'] not in {'H', 'S'}:
                raise ValueError('Only selected congressional candidates can be published')
            if not con.execute('SELECT 1 FROM cs_candidates WHERE candidate_id=?', (row['candidate_id'],)).fetchone():
                raise ValueError('Selected candidate is absent from retained checkpoint')
            candidate = {key: row.get(key, '') for key in ('candidate_id', 'name', 'office', 'state', 'district',
                         'party', 'stage', 'election_id', 'known_at')}
            candidate.update(cycle=int(row['cycle']), roster_status=row.get('roster_status') or 'registry_only',
                             source_url=_public_url(row.get('source_url'), provenance_hosts),
                             features={'media_recency_score': None, 'national_score': None, 'subnational_score': None},
                             feature_provenance=None,
                             missingness=[], coverage=dict.fromkeys(SCOPES, 0), article_count=0, reviewed_annotations=0)
            candidates.append(candidate)
        by_id = {r['candidate_id']: r for r in candidates}
        rows = view.rows(f'''SELECT a.article_id,a.url,a.outlet,v.version_id,v.published_at,v.available_at,
            l.candidate_id FROM cs_articles a JOIN cs_versions v USING(article_id)
            JOIN cs_article_candidates l USING(article_id) WHERE l.candidate_id IN ({placeholders})
            AND v.published_at IS NOT NULL ORDER BY a.article_id,v.available_at DESC,v.version_id,l.candidate_id''', ids)
        articles = {}
        versions = {}
        eligible_label_pairs = set()
        for row in rows:
            published = dt(row['published_at'])
            if not start <= published <= cutoff:
                continue
            url = _public_url(row['url'], domains)
            if not url:
                continue
            eligible_label_pairs.add((row['version_id'], row['candidate_id']))
            aid = row['article_id']
            if aid not in articles:
                profile = AgentStore.profile_for(view, row['url'], row['published_at'], policy['as_of'], mode=mode)
                scope = profile['scope'] if profile else 'unknown'
                articles[aid] = {'article_id': aid, 'url': url, 'domain': _domain(urlsplit(url).hostname),
                    'published_at': iso(row['published_at']), 'scope': scope, 'candidate_ids': [],
                    'association_status': 'unreviewed_search_association',
                    'historical_scope_verified': bool(profile and profile['historical_scope_verified'])}
                versions[aid] = row['version_id']
            if row['version_id'] == versions[aid] and row['candidate_id'] not in articles[aid]['candidate_ids']:
                articles[aid]['candidate_ids'].append(row['candidate_id'])
        for aid, article in articles.items():
            article['candidate_ids'].sort()
            for cid in article['candidate_ids']:
                candidate = by_id[cid]
                candidate['article_count'] += 1
                candidate['coverage'][article['scope']] += 1
        for version, cid in sorted(eligible_label_pairs):
            by_id[cid]['reviewed_annotations'] += con.execute('''SELECT COUNT(*) FROM cs_annotations
                WHERE version_id=? AND candidate_id=? AND reviewed=1
                AND entity_status IN ('verified','exact_name_context')''', (version, cid)).fetchone()[0]
        for candidate in candidates:
            feature = features.get(candidate['candidate_id'], {})
            matching = bool(feature and iso(feature['as_of']) == iso(policy['as_of'])
                            and feature.get('mode') == mode and feature.get('reviewed_only') is True
                            and feature.get('state') == candidate['state']
                            and feature.get('cycle') == candidate['cycle'])
            lookbacks = set()
            if matching:
                # The report's numeric features do not contain their lookback.
                # Recover it only from an exactly matching persisted snapshot.
                # Never relabel a 731-day score as a one-month metadata count.
                for snapshot in view.rows('''SELECT features_json,config_json FROM sa_snapshots
                        WHERE candidate_id=? AND cycle=? AND as_of=? AND mode=?''',
                        (candidate['candidate_id'], candidate['cycle'], iso(policy['as_of']), mode)):
                    if json.loads(snapshot['features_json']) != feature:
                        continue
                    config = json.loads(snapshot['config_json'])
                    days = config.get('lookback_days')
                    if (type(days) is int and 1 <= days <= 100000 and config.get('mode') == mode
                            and config.get('reviewed_only') is True):
                        lookbacks.add(days)
            if len(lookbacks) == 1:
                days = next(iter(lookbacks))
                lower = cutoff - timedelta(days=days)
                candidate['feature_provenance'] = {'as_of': iso(policy['as_of']), 'state': candidate['state'],
                    'cycle': candidate['cycle'], 'mode': mode, 'lookback_days': days,
                    'lookback_start': lower.isoformat(timespec='seconds'),
                    'metadata_window_start': policy['start'], 'metadata_window_as_of': policy['as_of'],
                    'same_as_metadata_window': lower == start}
            if matching and candidate['feature_provenance'] and candidate['reviewed_annotations']:
                candidate['features'] = {
                    'media_recency_score': _score(feature.get('media_recency_score')),
                    'national_score': _score(feature.get('national', {}).get('score')),
                    'subnational_score': _score(feature.get('subnational', {}).get('score'))}
            if not candidate['article_count']:
                candidate['missingness'].append('no_article_metadata_in_original_window')
            if not candidate['reviewed_annotations']:
                candidate['missingness'].append('no_reviewed_candidate_sentiment')
            if not matching:
                candidate['missingness'].append('no_matching_reviewed_snapshot')
            elif candidate['feature_provenance'] is None:
                candidate['missingness'].append('feature_lookback_provenance_unavailable')
            if candidate['features']['media_recency_score'] is None:
                candidate['missingness'].append('sentiment_unavailable')
        requested = {}
        for row in original.get('source_resolution', []):
            domain = _domain(row.get('domain'))
            if domain:
                requested[domain] = row
        states = {r['state'] for r in candidates}
        sources = []
        for profile in profiles:
            domain = _domain(profile['domain'])
            covered = json.loads(profile['states_json'])
            if not domain or (domain not in requested and profile['scope'] != 'national' and not states.intersection(covered)):
                continue
            resolution = requested.get(domain, {})
            sources.append({'domain': domain, 'profile_id': profile['profile_id'], 'scope': profile['scope'],
                'states': covered, 'geography': _geography(json.loads(profile['geography_json'])),
                'url_prefix': urlsplit(profile['url_prefix']).path,
                'observed_at': profile['observed_at'], 'valid_from': profile['valid_from'], 'valid_to': profile['valid_to'],
                'evidence_url': _public_url(profile['evidence_url'], provenance_hosts),
                'resolution_status': resolution.get('status') if resolution.get('status') in RESOLUTIONS else 'not_requested',
                'source_id': resolution.get('source_id') if type(resolution.get('source_id')) is int else None})
        represented = {r['domain'] for r in sources}
        for domain, resolution in sorted(requested.items()):
            if domain not in represented:
                sources.append({'domain': domain, 'profile_id': None, 'scope': 'unknown', 'states': [], 'geography': {}, 'url_prefix': '',
                    'observed_at': None, 'valid_from': None, 'valid_to': None, 'evidence_url': None,
                    'resolution_status': resolution.get('status') if resolution.get('status') in RESOLUTIONS else 'error',
                    'source_id': resolution.get('source_id') if type(resolution.get('source_id')) is int else None})
        coverage = {scope: sum(r['scope'] == scope for r in articles.values()) for scope in SCOPES}
        collected = original.get('run', {}).get('collection', {})
        collection = {}
        for public, original_key in (('processed_jobs', 'processed'), ('blocked_jobs', 'blocked'),
                                     ('failed_jobs', 'errors'), ('processed_hits', 'processed_hits')):
            value = collected.get(original_key)
            collection[public] = value if type(value) is int and value >= 0 else None
        return {'schema_version': 1, 'dataset_kind': 'real',
            'provenance': {'source_repository': source_repository, 'source_run_id': int(report['source_run_id']),
                'analysis_run_id': int(analysis_run_id), 'code_revision': code_revision,
                'collection_code_revision': report.get('collection_source_commit')
                    if re.fullmatch(r'[A-Za-z0-9._-]{1,80}', str(report.get('collection_source_commit', ''))) else None},
            'window': {'start': policy['start'], 'as_of': policy['as_of'], 'cycle': policy['cycle'], 'mode': mode},
            'budget': {'limit': 20, 'used': used, 'remaining': 20-used, 'provider_requests_this_analysis': 0},
            'summary': {'selected_candidates': len(candidates), 'article_urls': len(articles),
                'candidate_article_links': sum(len(a['candidate_ids']) for a in articles.values()),
                'reviewed_annotations': sum(c['reviewed_annotations'] for c in candidates),
                'retrospective_scope_urls': sum(not a['historical_scope_verified'] for a in articles.values()),
                'candidates_with_scores': sum(c['features']['media_recency_score'] is not None for c in candidates)},
            'collection': collection,
            'checkpoint_counts': {'article_urls': con.execute('SELECT COUNT(*) FROM cs_articles').fetchone()[0],
                                  'candidate_article_links': con.execute('SELECT COUNT(*) FROM cs_article_candidates').fetchone()[0],
                                  'reviewed_annotations': con.execute('SELECT COUNT(*) FROM cs_annotations WHERE reviewed=1').fetchone()[0]},
            'count_scope': 'Summary and scope counts include only selected-cohort search associations with public publisher URLs and publication dates in the original collection window; checkpoint_counts describes the whole saved database.',
            'coverage_note': 'Candidate coverage counts describe source geography for saved search associations; they do not establish a verified mention, candidate-state relevance, or district readership. Feature lookback windows are reported separately from metadata counts.',
            'original_status': original.get('status') if original.get('status') in STATUSES else 'unknown',
            'current_status': current.get('status') if current.get('status') in STATUSES else 'unknown',
            'warnings': {'original': _messages(original), 'current': _messages(current), 'research': [
                'Media portrayal is not representative public opinion; survey favorability remains separate.',
                'Registrations are not verified contestants; search associations are not verified candidate mentions.',
                'Missing sentiment is unavailable, not neutral. Partisanship carries no sentiment-weight penalty.',
                'Retrospective reconstruction is not a point-in-time forecast; source coverage is incomplete.',
                'Public export contains article metadata only; original publisher text and review evidence are omitted.']},
            'coverage': coverage, 'candidates': candidates,
            'articles': sorted(articles.values(), key=lambda a: (a['published_at'], a['article_id'])),
            'sources': sorted(sources, key=lambda s: (s['domain'], s['profile_id'] or ''))}
