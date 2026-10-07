import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from charisma_lab.agents_store import AgentStore
from charisma_lab.agents_sources import import_profiles,import_bias,import_archive_jsonl,SourceAgent,import_congress_yaml
from charisma_lab.agents_collect import CollectionAgent,select_cohort
from charisma_lab.agents_analysis import FeatureConfig,snapshot,AnalysisAgent,eligible_portrayals
from charisma_lab.agents_bias import import_independent_bias_samples
from charisma_lab.agents_rss import parse_feed
from charisma_lab.agents import SentimentWorkflow,RunBudget
from charisma_lab.util import now,dumps

@pytest.fixture
def db(tmp_path):
    s=AgentStore(tmp_path/'test.sqlite')
    for cid,name,state,office in [('C1','Alex Rowan','MI','H'),('C2','Jordan Vale','PA','S')]:
        s.candidate(cid,name,known_at='1990-01-01',source_url='synthetic://candidate')
        s.con.execute('INSERT INTO cs_candidate_cycles VALUES(?,?,?,?,?,?,?,?,?,?)',
            (cid,2026,office,state,'1','X',2026,'registry_only','1990-01-01','synthetic://candidate'))
    for domain,scope,states in [('nat1.example','national',[]),('nat2.example','national',[]),
                                ('mi1.example','state',['MI']),('mi2.example','metro',['MI']),('pa1.example','state',['PA'])]:
        s.source_profile(domain=domain,name=domain,scope=scope,states=states,evidence_url='synthetic://scope',
                         observed_at='1990-01-01',valid_from='1990-01-01',media_cloud_id=len(domain))
    s.con.commit(); yield s; s.close()


def article(db,domain,slug,sentiment=0.5,published='2026-09-20',retrieved='2026-09-20',body='',**kwargs):
    cid=kwargs.pop('cid','C1');title=kwargs.pop('title',f'Congress candidate Alex Rowan {slug}')
    vid=db.article(url=f'https://{domain}/{slug}',title=title,body=body,candidate_ids=[cid],
       published_at=published,retrieved_at=retrieved,**kwargs)
    db.annotation(vid,cid,sentiment,evidence=title,annotated_at=published,
                  annotation_basis='synthetic_fixture',annotation_evidence_url='synthetic://article-label-fixture')
    db.con.commit();return vid


def cfg(**kw): return FeatureConfig(min_outlets=1,min_unique_articles=1,**kw)


def test_source_seed_count_and_all_states(tmp_path):
    root=Path(__file__).parents[1]
    with AgentStore(tmp_path/'seed.sqlite') as s:
        assert import_profiles(s,root/'data/source_profiles.csv')==63
        assert import_bias(s,root/'data/source_bias_seed.csv')==6
        audit=SourceAgent(s).audit()
        assert len(audit['covered_state_codes'])==50
        assert audit['national_profiles']==12
        assert s.rating_for('foxnews.com','1994-01-01','2026-10-06')['label']=='Unknown'

@pytest.mark.parametrize('scope,states',[('nationalx',[]),('state',[]),('metro',['XX'])])
def test_bad_scope_rejected(db,scope,states):
    with pytest.raises(ValueError):db.source_profile(domain='x.example',name='X',scope=scope,states=states,evidence_url='x')


def test_current_profile_not_historical(db):
    db.source_profile(domain='new.example',name='New',scope='state',states=['MI'],observed_at='2026-10-06',evidence_url='x')
    assert db.profile_for('https://new.example/a','1994-01-01','1994-01-02') is None
    r=db.profile_for('https://new.example/a','1994-01-01','1994-01-02',mode='retrospective')
    assert not r['historical_scope_verified']


def test_source_edition_prefix(db):
    db.source_profile(domain='nat1.example',name='Michigan edition',scope='local',states=['MI'],
         url_prefix='https://nat1.example/local/mi/',observed_at='1990-01-01',evidence_url='x')
    assert db.profile_for('https://nat1.example/local/mi/a','2026-01-01','2026-01-01')['scope']=='local'
    assert db.profile_for('https://nat1.example/politics/a','2026-01-01','2026-01-01')['scope']=='national'


def bias(db,provider='AllSides',label='Left',**kw):
    return db.bias(domain='nat1.example',provider=provider,label=label,valid_from=kw.pop('valid_from','1990-01-01'),
                   available_at=kw.pop('available_at','1990-01-01'),evidence_url='synthetic://bias',**kw)


def test_bias_time_and_disagreement(db):
    bias(db);bias(db,'Other','Right')
    assert db.rating_for('nat1.example','2026-01-01','2026-01-01')['label']=='Mixed/Disputed'
    assert db.rating_for('nat1.example','2026-01-01','2026-01-01',provider='AllSides')['label']=='Left'


def test_future_bias_not_backfilled(db):
    bias(db,valid_from='2026-10-06',available_at='2026-10-06')
    assert db.rating_for('nat1.example','2024-01-01','2026-10-06')['label']=='Unknown'


def test_bias_available_after_cutoff_excluded(db):
    bias(db,available_at='2027-01-01')
    assert db.rating_for('nat1.example','2026-01-01','2026-10-06')['label']=='Unknown'


def test_provisional_bias_not_used(db):
    bias(db,status='provisional',method='model_provisional')
    assert db.rating_for('nat1.example','2026-01-01','2026-10-06')['label']=='Unknown'


def test_news_bias_not_opinion_bias(db):
    bias(db,genre='online_news')
    assert db.rating_for('nat1.example','2026-01-01','2026-10-06',genre='opinion')['label']=='Unknown'


def test_numeric_bias_needs_scale(db):
    with pytest.raises(ValueError):bias(db,native_score=3.2)


def test_plan_routes_states_without_president(db):
    db.candidate('P1','National Leader',known_at='1990-01-01',source_url='x')
    db.con.execute('INSERT INTO cs_candidate_cycles VALUES(?,?,?,?,?,?,?,?,?,?)',('P1',2026,'P','US','','X',2026,'registry_only','1990-01-01','x'))
    db.con.commit()
    rows=select_cohort(db,max_candidates=None)
    assert {r['candidate_id'] for r in rows}=={'C1','C2'}
    report=CollectionAgent(db).plan_campaign(rows,'2026-09-01','2026-09-30')
    bystate={r['state']:r for r in report}
    assert bystate['US']['candidate_count']==2
    assert bystate['MI']['candidate_ids']==['C1']
    assert 'pa1.example' not in bystate['MI']['detail']['selected_domains']
    assert db.rows('SELECT COUNT(*) n FROM sa_plan_audit')[0]['n']==3


def test_registration_target_mismatch_excluded(db):
    db.con.execute("UPDATE cs_candidate_cycles SET target_election_year=2028 WHERE candidate_id='C2'");db.con.commit()
    assert [r['candidate_id'] for r in select_cohort(db)]==['C1']


def test_roster_only_not_registration(db):
    assert select_cohort(db,roster_only=True)==[]


def test_plan_idempotent(db):
    worker=CollectionAgent(db);rows=select_cohort(db)
    worker.plan_campaign(rows,'2026-09-01','2026-09-30')
    n=db.rows('SELECT COUNT(*) n FROM cs_jobs')[0]['n']
    worker.plan_campaign(rows,'2026-09-01','2026-09-30')
    assert db.rows('SELECT COUNT(*) n FROM cs_jobs')[0]['n']==n


def test_plan_cap_before_writes(db):
    with pytest.raises(ValueError):CollectionAgent(db).plan_campaign(select_cohort(db),'1990-01-01','2026-10-06',max_initial_jobs=2)
    assert db.rows('SELECT COUNT(*) n FROM cs_jobs')[0]['n']==0


def test_unresolved_panel_explicit(db):
    db.con.execute('UPDATE cs_outlets SET media_cloud_id=NULL');db.con.commit()
    r=CollectionAgent(db).plan_campaign(select_cohort(db),'2026-09-01','2026-09-30')
    assert all(x['status']=='blocked_unresolved_source_ids' for x in r)


def test_historical_service_windows(db):
    db.identity_link('C1','person1','x','1990-01-01')
    db.term(person_id='person1',office='H',state='MI',start_date='1991-01-03T00:00:00Z',
            end_date='1993-01-03T00:00:00Z',available_at='1990-01-01',evidence_url='x')
    r=CollectionAgent(db).plan_service(['C1'],start='1990-01-01',end='1994-01-01',dry_run=True)
    assert r[0]['start'].startswith('1991-01-03')
    assert r[0]['end'].startswith('1993-01-02')


def test_missing_components_do_not_turn_neutral(db):
    s=snapshot(db,'C1','2026-10-06',state='MI',config=cfg())
    assert s['media_recency_score'] is None and s['national']['score'] is None
    article(db,'nat1.example','only')
    s=snapshot(db,'C1','2026-10-06',state='MI',config=cfg())
    assert s['national']['score']==75 and s['subnational']['score'] is None
    assert s['media_recency_score'] is None


def test_national_local_equal_weights(db):
    article(db,'nat1.example','a',1);article(db,'mi1.example','b',-1)
    s=snapshot(db,'C1','2026-10-06',state='MI',config=cfg())
    assert s['media_recency_score']==50 and s['local_minus_national']==-100


def test_wrong_state_not_local(db):
    article(db,'pa1.example','wrong',-1)
    s=snapshot(db,'C1','2026-10-06',state='MI',config=cfg())
    assert s['subnational']['article_urls']==0


def test_strict_future_version_vs_retro(db):
    article(db,'nat1.example','a',published='1994-09-01',retrieved='2026-10-06')
    s=snapshot(db,'C1','1994-10-01',state='MI',config=cfg())
    assert s['national']['article_urls']==0
    r=snapshot(db,'C1','1994-10-01',state='MI',config=cfg(mode='retrospective'))
    assert r['national']['article_urls']==1
    assert 'later_retrieved_versions_present' in r['flags']


def test_postcutoff_publication_never_allowed(db):
    article(db,'nat1.example','future',published='2027-01-01',retrieved='2027-01-01')
    r=snapshot(db,'C1','2026-10-06',state='MI',config=cfg(mode='retrospective'))
    assert r['national']['article_urls']==0


def test_updated_url_not_double_counted(db):
    article(db,'nat1.example','a',.7)
    article(db,'nat1.example','a',-.7,retrieved='2026-10-01',title='Congress candidate Alex Rowan revised headline')
    s=snapshot(db,'C1','2026-10-06',state='MI',config=cfg())
    assert s['national']['article_urls']==1
    assert s['national']['score']==pytest.approx(15.)


def test_exact_syndication_diagnostic(db):
    body='Congress candidate Alex Rowan is discussed in this identical piece. '*10
    article(db,'nat1.example','copy1',body=body);article(db,'nat2.example','copy2',body=body)
    s=snapshot(db,'C1','2026-10-06',state='MI',config=cfg())
    assert s['national']['article_urls']==2 and s['national']['unique_text_clusters']==1
    assert s['national']['syndicated_or_identical_url_excess']==1


def test_ideology_not_weight_penalty(db):
    bias(db,label='Right');article(db,'nat1.example','a',1)
    db.bias(domain='nat2.example',provider='AllSides',label='Left',valid_from='1990-01-01',available_at='1990-01-01',evidence_url='x')
    article(db,'nat2.example','b',-1)
    s=snapshot(db,'C1','2026-10-06',state='MI',config=cfg())
    assert s['national']['score']==50
    assert s['source_ideology_strata']['Right']['score']==100
    assert s['source_ideology_strata']['Left']['score']==0


def test_campaign_sources_separate(db):
    db.source_profile(domain='campaign.example',name='Campaign',scope='national',source_kind='campaign',
                      observed_at='1990-01-01',evidence_url='x')
    article(db,'campaign.example','a')
    s=snapshot(db,'C1','2026-10-06',state='MI',config=cfg())
    assert s['national']['article_urls']==0
    assert s['dropped']['separate_nonnews_channel']==1


def test_term_end_exclusive(db):
    db.identity_link('C1','person1','x','1990-01-01')
    db.term(person_id='person1',office='H',state='MI',start_date='2025-01-03T00:00:00Z',
        end_date='2026-09-20T00:00:00Z',available_at='2026-09-20T00:00:00Z',evidence_url='x')
    article(db,'nat1.example','during',published='2026-09-19',retrieved='2026-09-19')
    article(db,'nat1.example','after',published='2026-09-20T00:00:00Z',retrieved='2026-09-20T00:00:00Z')
    s=snapshot(db,'C1','2026-10-06',state='MI',config=cfg())
    assert s['during_service']['article_urls']==1
    assert s['outside_recorded_service']['article_urls']==1
    assert s['in_office_at_cutoff'] is False


def test_unknown_history_not_out_of_office(db):
    s=snapshot(db,'C1','2026-10-06',state='MI',config=cfg())
    assert s['in_office_at_cutoff'] is None


def test_monthly_history_has_month_ends(db):
    rows=AnalysisAgent(db).monthly_history('C1','1990-01-01','1990-03-20',state='MI',config=cfg())
    assert [r['as_of'][:10] for r in rows]==['1990-01-31','1990-02-28','1990-03-20']


def test_archive_backdating_rejected_without_evidence(db,tmp_path):
    row=dict(url='https://nat1.example/a',title='Congress Alex Rowan',published_at='1994-01-01',
      candidate_ids=['C1'],rights_note='test',source_note='test',retrieved_at='2026-01-01',available_at='1994-01-01')
    p=tmp_path/'archive.jsonl';p.write_text(json.dumps(row)+'\n')
    with pytest.raises(ValueError):import_archive_jsonl(db,p)


def test_independent_bias_corpus_cannot_be_candidate_search(db,tmp_path):
    row=dict(domain='nat1.example',url='https://nat1.example/a',title='Title',body='body '*100,published_at='1994-01-01',
      available_at='1994-01-01',sampling_frame='candidate_search',rights_note='test',evidence_url='x')
    p=tmp_path/'bias.jsonl';p.write_text(json.dumps(row)+'\n')
    with pytest.raises(ValueError):import_independent_bias_samples(db,p)


def test_rss_publication_not_update_date():
    xml=b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Alex Rowan campaign</title>
      <link href="https://nat1.example/a"/><updated>2026-10-06T10:00:00Z</updated></entry></feed>'''
    assert parse_feed(xml)[0]['published_at'] is None


def test_rss_parse_publication():
    xml=b'''<rss><channel><item><title>Congress Alex Rowan</title><link>https://nat1.example/a</link>
      <pubDate>Tue, 06 Oct 2026 10:00:00 GMT</pubDate></item></channel></rss>'''
    assert parse_feed(xml)[0]['published_at']=='2026-10-06T10:00:00+00:00'


def test_xml_entities_blocked():
    from defusedxml.common import DefusedXmlException
    with pytest.raises(DefusedXmlException):parse_feed(b'<!DOCTYPE a [<!ENTITY x "unsafe">]><rss><item><title>&x;</title></item></rss>')


def test_unknown_alias_is_not_sentiment(db):
    vid=db.article(url='https://nat1.example/a',title='Someone else wins a Senate contest',candidate_ids=['C1'],published_at='2026-09-20')
    class Stub:
        model_id='test-model'
        def predict(self,x): raise AssertionError('Should not classify absent target')
    result=AnalysisAgent(db).annotate(Stub())
    assert result['no_name_match']==1
    assert db.rows('SELECT entity_status FROM cs_annotations WHERE version_id=?',(vid,))[0]['entity_status']=='no_match'


def test_same_person_fec_bioguide_not_false_homonym(db):
    db.candidate('BIO1','Alex Rowan',known_at='1990-01-01',source_url='x')
    db.identity_link('C1','person1','x','1990-01-01');db.identity_link('BIO1','person1','x','1990-01-01')
    vid=db.article(url='https://nat1.example/a',title='Congress candidate Alex Rowan is praised',candidate_ids=['C1'],published_at='2026-09-20')
    class Stub:
        model_id='test-model'
        def predict(self,x): return dict(sentiment=.5,confidence=.6,probabilities={'positive':.6,'negative':.1,'neutral':.3})
    AnalysisAgent(db).annotate(Stub())
    assert db.rows('SELECT entity_status FROM cs_annotations WHERE version_id=?',(vid,))[0]['entity_status']=='exact_name_context'


def test_coordinator_offline_no_claim_of_live_requests(db,tmp_path):
    result=SentimentWorkflow(db).run(select_cohort(db),'2026-10-06',checkpoint_path=tmp_path/'backup.sqlite')
    assert result['collection']['status']=='disabled'
    assert (tmp_path/'backup.sqlite').exists()
    assert {r['agent'] for r in db.rows('SELECT * FROM sa_events')} >= {'SourceAgent','Coordinator','AnalysisAgent'}


def test_coordinator_collects_from_fixture_provider(db):
    CollectionAgent(db).plan_campaign(select_cohort(db),'2026-09-01','2026-09-30')
    class FakeProvider:
        name='mediacloud'
        def page(self,p):return ([{'url':'https://'+p['domains'][0]+'/test','title':'Congress candidate Alex Rowan discussion','published_at':'2026-09-20'}],None,False)
    client=SimpleNamespace(requests_used=0)
    result=SentimentWorkflow(db).run(select_cohort(db),'2026-10-06',run_network=True,
           provider_override=FakeProvider(),client_override=client,budget=RunBudget(max_search_jobs=1))
    assert result['collection']['processed']==1
    assert result['collection']['processed_hits']==1


def test_export_no_body(db,tmp_path):
    article(db,'nat1.example','a',body='PRIVATE_ARTICLE_BODY '*100)
    folder=SentimentWorkflow(db).export(tmp_path/'exports')
    assert 'PRIVATE_ARTICLE_BODY' not in ''.join(p.read_text() for p in folder.iterdir())


def test_congress_import_no_ballot_assumption(db,tmp_path):
    p=tmp_path/'officials.yaml'
    p.write_text('''- id:\n    bioguide: X0001\n    fec: [C1]\n  name:\n    first: Alex\n    last: Rowan\n  terms:\n  - type: rep\n    start: '1991-01-03'\n    end: '1993-01-03'\n    state: MI\n    district: 1\n    party: Example\n''')
    result=import_congress_yaml(db,p,source_url='synthetic://cc0',min_year=1990,observed_at='2026-10-06')
    assert result['terms']==1 and result['existing_fec_links']==1
    assert db.rows('SELECT COUNT(*) n FROM cs_roster')[0]['n']==0


def test_standing_bridge_missing_components_are_not_imputed(db):
    from charisma_lab.agents_analysis import combine_standing
    features=snapshot(db,'C1','2026-10-06',state='MI',config=cfg())
    result=combine_standing(db,features,geography='MI',population='registered_voters')
    assert result['charisma_score'] is None
    assert result['favorability_score'] is None
    assert result['forecast_ready'] is False
    assert 'favorability_missing' in result['flags']
    with pytest.raises(ValueError):
        combine_standing(db,features,geography='MI',population='registered_voters',weights=(1,1,1))


def test_source_resolution_priority_domains(db):
    # The pilot can resolve relevant national/local sources first rather than
    # alphabetically spending its entire request budget on unrelated states.
    db.con.execute('UPDATE cs_outlets SET media_cloud_id=NULL')
    class Client:
        def get(self,url,**kw):
            domain=kw['params']['name']
            return SimpleNamespace(json=lambda:{'results':[{'id':999,'homepage':'https://'+domain}], 'next':None})
    rows=SourceAgent(db).resolve(Client(),'fixture',domains=['mi2.example'],max_sources=1)
    assert rows[0]['domain']=='mi2.example'
    assert db.rows("SELECT media_cloud_id FROM cs_outlets WHERE domain='mi2.example'")[0]['media_cloud_id']==999


def test_monthly_history_resolves_local_state_from_active_service(db):
    db.identity_link('C1','person:C1','synthetic://history','1990-01-01')
    db.term(person_id='person:C1',office='H',state='MI',start_date='2025-01-03T00:00:00Z',
            end_date='2027-01-03T00:00:00Z',available_at='2025-01-03',evidence_url='synthetic://history')
    rows=AnalysisAgent(db).monthly_history('C1','2026-09-01','2026-10-06',config=cfg())
    assert all(r['state']=='MI' and r['in_office_at_cutoff'] for r in rows)
