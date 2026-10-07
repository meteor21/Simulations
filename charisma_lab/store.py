from __future__ import annotations
import json
import sqlite3
import tempfile
import uuid
import zlib
from contextlib import closing
from pathlib import Path
from .util import canonical_url, digest, dumps, host, iso, normal, now

SCHEMA = """
CREATE TABLE IF NOT EXISTS cs_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cs_candidates(
 candidate_id TEXT PRIMARY KEY, name TEXT NOT NULL, aliases_json TEXT NOT NULL,
 known_at TEXT NOT NULL, source_url TEXT NOT NULL, person_id TEXT,
 identity_note TEXT NOT NULL DEFAULT 'office-specific ID; aliases need auditing');
CREATE TABLE IF NOT EXISTS cs_candidate_cycles(
 candidate_id TEXT NOT NULL REFERENCES cs_candidates(candidate_id), cycle INTEGER NOT NULL,
 office TEXT NOT NULL, state TEXT NOT NULL, district TEXT NOT NULL DEFAULT '', party TEXT NOT NULL,
 target_election_year INTEGER, roster_status TEXT NOT NULL DEFAULT 'registry_only',
 known_at TEXT NOT NULL, source_url TEXT NOT NULL,
 PRIMARY KEY(candidate_id,cycle,office,state,district));
CREATE TABLE IF NOT EXISTS cs_roster(
 candidate_id TEXT NOT NULL REFERENCES cs_candidates(candidate_id), election_id TEXT NOT NULL,
 cycle INTEGER NOT NULL, office TEXT NOT NULL, state TEXT NOT NULL, district TEXT NOT NULL,
 stage TEXT NOT NULL, known_at TEXT NOT NULL, source_url TEXT NOT NULL,
 PRIMARY KEY(candidate_id,election_id));
CREATE TABLE IF NOT EXISTS cs_outlets(
 domain TEXT PRIMARY KEY, name TEXT NOT NULL, scope_state TEXT NOT NULL DEFAULT 'US',
 media_cloud_id INTEGER, orientation TEXT NOT NULL DEFAULT 'unclassified',
 orientation_source TEXT NOT NULL DEFAULT '', permitted_fetch INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS cs_jobs(
 job_id TEXT PRIMARY KEY, provider TEXT NOT NULL, payload_json TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
 error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS cs_jobs_status ON cs_jobs(provider,status);
CREATE TABLE IF NOT EXISTS cs_articles(
 article_id TEXT PRIMARY KEY, url TEXT NOT NULL UNIQUE, outlet TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cs_versions(
 version_id TEXT PRIMARY KEY, article_id TEXT NOT NULL REFERENCES cs_articles(article_id),
 title TEXT NOT NULL, body_z BLOB, published_at TEXT, indexed_at TEXT,
 retrieved_at TEXT NOT NULL, available_at TEXT NOT NULL, availability_basis TEXT NOT NULL,
 archive_evidence_url TEXT NOT NULL DEFAULT '', content_hash TEXT NOT NULL,
 rights_note TEXT NOT NULL DEFAULT '', metadata_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS cs_versions_article ON cs_versions(article_id,available_at);
CREATE TABLE IF NOT EXISTS cs_article_candidates(
 article_id TEXT NOT NULL REFERENCES cs_articles(article_id),
 candidate_id TEXT NOT NULL REFERENCES cs_candidates(candidate_id),
 PRIMARY KEY(article_id,candidate_id));
CREATE TABLE IF NOT EXISTS cs_annotations(
 version_id TEXT NOT NULL REFERENCES cs_versions(version_id),
 candidate_id TEXT NOT NULL REFERENCES cs_candidates(candidate_id), model_id TEXT NOT NULL,
 sentiment REAL NOT NULL CHECK(sentiment BETWEEN -1 AND 1), confidence REAL NOT NULL,
 entity_status TEXT NOT NULL, reviewed INTEGER NOT NULL DEFAULT 0,
 evidence TEXT NOT NULL, diagnostics_json TEXT NOT NULL, annotated_at TEXT NOT NULL,
 PRIMARY KEY(version_id,candidate_id,model_id));
CREATE INDEX IF NOT EXISTS cs_annotations_candidate ON cs_annotations(candidate_id);
CREATE TABLE IF NOT EXISTS cs_surveys(
 observation_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES cs_candidates(candidate_id),
 wave_id TEXT NOT NULL, pollster TEXT NOT NULL, geography TEXT NOT NULL, population TEXT NOT NULL,
 metric TEXT NOT NULL, field_end TEXT NOT NULL, available_at TEXT NOT NULL, source_url TEXT NOT NULL,
 favorable REAL NOT NULL, unfavorable REAL NOT NULL, sample_size INTEGER NOT NULL,
 dont_know REAL, metadata_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS cs_surveys_candidate ON cs_surveys(candidate_id,available_at);
CREATE TABLE IF NOT EXISTS cs_pedigree(
 observation_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES cs_candidates(candidate_id),
 effective_at TEXT NOT NULL, available_at TEXT NOT NULL, years_elected REAL NOT NULL,
 general_wins INTEGER NOT NULL, general_contests INTEGER NOT NULL,
 mean_outperformance_pp REAL, baseline_train_end TEXT,
 history_complete INTEGER NOT NULL, source_url TEXT NOT NULL, metadata_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS cs_pedigree_candidate ON cs_pedigree(candidate_id,effective_at,available_at);
CREATE TABLE IF NOT EXISTS cs_scores(
 snapshot_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, election_id TEXT NOT NULL,
 as_of TEXT NOT NULL, mode TEXT NOT NULL, geography TEXT NOT NULL, population TEXT NOT NULL,
 favorability_score REAL, recency_score REAL, pedigree_score REAL, charisma_score REAL,
 flags_json TEXT NOT NULL, details_json TEXT NOT NULL, config_json TEXT NOT NULL,
 created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS cs_scores_time ON cs_scores(candidate_id,as_of);
CREATE TABLE IF NOT EXISTS cs_fetch_log(
 attempt_id INTEGER PRIMARY KEY AUTOINCREMENT, article_id TEXT NOT NULL,
 attempted_at TEXT NOT NULL, status TEXT NOT NULL, message TEXT NOT NULL);
"""

class Store:
    """One local SQLite writer. Use backup() for Drive; never share a mounted-Drive live DB."""
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        # Inspect existing files read-only before WAL mode or any schema DDL.
        if self.path.exists():
            self._inspect_database(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.path, timeout=30)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys=ON")
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(SCHEMA)
        version = self.con.execute("SELECT value FROM cs_meta WHERE key='schema_version'").fetchone()
        if version and version[0] != '1':
            raise ValueError("Incompatible charisma schema; migrate before opening.")
        self.con.execute("INSERT OR IGNORE INTO cs_meta VALUES('schema_version','1')")
        self.con.execute("INSERT OR IGNORE INTO cs_meta VALUES('database_id',?)", (str(uuid.uuid4()),))
        self.con.commit()

    @staticmethod
    def _inspect_database(path):
        """Only dedicated project databases may be opened for writing."""
        with closing(read_only(path)) as con:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not tables:
                return None
            if 'cs_meta' not in tables or any(not t.startswith(('cs_', 'sa_', 'sqlite_')) for t in tables):
                raise ValueError('Existing database is not a dedicated sentiment database; use a new path.')
            version = con.execute("SELECT value FROM cs_meta WHERE key='schema_version'").fetchone()
            if not version or version[0] != '1':
                raise ValueError('Incompatible charisma schema; migrate before opening.')
            identity = con.execute("SELECT value FROM cs_meta WHERE key='database_id'").fetchone()
            return identity[0] if identity else None

    def close(self):
        self.con.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def rows(self, sql, params=()):
        return [dict(r) for r in self.con.execute(sql, params)]

    def backup(self, path):
        target = Path(path).expanduser().resolve()
        if target == self.path:
            raise ValueError("Backup destination cannot be the live database.")
        identity = self.con.execute("SELECT value FROM cs_meta WHERE key='database_id'").fetchone()[0]
        def verify_destination():
            if target.exists() and self._inspect_database(target) != identity:
                raise ValueError('Backup destination belongs to another database or has no lineage; use a new path.')
            if any(Path(str(target) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
                raise ValueError('Backup destination appears active; close its database connections first.')
        verify_destination()
        target.parent.mkdir(parents=True, exist_ok=True)
        self.con.commit()
        with tempfile.NamedTemporaryFile(prefix=target.name + '.', suffix='.tmp', dir=target.parent, delete=False) as f:
            temporary = Path(f.name)
        try:
            with closing(sqlite3.connect(temporary)) as dest:
                self.con.backup(dest)
                dest.execute('PRAGMA journal_mode=DELETE')
            verify_destination()
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def candidate(self, candidate_id, name, aliases=None, known_at=None, source_url='', person_id=None):
        if not candidate_id or not name.strip() or not source_url:
            raise ValueError("candidate_id, name and provenance source_url are required")
        aliases = list(dict.fromkeys([name] + (aliases or [])))
        if any(len(normal(x).split()) < 2 for x in aliases):
            raise ValueError("Use full names, not surname-only aliases.")
        known_at = iso(known_at or now())
        prior = self.con.execute('SELECT person_id FROM cs_candidates WHERE candidate_id=?', (candidate_id,)).fetchone()
        if prior and prior[0] and person_id and prior[0] != person_id:
            raise ValueError('Conflicting person_id requires an explicit reviewed identity correction.')
        self.con.execute("""INSERT INTO cs_candidates
        (candidate_id,name,aliases_json,known_at,source_url,person_id) VALUES(?,?,?,?,?,?)
        ON CONFLICT(candidate_id) DO UPDATE SET
          person_id=COALESCE(excluded.person_id,cs_candidates.person_id)
        """, (candidate_id,name,dumps(aliases),known_at,source_url,person_id))
        # Re-importing a later cycle must not overwrite historical identity metadata.
        self.con.commit()

    def article(self, *, url, title, candidate_ids, body='', published_at=None, indexed_at=None,
                retrieved_at=None, available_at=None, availability_basis='retrieved_version',
                archive_evidence_url='', rights_note='', metadata=None):
        url = canonical_url(url)
        retrieved_at = iso(retrieved_at or now())
        available_at = iso(available_at or retrieved_at)
        if available_at < retrieved_at:
            if availability_basis != 'verified_archive_version' or not archive_evidence_url:
                raise ValueError("Backdating a content version requires verified archive evidence.")
        if availability_basis not in {'retrieved_version','verified_archive_version','synthetic_fixture'}:
            raise ValueError("Unsupported availability basis")
        article_id = digest(url)
        content_hash = digest(normal(body if len(body) >= 100 else title))
        # Version identity includes the evidence date: live retrieval cannot replace an archive version.
        version_id = digest([article_id,title,body,available_at,archive_evidence_url])
        # Attribute explicitly configured subdomains to their panel outlet.
        hostname = host(url)
        matches = [r[0] for r in self.con.execute('SELECT domain FROM cs_outlets')
                   if hostname == r[0] or hostname.endswith('.' + r[0])]
        outlet = max(matches, key=len) if matches else hostname
        self.con.execute("INSERT OR IGNORE INTO cs_articles VALUES(?,?,?)", (article_id,url,outlet))
        self.con.execute("INSERT OR IGNORE INTO cs_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (version_id,article_id,title,zlib.compress(body.encode()) if body else None,
             iso(published_at) if published_at else None, iso(indexed_at) if indexed_at else None,
             retrieved_at,available_at,availability_basis,archive_evidence_url,content_hash,
             rights_note,dumps(metadata or {})))
        self.con.executemany("INSERT OR IGNORE INTO cs_article_candidates VALUES(?,?)",
                             [(article_id,c) for c in candidate_ids])
        return version_id

    def annotation(self, version_id, candidate_id, sentiment, *, model_id='human:v1',
                   confidence=1.0, entity_status='verified', reviewed=True, evidence='', diagnostics=None,
                   annotated_at=None, annotation_basis='created_now', annotation_evidence_url=''):
        from .util import finite_number
        sentiment = finite_number(sentiment,-1,1)
        confidence = finite_number(confidence,0,1)
        if entity_status not in {'verified','exact_name_context','needs_review','no_match'}:
            raise ValueError("Unknown entity_status")
        if not evidence:
            raise ValueError("Annotation requires source-text evidence.")
        if annotation_basis not in {'created_now','verified_annotation_record','synthetic_fixture'}:
            raise ValueError('Unsupported annotation availability basis.')
        created_at=now()
        annotated_at=iso(annotated_at or created_at)
        if annotated_at<created_at and (annotation_basis=='created_now' or not annotation_evidence_url):
            raise ValueError('Backdating an annotation requires dated annotation-record evidence or an explicit synthetic fixture.')
        diagnostics=dict(diagnostics or {},annotation_basis=annotation_basis,
                         annotation_evidence_url=annotation_evidence_url)
        self.con.execute("INSERT OR REPLACE INTO cs_annotations VALUES(?,?,?,?,?,?,?,?,?,?)",
            (version_id,candidate_id,model_id,sentiment,confidence,entity_status,int(reviewed),
             evidence,dumps(diagnostics),annotated_at))

    def enqueue(self, provider, payload):
        job_id = digest([provider,payload])
        t = now()
        self.con.execute("INSERT OR IGNORE INTO cs_jobs VALUES(?,?,?,'pending',0,NULL,?,?)",
                         (job_id,provider,dumps(payload),t,t))
        return job_id

    def reset_interrupted(self):
        # Only call after confirming no other runner is active on this database.
        self.con.execute("UPDATE cs_jobs SET status='pending',updated_at=? WHERE status='running'",(now(),))
        self.con.commit()

    def status(self):
        tables = ['cs_candidates','cs_candidate_cycles','cs_roster','cs_articles','cs_versions',
                  'cs_annotations','cs_surveys','cs_pedigree','cs_scores']
        return {'counts':{t:self.con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in tables},
                'jobs':self.rows('SELECT provider,status,COUNT(*) AS n FROM cs_jobs GROUP BY provider,status')}

def read_only(path):
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Database does not exist: {p}")
    return sqlite3.connect(p.as_uri() + '?mode=ro', uri=True)

def unpack_body(row) -> str:
    return zlib.decompress(row['body_z']).decode() if row['body_z'] else ''
