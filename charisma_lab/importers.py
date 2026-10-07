"""Explicit data contracts; no guessing a source table or silently fabricating observations."""
from __future__ import annotations
import csv
import io
import json
import re
import zipfile
from contextlib import closing
from pathlib import Path
from .store import Store, read_only
from .util import digest, dumps, finite_number, iso, now


def display_name(name: str) -> str:
    """FEC LAST, FIRST MIDDLE -> First Middle Last; no guessed nicknames or surname-only aliases."""
    name = re.sub(r'\s+', ' ', name.strip())
    if ',' in name:
        last, rest = name.split(',',1)
        name = f'{rest.strip()} {last.strip()}'
    return name.title() if name.isupper() else name


def import_funding(store: Store, path: str | Path, cycles=None) -> int:
    """Reuse the user's actual federal_candidate_cycle schema, read-only; finance != election roster."""
    required = {'candidate_id','candidate_name','finance_cycle','office','state','district','party'}
    n = 0
    with closing(read_only(path)) as con:
        columns = {r[1] for r in con.execute('PRAGMA table_info(federal_candidate_cycle)')}
        if not required <= columns:
            tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            raise ValueError(f'Missing federal_candidate_cycle columns {sorted(required-columns)}. '
                             f'Available tables: {tables}')
        fields = sorted(required)
        sql = 'SELECT DISTINCT ' + ','.join(fields) + ' FROM federal_candidate_cycle'
        params = []
        if cycles:
            sql += ' WHERE finance_cycle IN (' + ','.join('?' for _ in cycles) + ')'
            params = [int(y) for y in cycles]
        retrieved = now()
        source = Path(path).resolve().as_uri() + '#federal_candidate_cycle'
        for values in con.execute(sql,params):
            r = dict(zip(fields,values))
            if not r['candidate_id'] or not r['candidate_name']:
                continue
            name = display_name(r['candidate_name'])
            if len(name.split()) < 2:
                continue
            store.candidate(r['candidate_id'],name,known_at=retrieved,source_url=source)
            office = {'HOUSE':'H','SENATE':'S','PRESIDENT':'P','PRESIDENTIAL':'P'}.get(
                str(r['office']).upper(),str(r['office']).upper())
            store.con.execute('INSERT OR IGNORE INTO cs_candidate_cycles VALUES(?,?,?,?,?,?,?,?,?,?)',
                (r['candidate_id'],int(r['finance_cycle']),office,r['state'] or 'US',
                 str(r['district'] or ''),r['party'] or '',None,'registry_only',retrieved,source))
            n += 1
    store.con.commit()
    return n


def import_fec_zip(store: Store, path, cycle: int) -> int:
    """Read FEC candidate-master ZIP, excluding addresses. IDs are office-specific, not person IDs."""
    if cycle % 2 or not 1976 <= cycle <= 2100:
        raise ValueError('Supply an even FEC finance-cycle year.')
    source = f'https://www.fec.gov/files/bulk-downloads/{cycle}/cn{cycle % 100:02d}.zip'
    retrieved = now()
    n = 0
    with zipfile.ZipFile(path) as z:
        members = [i for i in z.infolist() if Path(i.filename).name.lower() == 'cn.txt']
        if len(members) != 1 or members[0].file_size > 300_000_000:
            raise ValueError('Expected one reasonably sized cn.txt in the official ZIP.')
        with z.open(members[0]) as raw, io.TextIOWrapper(raw,encoding='utf-8-sig',errors='replace') as text:
            for r in csv.reader(text,delimiter='|'):
                if len(r) != 15:
                    raise ValueError('FEC format changed: expected 15 fields, including unused addresses.')
                cid,name,party,year,state,office,district = r[:7]
                name = display_name(name)
                if not cid or len(name.split()) < 2:
                    continue
                store.candidate(cid,name,known_at=retrieved,source_url=source)
                store.con.execute('INSERT OR IGNORE INTO cs_candidate_cycles VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (cid,cycle,office,state,district,party,int(year) if year.isdigit() else None,
                     'registry_only',retrieved,source))
                n += 1
    store.con.commit()
    return n


def read_csv(path):
    with open(path,newline='',encoding='utf-8-sig') as f:
        yield from csv.DictReader(f)


def require(row, fields):
    missing = [x for x in fields if row.get(x) in (None,'')]
    if missing:
        raise ValueError(f'Missing required columns/values: {missing}')


def import_candidates(store,path):
    count=0
    for r in read_csv(path):
        require(r,['candidate_id','name','known_at','source_url'])
        store.candidate(r['candidate_id'],r['name'],json.loads(r.get('aliases_json') or '[]'),
                        r['known_at'],r['source_url'],r.get('person_id') or None)
        count+=1
    return count


def import_aliases(store,path):
    """Review nicknames/cross-office links explicitly; never auto-merge equal surnames."""
    n=0
    for r in read_csv(path):
        require(r,['candidate_id','aliases_json','source_url'])
        found=store.rows('SELECT * FROM cs_candidates WHERE candidate_id=?',(r['candidate_id'],))
        if not found: raise ValueError('Unknown candidate ID: '+r['candidate_id'])
        person_id=r.get('person_id') or None
        if person_id:
            known={found[0]['person_id']} if found[0]['person_id'] else set()
            if store.rows("SELECT name FROM sqlite_master WHERE type='table' AND name='sa_identity_links'"):
                known.update(x['person_id'] for x in store.rows(
                    'SELECT person_id FROM sa_identity_links WHERE candidate_id=?',(r['candidate_id'],)))
            if known and known!={person_id}:
                raise ValueError('Identity conflict; manual review required')
        aliases=json.loads(r['aliases_json'])
        if not isinstance(aliases,list) or any(not isinstance(a,str) or len(a.split())<2 for a in aliases):
            raise ValueError('aliases_json must be a list of full-name strings')
        aliases=list(dict.fromkeys(json.loads(found[0]['aliases_json'])+aliases))
        store.con.execute('UPDATE cs_candidates SET aliases_json=?,person_id=COALESCE(?,person_id),identity_note=? WHERE candidate_id=?',
                          (dumps(aliases),r.get('person_id') or None,'reviewed aliases: '+r['source_url'],r['candidate_id']))
        n+=1
    store.con.commit(); return n


def import_roster(store,path):
    n=0
    for r in read_csv(path):
        cols=['candidate_id','election_id','cycle','office','state','district','stage','known_at','source_url']
        require(r,[x for x in cols if x!='district'])
        if r['stage'] not in {'primary','general','runoff','special_general','special_primary'}:
            raise ValueError('Use an explicit contest stage; distinct Senate seats/specials need distinct election_id.')
        r['cycle']=int(r['cycle']); r['known_at']=iso(r['known_at'])
        store.con.execute('INSERT OR REPLACE INTO cs_roster VALUES(?,?,?,?,?,?,?,?,?)',tuple(r[x] for x in cols))
        n+=1
    store.con.commit(); return n


def import_outlets(store,path):
    n=0
    for r in read_csv(path):
        require(r,['domain','name'])
        domain=r['domain'].lower().removeprefix('www.')
        if '/' in domain or ' ' in domain or '.' not in domain: raise ValueError('Use an outlet domain, not a URL.')
        orientation=r.get('orientation') or 'unclassified'
        if orientation!='unclassified' and not r.get('orientation_source'):
            raise ValueError('Source any ideological labels; do not invent them.')
        store.con.execute('INSERT OR REPLACE INTO cs_outlets VALUES(?,?,?,?,?,?,?)',
          (domain,r['name'],r.get('scope_state') or 'US',
           int(r['media_cloud_id']) if r.get('media_cloud_id') else None,
           orientation,r.get('orientation_source') or '',int(r.get('permitted_fetch') or 0)))
        n+=1
    store.con.commit(); return n


def import_surveys(store,path):
    n=0
    for r in read_csv(path):
        require(r,['candidate_id','wave_id','pollster','geography','population','metric','field_end',
                   'available_at','source_url','favorable','unfavorable','sample_size'])
        f,u=finite_number(r['favorable'],0,1),finite_number(r['unfavorable'],0,1)
        if f+u>1.000001: raise ValueError('Survey shares must be fractions and sum to no more than one.')
        if iso(r['available_at'])<iso(r['field_end']): raise ValueError('Survey release precedes fieldwork end.')
        dk=finite_number(r['dont_know'],0,1) if r.get('dont_know') else None
        if dk is not None and f+u+dk>1.000001: raise ValueError('Survey categories sum above one.')
        sample=int(r['sample_size'])
        if sample<1: raise ValueError('sample_size must be positive')
        oid=r.get('observation_id') or digest([r['candidate_id'],r['wave_id'],r['pollster'],
                                             r['geography'],r['population'],r['metric'],r['available_at']])
        store.con.execute('INSERT OR REPLACE INTO cs_surveys VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
           (oid,r['candidate_id'],r['wave_id'],r['pollster'],r['geography'],r['population'],r['metric'],
            iso(r['field_end']),iso(r['available_at']),r['source_url'],f,u,sample,dk,dumps(r)))
        n+=1
    store.con.commit(); return n


def import_pedigree(store,path):
    n=0
    for r in read_csv(path):
        require(r,['candidate_id','effective_at','available_at','years_elected','general_wins',
                   'general_contests','history_complete','source_url'])
        years=finite_number(r['years_elected'],0,100)
        wins,contests=int(r['general_wins']),int(r['general_contests'])
        if not 0<=wins<=contests: raise ValueError('Require 0 <= wins <= contests.')
        if iso(r['available_at'])<iso(r['effective_at']): raise ValueError('Pedigree evidence cannot precede its effective date.')
        op=finite_number(r['mean_outperformance_pp'],-200,200) if r.get('mean_outperformance_pp') else None
        baseline=iso(r['baseline_train_end']) if r.get('baseline_train_end') else None
        if op is not None and not baseline:
            raise ValueError('Outperformance needs the training cutoff of its baseline model.')
        if baseline and baseline>=iso(r['effective_at']):
            raise ValueError('Baseline training cutoff must precede the snapshot. See history importer for per-race checks.')
        complete=int(r['history_complete'])
        if complete not in (0,1): raise ValueError('history_complete must be 0 or 1')
        oid=r.get('observation_id') or digest(r)
        store.con.execute('INSERT OR REPLACE INTO cs_pedigree VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
           (oid,r['candidate_id'],iso(r['effective_at']),iso(r['available_at']),years,wins,contests,op,
            baseline,complete,r['source_url'],dumps(r)))
        n+=1
    store.con.commit(); return n


def import_articles(store,path):
    n=0
    for r in read_csv(path):
        require(r,['url','title','candidate_ids_json','source_note'])
        store.article(url=r['url'],title=r['title'],candidate_ids=json.loads(r['candidate_ids_json']),
             body=r.get('body') or '',published_at=r.get('published_at') or None,
             indexed_at=r.get('indexed_at') or None,retrieved_at=r.get('retrieved_at') or now(),
             available_at=r.get('available_at') or None,
             availability_basis=r.get('availability_basis') or 'retrieved_version',
             archive_evidence_url=r.get('archive_evidence_url') or '',rights_note=r['source_note'],metadata={k:v for k,v in r.items() if k!='body'})
        n+=1
    store.con.commit(); return n


def import_annotations(store,path):
    n=0
    for r in read_csv(path):
        require(r,['version_id','candidate_id','sentiment','evidence'])
        store.annotation(r['version_id'],r['candidate_id'],r['sentiment'],model_id=r.get('model_id') or 'human:v1',
              confidence=r.get('confidence') or 1,entity_status=r.get('entity_status') or 'verified',
              reviewed=int(r.get('reviewed') or 0)==1,evidence=r['evidence'],diagnostics={'source':'annotation_csv'},
              annotated_at=r.get('annotated_at') or None,
              annotation_basis=r.get('annotation_basis') or 'created_now',
              annotation_evidence_url=r.get('annotation_evidence_url') or '')
        n+=1
    store.con.commit(); return n
