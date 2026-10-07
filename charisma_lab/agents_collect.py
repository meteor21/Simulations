"""Agent 2: budgeted national/state source panels, service-term and campaign queues."""
from __future__ import annotations
import json
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .collect import plan as base_plan, query_names, run_search
from .scrape import Scraper,run_fetch
from .network import BudgetExceeded,AccessBlocked
from .util import iso,dt,now,digest,dumps,months,host


def select_cohort(store,cycles=(2026,),*,roster_only=False,max_candidates=24,offices=('H','S'),as_of=None):
    if not cycles: raise ValueError('Select at least one cycle')
    if not set(offices)<={'H','S'}: raise ValueError('Congressional cohort accepts H/S only; keep national context separate')
    if not offices: raise ValueError('Select at least one congressional office')
    if max_candidates is not None and (type(max_candidates) is not int or max_candidates<0):
        raise ValueError('max_candidates must be nonnegative or None')
    table='cs_roster' if roster_only else 'cs_candidate_cycles'
    sql=f'''SELECT x.*,c.name,c.aliases_json FROM {table} x JOIN cs_candidates c USING(candidate_id)
      WHERE x.cycle IN ({','.join('?' for _ in cycles)}) AND x.office IN ({','.join('?' for _ in offices)})'''
    if not roster_only: sql+=' AND (x.target_election_year IS NULL OR x.target_election_year=x.cycle)'
    params=tuple(cycles)+tuple(offices)
    if as_of is not None:
        sql+=' AND x.known_at<=? AND c.known_at<=?'
        params+=(iso(as_of),iso(as_of))
    rows=store.rows(sql,params)
    # Deterministic interleaving, not an alphabetical celebrity/party sample.
    strata=defaultdict(list)
    for r in rows: strata[(r['state'],r['office'],r.get('party',''),r['cycle'])].append(r)
    queues=[deque(sorted(v,key=lambda r:digest([r['candidate_id'],r['cycle'],r.get('election_id'),r.get('stage')]))) for k,v in sorted(strata.items())]
    chosen=[]; seen=set()
    while any(queues):
        for q in queues:
            if q:
                r=q.popleft(); key=(r['candidate_id'],r['cycle'],r['office'],r['state'],r['district'],r.get('election_id'),r.get('stage'))
                if key not in seen: chosen.append(r); seen.add(key)
        if max_candidates is not None and len(chosen)>=max_candidates: break
    if max_candidates is not None: chosen=chosen[:max_candidates]
    return chosen


class CollectionAgent:
    name='CollectionAgent'
    def __init__(self,store): self.store=store

    def _profiles(self):
        latest={}
        rows=self.store.rows("SELECT * FROM sa_source_profiles WHERE status='reviewed' ORDER BY valid_from DESC")
        for r in rows: latest.setdefault((r['domain'],r['url_prefix']),r)
        return list(latest.values())

    def plan_campaign(self,cohort,start,end,*,provider='mediacloud',batch_size=8,
                      run_label='midterms-2026',dry_run=False,max_initial_jobs=10000):
        """Same national evidence is shared across candidates; local panels routed by state.

        Statewide eligibility is not a claim that every voter in a House district reads
        every outlet in that state. District-consumption modeling is a later layer.
        """
        if provider not in {'mediacloud','gdelt'}: raise ValueError('Unsupported provider')
        profiles=[p for p in self._profiles() if p['source_kind'] in {'news','wire','opinion','advocacy'}]
        national=[p for p in profiles if p['scope']=='national']
        states=defaultdict(set); ids=set()
        cycles={r['cycle'] for r in cohort}
        for r in cohort:
            if r['office'] not in {'H','S'}: raise ValueError('Do not mix presidential registrations into the congressional cohort')
            states[r['state']].add(r['candidate_id']); ids.add(r['candidate_id'])
        if not ids: raise ValueError('No congressional candidates selected; import registry/roster first')
        groups=[('national','US',sorted(ids),national)]
        for state,cids in sorted(states.items()):
            local=[p for p in profiles if p['scope'] in {'state','metro','local'} and state in json.loads(p['states_json'])]
            groups.append(('subnational',state,sorted(cids),local))
        windows=len(list(months(start,end)))
        estimated=sum(((len(cids)+batch_size-1)//batch_size)*windows for _,_,cids,p in groups if p)
        if estimated>max_initial_jobs: raise ValueError(f'Would plan {estimated} initial jobs; raise max_initial_jobs explicitly or narrow cohort/window')
        provider_ids={r['domain']:r['media_cloud_id'] for r in self.store.rows('SELECT * FROM cs_outlets')}
        report=[]
        for scope,state,cids,panel in groups:
            all_domains=sorted({p['domain'] for p in panel})
            unresolved=[d for d in all_domains if not provider_ids.get(d)] if provider=='mediacloud' else []
            domains=[d for d in all_domains if d not in unresolved]
            detail={'selected_domains':all_domains,'unresolved_domains':unresolved,
                    'district_note':'State-routed discovery; not district audience reach',
                    'history_note':'Current directory used for discovery; historical source/ideology validity checked during scoring'}
            status='planned'; jobs=[]
            count=((len(cids)+batch_size-1)//batch_size)*windows if all_domains else 0
            if not all_domains: status='no_source_panel'
            elif dry_run: status='dry_run'
            elif not domains: status='blocked_unresolved_source_ids'
            else:
                before={r['job_id'] for r in self.store.rows('SELECT job_id FROM cs_jobs')}
                result=base_plan(self.store,cids,start,end,provider=provider,batch_size=batch_size,
                  domains=domains,source_ids=[provider_ids[d] for d in domains] if provider=='mediacloud' else [],
                  max_jobs=max_initial_jobs)
                # Include reused jobs too, for an auditable coverage manifest.
                for row in self.store.rows('SELECT * FROM cs_jobs WHERE provider=?',(provider,)):
                    payload=json.loads(row['payload_json'])
                    if payload.get('domains')==domains and set(payload['candidate_ids'])<=set(cids) and payload['start']>=dt(start,end_of_day=False).isoformat(timespec='seconds') and payload['end']<=iso(end):
                        jobs.append(row['job_id'])
                detail['new_jobs']=result['new_jobs']
                if unresolved: status='partial_source_resolution'
            record={'scope':scope,'state':state,'candidate_count':len(cids),'candidate_ids':cids,
                    'potential_initial_jobs':count,'resolved_domains':len(domains),'unresolved_domains':len(unresolved),
                    'status':status,'detail':detail}
            report.append(record)
            if not dry_run:
                aid=digest([run_label,scope,state,cids,start,end,provider,all_domains,domains])
                self.store.con.execute('INSERT OR REPLACE INTO sa_plan_audit VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                 (aid,run_label,next(iter(cycles)) if len(cycles)==1 else None,dumps(cids),scope,state,iso(start),iso(end),provider,dumps(domains),dumps(jobs),status,dumps(detail),now()))
                self.store.con.commit()
        self.store.event(self.name,'plan_campaign',run_label=run_label,dry_run=dry_run,estimated_initial_jobs=estimated,groups=len(report))
        return report

    def plan_service(self,candidate_ids,*,start='1990-01-01',end=None,provider='mediacloud',
                     dry_run=True,max_initial_jobs=10000):
        end=end or now(); report=[]; estimated_total=0
        for cid in sorted(set(candidate_ids)):
            terms=self.store.rows('''SELECT t.* FROM sa_service_terms t JOIN sa_identity_links l USING(person_id)
                                   WHERE l.candidate_id=? AND t.office IN ('H','S')''',(cid,))
            if not terms:
                report.append({'candidate_id':cid,'status':'no_service_history'}); continue
            for term in terms:
                a=max(dt(start,end_of_day=False),dt(term['start_date'],end_of_day=False))
                b=min(dt(end),dt(term['end_date'],end_of_day=False) if term['end_date'] else dt(end))
                if a>=b: continue
                # The end is exclusive: avoid attributing the next officeholder's first instant.
                if term['end_date'] and b==dt(term['end_date'],end_of_day=False): b-=timedelta(seconds=1)
                cohort=[{'candidate_id':cid,'cycle':0,'office':term['office'],'state':term['state'],'district':term['district']}]
                preview=self.plan_campaign(cohort,a.isoformat(),b.isoformat(),provider=provider,
                      run_label='service:'+term['term_id'],dry_run=True,max_initial_jobs=max_initial_jobs)
                count=sum(x['potential_initial_jobs'] for x in preview)
                estimated_total+=count
                if estimated_total>max_initial_jobs: raise ValueError('Service history plan exceeds aggregate max_initial_jobs; narrow years/candidates')
                report.append({'candidate_id':cid,'term_id':term['term_id'],'start':a.isoformat(),
                               'end':b.isoformat(),'status':'preview' if dry_run else 'planned',
                               'groups':preview,'cohort':cohort})
        # Only enqueue after the whole aggregate plan passes the budget check.
        if not dry_run:
            for r in report:
                if r.get('status')=='planned':
                    r['groups']=self.plan_campaign(r.pop('cohort'),r['start'],r['end'],provider=provider,
                        run_label='service:'+r['term_id'],dry_run=False,max_initial_jobs=max_initial_jobs)
        self.store.event(self.name,'plan_service',estimated_initial_jobs=estimated_total,dry_run=dry_run)
        return report

    def run(self,provider,*,max_jobs=10,checkpoint_path=None):
        result=run_search(self.store,provider,max_jobs=max_jobs,checkpoint_path=checkpoint_path)
        self.store.event(self.name,'collect',provider=provider.name,**result); return result

    def scrape(self,client,*,max_articles=25,checkpoint_path=None):
        domains=[r['domain'] for r in self.store.rows('SELECT domain FROM cs_outlets WHERE permitted_fetch=1')]
        if not domains: return {'status':'disabled_no_permitted_domains','fetched':0}
        result=run_fetch(self.store,Scraper(client,domains),max_articles=max_articles,checkpoint_path=checkpoint_path)
        self.store.event(self.name,'scrape',**result); return result

    def queue_status(self):
        return self.store.rows('SELECT provider,status,COUNT(*) AS jobs FROM cs_jobs GROUP BY provider,status ORDER BY provider,status')
