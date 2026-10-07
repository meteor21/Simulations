"""Resumable search workers. Every API page is committed before another is requested."""
from __future__ import annotations
import json
from datetime import datetime,timedelta,timezone
from .network import HttpClient, BudgetExceeded, AccessBlocked
from .util import dt, dumps, host, iso, months, now


def query_names(store,candidate_ids):
    names=[]
    for cid in candidate_ids:
        rows=store.rows('SELECT aliases_json FROM cs_candidates WHERE candidate_id=?',(cid,))
        if not rows: raise ValueError('Unknown candidate ID: '+cid)
        for name in json.loads(rows[0]['aliases_json']):
            # Exact phrase only, without injecting search operators from imported names.
            name=name.replace('"',' ').replace('\\',' ').strip()
            if name not in names: names.append(name)
    if not names: raise ValueError('No candidate names to search.')
    return '('+' OR '.join('"'+n+'"' for n in names)+')'


def plan(store, candidate_ids, start, end, *, provider='mediacloud', batch_size=8,
         domains=None, source_ids=None, collection_ids=None, max_jobs=10000):
    if provider not in {'mediacloud','gdelt'}: raise ValueError('Supported providers: mediacloud, gdelt.')
    if not 1<=batch_size<=25: raise ValueError('batch_size must be 1..25.')
    ids=sorted(set(candidate_ids))
    if not ids: raise ValueError('No candidates selected.')
    if provider=='mediacloud' and not (source_ids or collection_ids):
        raise ValueError('Media Cloud requires verified source_ids or collection_ids. Run resolve_outlets first.')
    if provider=='gdelt':
        # Conservative guard based on published API documentation; no claim of two-year DOC coverage.
        if dt(start,end_of_day=False)<datetime.now(timezone.utc)-timedelta(days=89):
            raise ValueError('GDELT DOC is restricted here to the last 89 days. Use Media Cloud/archival imports for history.')
        if dt(end)>datetime.now(timezone.utc)+timedelta(minutes=5):
            raise ValueError('End exceeds now. Use an explicit UTC timestamp for a live GDELT search.')
    windows=list(months(start,end))
    expected=((len(ids)+batch_size-1)//batch_size)*len(windows)
    if expected>max_jobs: raise ValueError(f'Plan would create {expected} initial jobs, above max_jobs={max_jobs}.')
    before=store.con.total_changes
    for a,b in windows:
        for i in range(0,len(ids),batch_size):
            batch=ids[i:i+batch_size]
            payload={'candidate_ids':batch,'query':query_names(store,batch),'start':a,'end':b,
                     'domains':sorted(domains or []),'source_ids':sorted(source_ids or []),
                     'collection_ids':sorted(collection_ids or []),'cursor':None}
            store.enqueue(provider,payload)
    store.con.commit()
    return {'candidate_ids':len(ids),'date_windows':len(windows),'initial_jobs':expected,
            'new_jobs':store.con.total_changes-before,
            'note':'Pagination/subdivision can add requests. This is not a promise of complete source coverage.'}


def resolve_outlets(store, client:HttpClient, token:str, *, max_pages=3):
    """Resolve source IDs only when the official directory homepage matches the configured domain."""
    if not token: raise ValueError('Set MEDIACLOUD_API_KEY in your local environment/Colab Secrets.')
    if type(max_pages) is not int or max_pages<1: raise ValueError('max_pages must be a positive integer')
    report=[]
    for outlet in store.rows('SELECT * FROM cs_outlets ORDER BY domain'):
        if outlet['media_cloud_id']:
            report.append({'domain':outlet['domain'],'id':outlet['media_cloud_id'],'status':'already_configured'}); continue
        matches={}
        complete=False
        for page in range(max_pages):
            r=client.get('https://search.mediacloud.org/api/sources/sources/',
                  params={'name':outlet['name'],'platform':'online_news','limit':100,'offset':page*100},
                  headers={'Authorization':'Token '+token},min_interval=31)
            data=r.json()
            if not isinstance(data,dict) or not isinstance(data.get('results'),list):
                raise ValueError('Unexpected source directory schema; source was not resolved.')
            for item in data.get('results',[]):
                if host(item.get('homepage',''))==outlet['domain']:
                    matches[int(item['id'])]=item
            if not data.get('next'):
                complete=True
                break
        if not complete:
            report.append({'domain':outlet['domain'],'id':None,'status':'incomplete_directory_search'})
        elif len(matches)==1:
            source_id=next(iter(matches))
            store.con.execute('UPDATE cs_outlets SET media_cloud_id=? WHERE domain=?',(source_id,outlet['domain']))
            report.append({'domain':outlet['domain'],'id':source_id,'status':'exact_homepage_match'})
        else:
            report.append({'domain':outlet['domain'],'id':None,'status':'ambiguous' if matches else 'not_resolved'})
        store.con.commit()
    return report


class MediaCloudProvider:
    name='mediacloud'
    def __init__(self,client,token):
        if not token: raise ValueError('MEDIACLOUD_API_KEY is required for historical Media Cloud search.')
        self.client=client; self.token=token

    def page(self,p):
        params={'q':p['query']+' AND language:en','start':p['start'][:10],'end':p['end'][:10],
                'platform':'onlinenews-mediacloud','page_size':1000}
        if p['source_ids']: params['ss']=','.join(map(str,p['source_ids']))
        if p['collection_ids']: params['cs']=','.join(map(str,p['collection_ids']))
        if p.get('cursor'): params['pagination_token']=p['cursor']
        r=self.client.get('https://search.mediacloud.org/api/search/story-list',params=params,
                         headers={'Authorization':'Token '+self.token},min_interval=31)
        data=r.json()
        if not isinstance(data,dict) or not isinstance(data.get('stories'),list) or 'pagination_token' not in data:
            raise ValueError('Unexpected Media Cloud schema; no empty-success substitution was made.')
        stories=[]
        for s in data['stories']:
            if not s.get('url'): continue
            stories.append({'url':s['url'],'title':s.get('title') or '',
                            'published_at':s.get('publish_date'), 'indexed_at':s.get('indexed_date'),
                            'metadata':{'provider':'mediacloud','provider_id':s.get('id'),'language':s.get('language')}})
        token=data['pagination_token']
        if token is not None and not isinstance(token,str): raise ValueError('Unexpected pagination token type.')
        if token and token==p.get('cursor'): raise ValueError('Provider repeated its pagination token.')
        return stories,token,False


class GdeltProvider:
    name='gdelt'
    def __init__(self,client): self.client=client
    def page(self,p):
        if dt(p['start'])<datetime.now(timezone.utc)-timedelta(days=90):
            raise AccessBlocked('Queued GDELT window has aged outside the supported recent window; use an archive provider.')
        query=p['query']+' sourcelang:english'
        if p['domains']: query+=' ('+' OR '.join('domainis:'+d for d in p['domains'])+')'
        params={'query':query,'mode':'artlist','format':'json','maxrecords':250,'sort':'DateAsc',
                'startdatetime':dt(p['start']).strftime('%Y%m%d%H%M%S'),
                'enddatetime':dt(p['end']).strftime('%Y%m%d%H%M%S')}
        r=self.client.get('https://api.gdeltproject.org/api/v2/doc/doc',params=params,min_interval=5.1)
        data=r.json()
        if not isinstance(data,dict) or not isinstance(data.get('articles'),list):
            raise ValueError('Unexpected GDELT response; inspect provider instead of assuming zero coverage.')
        rows=data['articles']; stories=[]
        for s in rows:
            seen=s.get('seendate')
            if seen:
                try: seen=datetime.strptime(seen,'%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc).isoformat()
                except ValueError: seen=None
            stories.append({'url':s['url'],'title':s.get('title') or '', 'published_at':None,
                            'indexed_at':seen,'metadata':{'provider':'gdelt','date_basis':'index_seen_not_publication'}})
        return stories,None,len(rows)>=250


def run_search(store,provider,*,max_jobs=20,checkpoint_path=None,checkpoint_every=5):
    """Sequential worker; bounded requests, idempotent pages, explicit blocked/error states."""
    counts={'processed':0,'processed_hits':0,'split':0,'blocked':0,'errors':0}
    if type(max_jobs) is not int or max_jobs<0: raise ValueError('max_jobs must be a nonnegative integer')
    if type(checkpoint_every) is not int or checkpoint_every<1: raise ValueError('checkpoint_every must be positive')
    try:
        for _ in range(max_jobs):
            row=store.con.execute("SELECT * FROM cs_jobs WHERE provider=? AND status='pending' ORDER BY created_at,job_id LIMIT 1",(provider.name,)).fetchone()
            if row is None: break
            p=json.loads(row['payload_json']); jid=row['job_id']
            store.con.execute("UPDATE cs_jobs SET status='running',attempts=attempts+1,updated_at=? WHERE job_id=?",(now(),jid)); store.con.commit()
            try:
                articles,cursor,saturated=provider.page(p)
                if cursor and store.con.execute('SELECT 1 FROM cs_jobs WHERE provider=? AND payload_json=?',
                        (provider.name,dumps(dict(p,cursor=cursor)))).fetchone():
                    raise ValueError('Provider pagination cycle detected; page was not marked complete.')
                t=now()
                page_hits=0
                with store.con:
                    # Oversized GDELT pages are subdivided before importing; avoid biased first-250 samples.
                    if saturated:
                        a,b=dt(p['start']),dt(p['end'])
                        if (b-a).total_seconds()<=3600:
                            store.con.execute("UPDATE cs_jobs SET status='saturated',error='Still at API cap at minimum window; not complete',updated_at=? WHERE job_id=?",(t,jid))
                            counts['blocked']+=1
                        else:
                            midpoint=a+(b-a)/2
                            for x,y in [(a,midpoint),(midpoint,b)]:
                                child=dict(p,start=x.isoformat(timespec='seconds'),end=y.isoformat(timespec='seconds'))
                                store.enqueue(provider.name,child)
                            store.con.execute("UPDATE cs_jobs SET status='split',updated_at=? WHERE job_id=?",(t,jid))
                            counts['split']+=1
                    else:
                        for a in articles:
                            # If a domain panel was supplied, retain only its members; never silently widen it.
                            if p['domains'] and not any(host(a['url'])==d or host(a['url']).endswith('.'+d) for d in p['domains']): continue
                            store.article(candidate_ids=p['candidate_ids'],retrieved_at=t,**a)
                            page_hits+=1
                        if cursor:
                            store.enqueue(provider.name,dict(p,cursor=cursor))
                        store.con.execute("UPDATE cs_jobs SET status='done',error=NULL,updated_at=? WHERE job_id=?",(t,jid))
                counts['processed']+=1
                counts['processed_hits']+=page_hits
            except BudgetExceeded:
                store.con.rollback()
                store.con.execute("UPDATE cs_jobs SET status='pending',updated_at=? WHERE job_id=?",(now(),jid)); store.con.commit()
                break
            except AccessBlocked as e:
                store.con.rollback()
                store.con.execute("UPDATE cs_jobs SET status='blocked',error=?,updated_at=? WHERE job_id=?",(str(e)[:400],now(),jid)); store.con.commit()
                counts['blocked']+=1
                break  # no repeated retries at the same blocked service
            except Exception as e:
                store.con.rollback()
                # Type only: exception URLs can contain API credentials.
                store.con.execute("UPDATE cs_jobs SET status='error',error=?,updated_at=? WHERE job_id=?",(type(e).__name__+': check response contract or input data',now(),jid)); store.con.commit()
                counts['errors']+=1
                break
            if checkpoint_path and counts['processed'] and counts['processed']%checkpoint_every==0:
                store.backup(checkpoint_path)
    finally:
        if checkpoint_path: store.backup(checkpoint_path)
    return counts


def requeue_failed(store):
    """Explicit user retry after correcting access/schema issues; never an infinite retry loop."""
    store.con.execute("UPDATE cs_jobs SET status='pending',error=NULL WHERE status IN ('blocked','error')")
    store.con.commit()
