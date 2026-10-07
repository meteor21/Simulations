"""Agent 1: evidence-backed source registry, candidate identities and service history."""
from __future__ import annotations
import csv
import json
import zlib
import tempfile
from pathlib import Path
from urllib.parse import urljoin,urlsplit
from .agents_store import AgentStore
from .importers import read_csv, require, FecAcquisitionError
from .network import BudgetExceeded, AccessBlocked
from .util import now, iso, host, dumps, digest, dt

# FEC's exact production bulk-download target, verified from its public proxy:
# https://github.com/fecgov/fec-proxy/blob/42a867c3c0fc6d86584f024f09ec990d725a022c/manifest_prod.yml#L23
# https://github.com/fecgov/fec-proxy/blob/42a867c3c0fc6d86584f024f09ec990d725a022c/nginx.conf#L70-L71
FEC_BULK_HOST='cg-519a459a-0ea3-42c2-b7bc-fa1143481f74.s3-us-gov-west-1.amazonaws.com'


def import_profiles(store, path):
    n=0
    for r in read_csv(path):
        require(r,['domain','name','scope','evidence_url'])
        store.source_profile(domain=r['domain'],name=r['name'],scope=r['scope'],
          states=json.loads(r.get('states_json') or '[]'), geography=json.loads(r.get('geography_json') or '{}'),
          source_kind=r.get('source_kind') or 'news',network_group=r.get('network_group') or '',
          valid_from=r.get('valid_from') or None,valid_to=r.get('valid_to') or None,
          observed_at=r.get('observed_at') or None,evidence_url=r['evidence_url'],
          status=r.get('status') or 'reviewed',url_prefix=r.get('url_prefix') or '',notes=r.get('notes') or '',
          media_cloud_id=int(r['media_cloud_id']) if r.get('media_cloud_id') else None,
          permitted_fetch=int(r.get('permitted_fetch') or 0)==1)
        n+=1
    return n


def import_bias(store,path):
    n=0
    for r in read_csv(path):
        require(r,['domain','provider','label','valid_from','available_at','evidence_url'])
        store.bias(domain=r['domain'],provider=r['provider'],label=r['label'],valid_from=r['valid_from'],
          available_at=r['available_at'],evidence_url=r['evidence_url'],valid_to=r.get('valid_to') or None,
          genre=r.get('genre') or 'online_news',native_score=float(r['native_score']) if r.get('native_score') else None,
          native_scale=r.get('native_scale') or '',method=r.get('method') or 'sourced_provider_rating',
          status=r.get('status') or 'reviewed',confidence_label=r.get('confidence_label') or 'not_reported',
          sample_n=int(r['sample_n']) if r.get('sample_n') else None,license_note=r.get('license_note') or '',
          metadata=json.loads(r.get('metadata_json') or '{}'))
        n+=1
    return n


def import_terms(store,path):
    n=0
    for r in read_csv(path):
        require(r,['person_id','office','state','start_date','available_at','evidence_url'])
        store.term(person_id=r['person_id'],office=r['office'],state=r['state'],district=r.get('district') or '',
          party=r.get('party') or '',start_date=r['start_date'],end_date=r.get('end_date') or None,
          available_at=r['available_at'],evidence_url=r['evidence_url'])
        if r.get('candidate_id'):
            store.identity_link(r['candidate_id'],r['person_id'],r['evidence_url'],r.get('available_at'))
        n+=1
    return n


def import_congress_yaml(store,path,*,source_url,min_year=1990,observed_at=None):
    """CC0 congress-legislators file. Officials only; never used as a losers/ballot list.

    The file's current FEC-to-Bioguide crosswalk is a retrospectively observed identity
    link, not evidence that each FEC registration existed in every historical cycle.
    """
    import yaml
    observed=iso(observed_at or now()); n=links=0
    data=yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data,list): raise ValueError('Expected congress-legislators YAML list')
    for person in data:
        pid=person.get('id',{}).get('bioguide')
        if not pid: continue
        terms=[t for t in person.get('terms',[]) if str(t.get('end','9999'))[:4]>=str(min_year)]
        if not terms: continue
        person_id='bioguide:'+pid
        name=person.get('name',{}); full=name.get('official_full') or ' '.join(
            str(name.get(k,'')).strip() for k in ['first','middle','last','suffix'] if name.get(k))
        if len(full.split())<2: continue
        canonical='BIO:'+pid
        aliases=[' '.join([name.get('first',''),name.get('last','')]).strip()]
        if name.get('nickname') and name.get('last'):
            aliases.append(name['nickname']+' '+name['last'])
        aliases=[a for a in aliases if len(a.split())>=2 and a!=full]
        store.candidate(canonical,full,aliases,known_at=observed,source_url=source_url,person_id=person_id)
        store.identity_link(canonical,person_id,source_url,observed)
        for fec_id in person.get('id',{}).get('fec',[]):
            if store.rows('SELECT candidate_id FROM cs_candidates WHERE candidate_id=?',(fec_id,)):
                store.identity_link(fec_id,person_id,source_url,observed); links+=1
        for t in terms:
            office={'rep':'H','sen':'S'}.get(t.get('type'))
            if not office: continue
            # YAML service intervals are dates; normalize to midnight with exclusive end.
            start=str(t['start'])[:10]+'T00:00:00+00:00'
            end=str(t['end'])[:10]+'T00:00:00+00:00' if t.get('end') else None
            store.term(person_id=person_id,office=office,state=t.get('state','US'),
              district=str(t.get('district','')),party=t.get('party',''),start_date=start,end_date=end,
              available_at=observed,evidence_url=source_url)
            n+=1
    store.event('SourceAgent','import_service_history',terms=n,existing_fec_links=links,min_year=min_year,
                warning='Officeholders only; retrospective identities and scheduled service ends require audit.')
    return {'terms':n,'existing_fec_links':links}


def import_archive_jsonl(store,path):
    """Normalize licensed archive exports; never assert access/rights or historical availability.

    Every row is the project's documented archive contract, not an untested claim to
    parse every proprietary vendor export. Store per-row source URL and rights note.
    """
    n=0
    with open(path,encoding='utf-8') as f:
        for line_no,line in enumerate(f,1):
            if not line.strip(): continue
            r=json.loads(line)
            require(r,['url','title','published_at','candidate_ids','rights_note','source_note'])
            if not isinstance(r['candidate_ids'],list): raise ValueError(f'Line {line_no}: candidate_ids must be a list')
            body=r.get('body') or ''
            if not body and not r['title']: raise ValueError('Archive row needs text')
            basis=r.get('availability_basis','retrieved_version')
            retrieved=r.get('retrieved_at') or now()
            available=r.get('available_at') or retrieved
            if iso(available)<iso(r['published_at']): raise ValueError('Availability cannot precede publication')
            store.article(url=r['url'],title=r['title'],candidate_ids=r['candidate_ids'],body=body,
              published_at=r['published_at'],retrieved_at=retrieved,available_at=available,
              availability_basis=basis,archive_evidence_url=r.get('archive_evidence_url',''),rights_note=r['rights_note'],
              metadata={'provider':'archive_import','genre':r.get('genre','unknown'),
                        'source_note':r['source_note'],'archive_record_id':r.get('archive_record_id'),
                        'original_publisher':r.get('original_publisher'),
                        'syndication_id':r.get('syndication_id')})
            n+=1
    store.con.commit(); store.event('SourceAgent','import_archive',rows=n); return n


class SourceAgent:
    name='SourceAgent'
    def __init__(self,store:AgentStore): self.store=store

    def audit(self):
        profiles=self.store.rows("SELECT * FROM sa_source_profiles WHERE status='reviewed'")
        states={s for r in profiles for s in json.loads(r['states_json'])}
        result={'profiles':len(profiles),'covered_state_codes':sorted(states),
                'national_profiles':sum(r['scope']=='national' for r in profiles),
                'subnational_profiles':sum(r['scope'] in {'state','metro','local'} for r in profiles),
                'provider_ids_resolved':self.store.rows('SELECT COUNT(*) AS n FROM cs_outlets WHERE media_cloud_id IS NOT NULL')[0]['n'],
                'bias_assessments':self.store.rows("SELECT COUNT(*) AS n FROM sa_bias_assessments WHERE status='reviewed'")[0]['n'],
                'warning':'A source directory is not proof of article access, historical coverage, or panel representativeness.'}
        self.store.event(self.name,'audit',**result); return result

    def resolve(self,client,token,*,max_sources=12,max_pages=3,domains=None):
        """Resolve exact root-homepage matches; reject child-source ambiguity."""
        if not token: raise ValueError('MEDIACLOUD_API_KEY required')
        report=[]
        rows=self.store.rows('SELECT * FROM cs_outlets WHERE media_cloud_id IS NULL ORDER BY domain')
        if domains is not None:
            order={d:i for i,d in enumerate(dict.fromkeys(domains))}
            rows=sorted([r for r in rows if r['domain'] in order],key=lambda r:order[r['domain']])
        rows=rows[:max_sources]
        for outlet in rows:
            matches={}; directory_complete=False
            try:
                for page in range(max_pages):
                    response=client.get('https://search.mediacloud.org/api/sources/sources/',
                        params={'name':outlet['domain'],'platform':'online_news','limit':100,'offset':page*100},
                        headers={'Authorization':'Token '+token},min_interval=31)
                    data=response.json()
                    if not isinstance(data,dict) or not isinstance(data.get('results'),list):
                        raise ValueError('Unexpected Media Cloud directory schema')
                    for item in data['results']:
                        if host(item.get('homepage',''))==outlet['domain'] and not item.get('url_search_string'):
                            matches[int(item['id'])]=item
                    if not data.get('next'): directory_complete=True; break
                if len(matches)==1 and directory_complete:
                    sid,item=next(iter(matches.items()))
                    self.store.con.execute('UPDATE cs_outlets SET media_cloud_id=? WHERE domain=?',(sid,outlet['domain']))
                    # Preserve the raw metadata; do not guess a provider's first-story field name.
                    self.store.con.execute('INSERT OR REPLACE INTO sa_source_coverage VALUES(?,?,?,?,?,?)',
                        (outlet['domain'],'mediacloud',None,None,now(),dumps(item)))
                    status='exact_root_homepage_match'
                else: sid=None; status='directory_incomplete' if not directory_complete else ('ambiguous' if matches else 'not_found')
                self.store.con.commit()
                report.append({'domain':outlet['domain'],'source_id':sid,'status':status})
            except BudgetExceeded:
                report.append({'domain':outlet['domain'],'status':'budget_stop'}); break
            except AccessBlocked as exc:
                error={'domain':outlet['domain'],'status':'error','error_type':type(exc).__name__}
                status=getattr(exc,'http_status',None)
                if type(status) is int: error['http_status']=status
                report.append(error)
                if status in {401,403}: break  # No repeated lookups with denied credentials/access.
            except Exception as exc:
                report.append({'domain':outlet['domain'],'status':'error','error_type':type(exc).__name__})
        self.store.event(self.name,'resolve_sources',report=report); return report

    def discover_collection(self,client,token,collection_id,*,max_pages=2,proposed_state=None):
        """Additional local outlets enter a REVIEW queue, not a guessed local/ideology label.

        Media Cloud pub_state means headquarters, not audience coverage. Never label
        a national paper as local just because its headquarters are in that state.
        """
        if not token: raise ValueError('MEDIACLOUD_API_KEY required')
        proposals=[]
        for page in range(max_pages):
            r=client.get('https://search.mediacloud.org/api/sources/sources/',
              params={'collection_id':int(collection_id),'limit':100,'offset':100*page},
              headers={'Authorization':'Token '+token},min_interval=31)
            data=r.json()
            if not isinstance(data.get('results'),list): raise ValueError('Unexpected directory schema')
            for x in data['results']:
                domain=host(x.get('homepage',''))
                if not domain: continue
                proposals.append({'domain':domain,'name':x.get('label') or x.get('name') or domain,
                    'media_cloud_id':x['id'],'scope':'unknown','suggested_state':proposed_state,
                    'headquarters_state':x.get('pub_state'),'status':'needs_geographic_review',
                    'evidence_url':f'https://search.mediacloud.org/api/sources/sources/{x["id"]}/',
                    'provider_metadata':x})
            if not data.get('next'): break
        self.store.event(self.name,'discover_collection',collection_id=collection_id,proposals=len(proposals))
        return proposals


def download_fec_cycles(store,client,cycles,cache_dir):
    """Download official candidate-master ZIPs in Colab. Registration != ballot roster."""
    from .importers import import_fec_zip
    cache=Path(cache_dir);cache.mkdir(parents=True,exist_ok=True);report=[]
    for year in cycles:
        year=int(year)
        if year%2 or not 1990<=year<=2100: raise ValueError('Choose even FEC cycles from 1990 onward')
        url=f'https://www.fec.gov/files/bulk-downloads/{year}/cn{year%100:02d}.zip'
        path=cache/f'fec_candidates_{year}.zip'
        if not path.exists():
            current=url; visited=set()
            for hop in range(4):
                if current in visited:
                    raise FecAcquisitionError('download','redirect_loop',cycle=year)
                visited.add(current)
                try: response=client.get(current,min_interval=2,max_bytes=50_000_000)
                except AccessBlocked as exc:
                    raise FecAcquisitionError('download','access_or_transport_blocked',cycle=year,
                        http_status=getattr(exc,'http_status',None)) from None
                if response.status_code in {301,302,303,307,308}:
                    location=response.headers.get('Location')
                    if not location:
                        raise FecAcquisitionError('download','redirect_missing_location',cycle=year,http_status=response.status_code)
                    target=urljoin(current,location)
                    try:
                        parsed=urlsplit(target)
                        official_origin=parsed.hostname in {'www.fec.gov','fec.gov'}
                        verified_bulk_object=(parsed.hostname==FEC_BULK_HOST
                            and parsed.path==f'/bulk-downloads/{year}/cn{year%100:02d}.zip')
                        permitted=(parsed.scheme=='https' and (official_origin or verified_bulk_object)
                            and not parsed.username and not parsed.password and parsed.port in {None,443}
                            and not parsed.query and not parsed.fragment)
                    except ValueError: permitted=False
                    if not permitted:
                        raise FecAcquisitionError('download','redirect_not_permitted',cycle=year,http_status=response.status_code)
                    if hop==3:
                        raise FecAcquisitionError('download','redirect_limit',cycle=year,http_status=response.status_code)
                    current=target
                    continue  # Every hop uses the same client and durable allowance.
                if response.status_code!=200:
                    raise FecAcquisitionError('download','http_status',cycle=year,http_status=response.status_code)
                if not response.content.startswith(b'PK'):
                    raise FecAcquisitionError('download','response_not_zip',cycle=year,http_status=200)
                break
            temporary=None
            try:
                with tempfile.NamedTemporaryFile(prefix=path.name+'.',suffix='.part',dir=cache,delete=False) as f:
                    temporary=Path(f.name);f.write(response.content)
                # Failed validation leaves neither a partial roster nor a cached
                # corrupt ZIP that every future run would silently reuse.
                rows=import_fec_zip(store,temporary,year)
                temporary.replace(path)
            except OSError:
                raise FecAcquisitionError('cache','io_error',cycle=year) from None
            finally:
                if temporary is not None: temporary.unlink(missing_ok=True)
        else:
            rows=import_fec_zip(store,path,year)
        report.append({'cycle':year,'imported_rows':rows,'source_url':url,'cache_path':str(path),
                       'file_sha256':__import__('hashlib').sha256(path.read_bytes()).hexdigest()})
    store.event('SourceAgent','download_fec',report=report);return report


def download_congress_history(store,client,cache_dir,min_year=1990):
    cache=Path(cache_dir);cache.mkdir(parents=True,exist_ok=True);report=[]
    for suffix in ['historical','current']:
        url=f'https://raw.githubusercontent.com/unitedstates/congress-legislators/main/legislators-{suffix}.yaml'
        path=cache/f'legislators-{suffix}.yaml'
        if not path.exists():
            response=client.get(url,max_bytes=30_000_000,min_interval=2)
            if response.status_code!=200: raise ValueError('Service-history download failed')
            temporary=path.with_suffix('.part');temporary.write_bytes(response.content);temporary.replace(path)
        report.append(dict(file=str(path),source_url=url,**import_congress_yaml(store,path,source_url=url,min_year=min_year)))
    return report
