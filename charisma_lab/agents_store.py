"""Additive schema for the three-worker news-sentiment workflow.

No original election/funding tables are modified. Current outlet descriptions,
historical applicability and observation/availability dates are separate.
"""
from __future__ import annotations
import json
import math
from contextlib import closing
from urllib.parse import urlsplit
from .store import Store, read_only
from .util import dumps, digest, iso, now, host, finite_number, dt

SCHEMA = """
CREATE TABLE IF NOT EXISTS sa_source_profiles(
 profile_id TEXT PRIMARY KEY, domain TEXT NOT NULL, url_prefix TEXT NOT NULL DEFAULT '',
 name TEXT NOT NULL, scope TEXT NOT NULL, states_json TEXT NOT NULL,
 geography_json TEXT NOT NULL, source_kind TEXT NOT NULL, network_group TEXT NOT NULL,
 valid_from TEXT NOT NULL, valid_to TEXT, observed_at TEXT NOT NULL,
 evidence_url TEXT NOT NULL, status TEXT NOT NULL, notes TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS sa_article_candidate_reverse ON cs_article_candidates(candidate_id,article_id);
CREATE INDEX IF NOT EXISTS sa_version_time ON cs_versions(published_at);
CREATE INDEX IF NOT EXISTS sa_profile_lookup ON sa_source_profiles(domain,valid_from);
CREATE TABLE IF NOT EXISTS sa_source_coverage(
 domain TEXT NOT NULL, provider TEXT NOT NULL, first_story TEXT, last_story TEXT,
 checked_at TEXT NOT NULL, evidence_json TEXT NOT NULL,
 PRIMARY KEY(domain,provider));
CREATE TABLE IF NOT EXISTS sa_bias_assessments(
 assessment_id TEXT PRIMARY KEY, domain TEXT NOT NULL, provider TEXT NOT NULL,
 label TEXT NOT NULL, ordinal_index REAL, native_score REAL, native_scale TEXT NOT NULL,
 genre TEXT NOT NULL, valid_from TEXT NOT NULL, valid_to TEXT, available_at TEXT NOT NULL,
 method TEXT NOT NULL, status TEXT NOT NULL, confidence_label TEXT NOT NULL,
 sample_n INTEGER, evidence_url TEXT NOT NULL, license_note TEXT NOT NULL,
 metadata_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS sa_bias_lookup ON sa_bias_assessments(domain,valid_from,available_at);
CREATE TABLE IF NOT EXISTS sa_identity_links(
 candidate_id TEXT PRIMARY KEY REFERENCES cs_candidates(candidate_id), person_id TEXT NOT NULL,
 evidence_url TEXT NOT NULL, observed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sa_service_terms(
 term_id TEXT PRIMARY KEY, person_id TEXT NOT NULL, office TEXT NOT NULL,
 state TEXT NOT NULL, district TEXT NOT NULL, party TEXT NOT NULL,
 start_date TEXT NOT NULL, end_date TEXT, available_at TEXT NOT NULL, evidence_url TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS sa_terms_person ON sa_service_terms(person_id,start_date);
CREATE TABLE IF NOT EXISTS sa_plan_audit(
 audit_id TEXT PRIMARY KEY, run_label TEXT NOT NULL, cycle INTEGER, candidate_ids_json TEXT NOT NULL,
 scope TEXT NOT NULL, state TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
 provider TEXT NOT NULL, domains_json TEXT NOT NULL, job_ids_json TEXT NOT NULL,
 status TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sa_events(
 event_id INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at TEXT NOT NULL,
 agent TEXT NOT NULL, action TEXT NOT NULL, details_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sa_snapshots(
 snapshot_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, cycle INTEGER,
 as_of TEXT NOT NULL, mode TEXT NOT NULL, config_json TEXT NOT NULL,
 features_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sa_independent_bias_sample(
 sample_id TEXT PRIMARY KEY, domain TEXT NOT NULL, url TEXT NOT NULL,
 title TEXT NOT NULL, body_z BLOB NOT NULL, published_at TEXT NOT NULL,
 available_at TEXT NOT NULL, sampling_frame TEXT NOT NULL,
 rights_note TEXT NOT NULL, evidence_url TEXT NOT NULL);
"""

LABELS = {'Left':-2.,'Lean Left':-1.,'Center':0.,'Lean Right':1.,'Right':2.}
STATES = set('AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC'.split())

class AgentStore(Store):
    @staticmethod
    def _inspect_database(path):
        identity = Store._inspect_database(path)
        with closing(read_only(path)) as con:
            if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cs_meta'").fetchone():
                version = con.execute("SELECT value FROM cs_meta WHERE key='sentiment_agents_schema'").fetchone()
                if version and version[0] != '2':
                    raise ValueError('Incompatible sentiment agents schema; migrate before opening.')
        return identity

    def __init__(self,path):
        super().__init__(path)
        self.con.executescript(SCHEMA)
        self.con.execute("INSERT OR IGNORE INTO cs_meta VALUES('sentiment_agents_schema','2')")
        self.con.commit()

    def event(self,agent:str,action:str,**details):
        self.con.execute('INSERT INTO sa_events(occurred_at,agent,action,details_json) VALUES(?,?,?,?)',
                         (now(),agent,action,dumps(details)))
        self.con.commit()

    def source_profile(self,*,domain:str,name:str,scope:str,states=None,geography=None,
                       source_kind='news',network_group='',valid_from=None,valid_to=None,
                       observed_at=None,evidence_url:str,status='reviewed',url_prefix='',notes='',
                       media_cloud_id=None,permitted_fetch=False):
        domain=domain.lower().removeprefix('www.').strip()
        if host('https://'+domain)!=domain or '/' in domain or ':' in domain or '.' not in domain:
            raise ValueError('domain must be a bare, public outlet hostname')
        if scope not in {'national','state','metro','local','unknown'}:
            raise ValueError('Invalid geographic scope')
        states=list(dict.fromkeys(states or []))
        if not set(states)<=STATES: raise ValueError('Use two-letter U.S. state/DC codes')
        if scope in {'state','metro','local'} and not states:
            raise ValueError('Subnational sources require explicit covered states')
        if source_kind not in {'news','wire','opinion','official','campaign','advocacy','social','unknown'}:
            raise ValueError('Unsupported source kind')
        if status not in {'reviewed','proposed'}: raise ValueError('Invalid profile status')
        if not name or not evidence_url: raise ValueError('Source name and geographic evidence are required')
        if url_prefix:
            if host(url_prefix)!=domain or not url_prefix.startswith(('https://','http://')):
                raise ValueError('Edition prefix must belong to its domain')
            url_prefix=urlsplit(url_prefix).path or '/'
        obs=iso(observed_at or now()); start=iso(valid_from or obs)
        stop=iso(valid_to) if valid_to else None
        if stop and stop<=start: raise ValueError('Profile interval must have positive duration')
        # Distinct dated evidence is a new observation, including corrections to
        # applicability, geography or review status. Never silently discard it.
        values=(domain,url_prefix,name,scope,dumps(states),dumps(geography or {}),source_kind,
                network_group,start,stop,obs,evidence_url,status,notes)
        columns=('domain','url_prefix','name','scope','states_json','geography_json','source_kind',
                 'network_group','valid_from','valid_to','observed_at','evidence_url','status','notes')
        # v0.2 used a narrower digest. Preserve its ID for an exact existing
        # observation while allowing materially different evidence a new ID.
        existing=self.con.execute('SELECT profile_id FROM sa_source_profiles WHERE '+
            ' AND '.join(column+' IS ?' for column in columns)+' LIMIT 1',values).fetchone()
        pid=existing[0] if existing else digest(values)
        self.con.execute('INSERT OR IGNORE INTO sa_source_profiles VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
          (pid,*values))
        # Do not replace old permissions or existing verified provider IDs.
        self.con.execute('''INSERT INTO cs_outlets(domain,name,scope_state,media_cloud_id,orientation,
          orientation_source,permitted_fetch) VALUES(?,?,?,?,?,?,?) ON CONFLICT(domain) DO UPDATE SET
          media_cloud_id=COALESCE(cs_outlets.media_cloud_id,excluded.media_cloud_id)''',
          (domain,name,states[0] if len(states)==1 else 'US',media_cloud_id,'unclassified','',int(permitted_fetch)))
        self.con.commit(); return pid

    def bias(self,*,domain,provider,label,valid_from,available_at,evidence_url,
             valid_to=None,genre='online_news',native_score=None,native_scale='',
             method='sourced_provider_rating',status='reviewed',confidence_label='not_reported',
             sample_n=None,license_note='',metadata=None):
        if label not in {*LABELS,'Unknown','Mixed/Disputed'}: raise ValueError('Unknown bias label')
        if status not in {'reviewed','provisional'}: raise ValueError('Invalid assessment status')
        if genre not in {'online_news','opinion','all'}: raise ValueError('Invalid assessment genre')
        if not domain or not provider or not evidence_url: raise ValueError('Bias provenance is required')
        start,available=iso(valid_from),iso(available_at)
        stop=iso(valid_to) if valid_to else None
        if stop and stop<=start: raise ValueError('Invalid bias applicability interval')
        if native_score is not None:
            native_score=finite_number(native_score)
            if not native_scale: raise ValueError('Native numeric ratings require their actual scale')
        if sample_n is not None and int(sample_n)<1: raise ValueError('sample_n must be positive')
        meta=metadata or {}
        if status=='provisional' and method!='model_provisional':
            raise ValueError('Provisional estimates must identify their model-based method')
        domain=domain.strip().lower().removeprefix('www.')
        values=(domain,provider,label,LABELS.get(label),native_score,native_scale,genre,start,stop,available,
                method,status,confidence_label,sample_n,evidence_url,license_note,dumps(meta))
        columns=('domain','provider','label','ordinal_index','native_score','native_scale','genre',
                 'valid_from','valid_to','available_at','method','status','confidence_label','sample_n',
                 'evidence_url','license_note','metadata_json')
        existing=self.con.execute('SELECT assessment_id FROM sa_bias_assessments WHERE '+
            ' AND '.join(column+' IS ?' for column in columns)+' LIMIT 1',values).fetchone()
        aid=existing[0] if existing else digest(values)
        self.con.execute('INSERT OR IGNORE INTO sa_bias_assessments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (aid,*values))
        self.con.commit(); return aid

    def identity_link(self,candidate_id,person_id,evidence_url,observed_at=None):
        candidate=self.rows('SELECT person_id FROM cs_candidates WHERE candidate_id=?',(candidate_id,))
        if not candidate: raise ValueError('Unknown candidate ID: '+candidate_id)
        if candidate[0]['person_id'] and candidate[0]['person_id']!=person_id:
            raise ValueError('Identity conflict with candidate registry; manual review required')
        old=self.rows('SELECT person_id FROM sa_identity_links WHERE candidate_id=?',(candidate_id,))
        if old and old[0]['person_id']!=person_id: raise ValueError('Identity conflict; manual review required')
        if not person_id or not evidence_url: raise ValueError('Identity evidence required')
        self.con.execute('INSERT OR IGNORE INTO sa_identity_links VALUES(?,?,?,?)',
            (candidate_id,person_id,evidence_url,iso(observed_at or now())))
        self.con.commit()

    def term(self,*,person_id,office,state,district='',party='',start_date,end_date=None,
             available_at,evidence_url):
        if office not in {'H','S','P','VP','GOV','OTHER'}: raise ValueError('Invalid term office')
        if not person_id or not evidence_url: raise ValueError('Term evidence required')
        # Service dates are interval boundaries, not evidence-availability dates.
        # A date-only exclusive end excludes the whole named end date.
        a=dt(start_date,end_of_day=False).isoformat(timespec='seconds')
        b=dt(end_date,end_of_day=False).isoformat(timespec='seconds') if end_date else None
        if b and b<=a: raise ValueError('Term end must be later than start (exclusive end)')
        tid=digest([person_id,office,state,str(district),a,b,evidence_url])
        self.con.execute('INSERT OR IGNORE INTO sa_service_terms VALUES(?,?,?,?,?,?,?,?,?,?)',
            (tid,person_id,office,state,str(district),party,a,b,iso(available_at),evidence_url))
        self.con.commit(); return tid

    def profile_for(self,url,published_at,as_of,*,mode='strict'):
        if mode not in {'strict','retrospective'}: raise ValueError('Invalid time mode')
        hostname=host(url); path=urlsplit(url).path
        pub,cut=iso(published_at),iso(as_of)
        rows=self.rows("SELECT * FROM sa_source_profiles WHERE status='reviewed'")
        matching=[r for r in rows if (hostname==r['domain'] or hostname.endswith('.'+r['domain']))
                  and (not r['url_prefix'] or path==r['url_prefix'].rstrip('/')
                       or path.startswith(r['url_prefix'].rstrip('/')+'/'))]
        exact=[r for r in matching if r['valid_from']<=pub and (not r['valid_to'] or pub<r['valid_to'])
               and (mode=='retrospective' or r['observed_at']<=cut)]
        historical=True
        if not exact and mode=='retrospective':
            exact=matching; historical=False
        if not exact: return None
        r=max(exact,key=lambda x:(len(x['url_prefix']),len(x['domain']),x['valid_from'],
                                 x['observed_at'],x['profile_id']))
        r=dict(r); r['historical_scope_verified']=historical
        return r

    def rating_for(self,domain,published_at,as_of,*,provider=None,genre='online_news'):
        """No retrospective fallback: 2026 ratings never become 1990 ratings."""
        pub,cut=iso(published_at),iso(as_of)
        domain=domain.strip().lower().removeprefix('www.')
        rows=self.rows("""SELECT * FROM sa_bias_assessments WHERE domain=? AND status='reviewed'
          AND valid_from<=? AND (valid_to IS NULL OR ?<valid_to) AND available_at<=?
          AND genre IN (?, 'all') ORDER BY valid_from DESC,available_at DESC""",
          (domain,pub,pub,cut,genre))
        if provider: rows=[r for r in rows if r['provider']==provider]
        latest={}
        # Prefer a provider's genre-specific evidence over its general fallback.
        # Retain tied observations and disagreements instead of choosing by SQL
        # insertion order and dropping provenance.
        for r in rows:
            rank=(r['genre']==genre,r['valid_from'],r['available_at'])
            old=latest.get(r['provider'])
            if old is None or rank>old[0]: latest[r['provider']]=(rank,[r])
            elif rank==old[0]: old[1].append(r)
        if not latest: return {'label':'Unknown','ordinal_index':None,'assessments':[]}
        assessments=[r for _,items in latest.values() for r in items]
        labels={r['label'] for r in assessments}
        label=next(iter(labels)) if len(labels)==1 else 'Mixed/Disputed'
        return {'label':label,'ordinal_index':LABELS.get(label),'assessments':assessments}
