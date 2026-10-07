import csv,json,math,sqlite3,zipfile
from datetime import datetime,timedelta,timezone
import pytest
from charisma_lab.store import Store,read_only
from charisma_lab.util import dt,iso,canonical_url,months,normal
from charisma_lab.scoring import ScoreConfig,decay,score_candidate,news
from charisma_lab import importers


def csvfile(tmp_path,name,rows):
    p=tmp_path/name
    with p.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    return p


def survey(store,tmp_path,**changes):
    r=dict(candidate_id='C1',wave_id='w1',pollster='Poll A',geography='US',population='rv',metric='favorability',
      field_end='2024-09-10',available_at='2024-09-11',source_url='synthetic://poll',favorable=.60,unfavorable=.30,sample_size=1000)
    r.update(changes); importers.import_surveys(store,csvfile(tmp_path,'poll.csv',[r]))


def pedigree(store,tmp_path,**changes):
    r=dict(candidate_id='C1',effective_at='2024-09-01',available_at='2024-09-02',years_elected=8,
      general_wins=3,general_contests=4,mean_outperformance_pp=6,baseline_train_end='2020-01-01',history_complete=1,source_url='synthetic://history')
    r.update(changes); importers.import_pedigree(store,csvfile(tmp_path,'pedigree.csv',[r]))


def article(store,i,sentiment,**kw):
    values=dict(url=f'https://outlet{i%3}.example/article-{i}',title=f'Alex Rowan campaign report number {i}',candidate_ids=['C1'],
       body=f'Alex Rowan discussed policy proposal {i} in a Senate campaign. '+f'This is synthetic article {i}. '*20,
       published_at='2024-09-01T12:00:00Z',retrieved_at='2024-09-01T13:00:00Z',availability_basis='synthetic_fixture')
    values.update(kw);vid=store.article(**values)
    store.annotation(vid,'C1',sentiment,evidence=values['title'],
                     annotated_at=values.get('published_at') or values.get('indexed_at') or values['retrieved_at'],
                     annotation_basis='synthetic_fixture',annotation_evidence_url='synthetic://article-label-fixture')
    store.con.commit();return vid


def score(store,**kw):
    return score_candidate(store,'C1','2024-10-01',geography='US',population='rv',**kw)

@pytest.mark.parametrize('days,expected',[(0,1),(90,.5),(180,.25),(360,.0625)])
def test_decay(days,expected): assert decay(days,90)==pytest.approx(expected)

@pytest.mark.parametrize('args',[(-1,90),(1,0),(1,-5)])
def test_bad_decay(args):
    with pytest.raises(ValueError):decay(*args)

def test_date_conservative():
    assert iso('2024-01-01')=='2024-01-01T23:59:59+00:00'
    with pytest.raises(ValueError):dt('2024-01-01T12:30:00')

def test_month_windows():
    chunks=list(months('2024-01-15','2024-03-05'))
    assert len(chunks)==3 and chunks[0][1]==chunks[1][0] and chunks[1][1]==chunks[2][0]

def test_canonical_url():
    assert canonical_url('https://a.example/x?id=7&utm_source=foo#title')=='https://a.example/x?id=7'
    with pytest.raises(ValueError): canonical_url('file:///etc/passwd')

def test_readonly_missing_does_not_create(tmp_path):
    p=tmp_path/'missing.sqlite'
    with pytest.raises(FileNotFoundError):read_only(p)
    assert not p.exists()

def test_unrelated_table_preserved(tmp_path):
    p=tmp_path/'source.sqlite'
    with sqlite3.connect(p) as c:
        c.execute('CREATE TABLE existing(x)');c.execute('INSERT INTO existing VALUES(7)')
    before=p.read_bytes()
    with pytest.raises(ValueError,match='dedicated sentiment database'): Store(p)
    assert p.read_bytes()==before
    with sqlite3.connect(p) as c:
        assert c.execute('SELECT x FROM existing').fetchone()[0]==7
        assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'cs_%'").fetchone()[0]==0

def test_funding_schema_guard(store,tmp_path):
    p=tmp_path/'bad.sqlite'
    with sqlite3.connect(p) as c:c.execute('CREATE TABLE nothing_here(x)')
    with pytest.raises(ValueError,match='Available tables'):importers.import_funding(store,p)

def test_funding_schema_integration(store,tmp_path):
    p=tmp_path/'funding.sqlite'
    with sqlite3.connect(p) as c:
        c.execute('CREATE TABLE federal_candidate_cycle(candidate_id,candidate_name,finance_cycle,office,state,district,party,total_receipts_usd)')
        c.execute("INSERT INTO federal_candidate_cycle VALUES('H12345678','VALE, JORDAN',2024,'H','CA','12','DEM',1000000)")
    before=p.read_bytes()
    assert importers.import_funding(store,p,[2024])==1
    assert p.read_bytes()==before
    row=store.rows("SELECT * FROM cs_candidate_cycles WHERE candidate_id='H12345678'")[0]
    assert row['roster_status']=='registry_only' and row['target_election_year'] is None
    assert store.con.execute('SELECT COUNT(*) FROM cs_pedigree').fetchone()[0]==0

def test_fec_mock_file(store,tmp_path):
    p=tmp_path/'cn.zip'
    row=['H12345678','VALE, JORDAN','DEM','2024','CA','H','12','I','C','C00000001','street','','town','CA','00000']
    with zipfile.ZipFile(p,'w') as z:z.writestr('cn.txt','|'.join(row)+'\n')
    assert importers.import_fec_zip(store,p,2024)==1
    assert 'street' not in str(store.status())

def test_no_implicit_composite(store):
    r=score(store)
    assert r['charisma_score'] is None and r['favorability_score'] is None
    assert not r['forecast_ready']

def test_future_survey_excluded(store,tmp_path):
    survey(store,tmp_path,available_at='2024-10-02')
    assert score(store)['favorability_score'] is None

def test_future_field_end_rejected(store,tmp_path):
    with pytest.raises(ValueError): survey(store,tmp_path,field_end='2024-10-01')

def test_poll_fraction_guard(store,tmp_path):
    with pytest.raises(ValueError):survey(store,tmp_path,favorable=60)

def test_approval_not_favorability(store,tmp_path):
    survey(store,tmp_path,metric='approval')
    assert score(store)['favorability_score'] is None

def test_geographic_poll_not_reused(store,tmp_path):
    survey(store,tmp_path,geography='CA-12')
    assert score(store)['favorability_score'] is None

def test_survey_revisions_one_wave(store,tmp_path):
    survey(store,tmp_path)
    survey(store,tmp_path,available_at='2024-09-12',favorable=.50,unfavorable=.40)
    r=score(store)
    assert r['favorability']['waves']==1 and r['favorability_score']==pytest.approx(55)

def test_equal_component_weights(store,tmp_path):
    survey(store,tmp_path);pedigree(store,tmp_path)
    for i in range(6):article(store,i,.40)
    r=score(store)
    assert r['favorability_score']==pytest.approx(65)
    assert r['recency_score']==pytest.approx(70)
    assert r['charisma_score']==pytest.approx(sum(r[k] for k in ['favorability_score','recency_score','pedigree_score'])/3)
    assert r['forecast_ready'] is False

def test_latest_bad_news_deteriorates_score(store):
    for i in range(6):article(store,i,.8,published_at='2024-04-01T12:00:00Z',retrieved_at='2024-04-01T13:00:00Z')
    before=score(store)['recency_score']
    for i in range(6,12):article(store,i,-.9,published_at='2024-09-25T12:00:00Z',retrieved_at='2024-09-25T13:00:00Z')
    after=score(store)
    assert after['recency_score']<before and after['recency']['momentum_30_minus_180']<0

def test_future_article_excluded(store):
    article(store,0,1,published_at='2024-10-02T12:00:00Z',retrieved_at='2024-10-02T13:00:00Z')
    assert score(store)['recency']['unique_articles']==0

def test_late_version_strict_vs_research(store):
    article(store,0,.9,retrieved_at='2026-01-01T12:00:00Z')
    assert score(store)['recency']['unique_articles']==0
    r=score(store,mode='research')
    assert r['recency']['unique_articles']==1 and 'historical_content_version_unverified' in r['flags']

def test_backdating_requires_archive_evidence(store):
    with pytest.raises(ValueError,match='Backdating'):
        article(store,0,.5,retrieved_at='2026-01-01',available_at='2024-09-01')

def test_verified_archive_version(store):
    article(store,0,.5,retrieved_at='2026-01-01',available_at='2024-09-01',
            availability_basis='verified_archive_version',archive_evidence_url='https://archive.example/verified-version')
    assert score(store)['recency']['unique_articles']==1

def test_index_date_not_true_publication(store):
    article(store,0,.5,published_at=None,indexed_at='2024-09-01T12:00:00Z')
    assert score(store)['recency']['unique_articles']==0
    assert score(store,mode='research')['recency']['unique_articles']==1

def test_unknown_entity_does_not_count(store):
    vid=article(store,0,.8)
    store.con.execute("UPDATE cs_annotations SET entity_status='needs_review' WHERE version_id=?",(vid,));store.con.commit()
    assert score(store)['recency']['unique_articles']==0

def test_unreviewed_annotation_filter(store):
    vid=article(store,0,.8)
    store.con.execute('UPDATE cs_annotations SET reviewed=0 WHERE version_id=?',(vid,));store.con.commit()
    assert score(store,config=ScoreConfig(require_reviewed=True))['recency']['unique_articles']==0

def test_exact_duplicate_not_independent(store):
    for i in range(6):article(store,i,.8,body='Alex Rowan campaign synthetic syndicated copy. '*20)
    r=score(store)
    assert r['recency']['unique_articles']==1 and r['recency_score'] is None

def test_one_outlet_not_full_news_score(store):
    for i in range(6):article(store,i,.8,url=f'https://single.example/a-{i}')
    r=score(store)
    assert r['recency']['unique_articles']==6 and r['recency_score'] is None

def test_outlet_balanced_not_article_count_balanced(store):
    for i in range(10):article(store,i,1,url=f'https://one.example/a-{i}')
    article(store,10,-1,url='https://two.example/a')
    article(store,11,0,url='https://three.example/a')
    assert score(store)['recency_score']==pytest.approx(50)

def test_unknown_pedigree_is_not_newcomer(store,tmp_path):
    pedigree(store,tmp_path,history_complete=0)
    assert score(store)['pedigree_score'] is None

def test_verified_newcomer_prior_is_labeled(store,tmp_path):
    pedigree(store,tmp_path,years_elected=0,general_wins=0,general_contests=0,mean_outperformance_pp='',baseline_train_end='')
    r=score(store)
    assert r['pedigree_score']==pytest.approx(50/3)
    assert 'verified_newcomer_neutral_outperformance_prior' in r['flags']

def test_future_pedigree_ignored(store,tmp_path):
    pedigree(store,tmp_path,effective_at='2024-11-06',available_at='2024-11-07')
    assert score(store)['pedigree_score'] is None

def test_impossible_pedigree_rejected(store,tmp_path):
    with pytest.raises(ValueError):pedigree(store,tmp_path,general_wins=9)

def test_no_registry_asof_no_strict_composite(store,tmp_path):
    survey(store,tmp_path);pedigree(store,tmp_path)
    for i in range(6):article(store,i,.4)
    store.con.execute("UPDATE cs_candidates SET known_at='2026-01-01T00:00:00+00:00'");store.con.commit()
    assert score(store)['charisma_score'] is None
    assert score(store,mode='research')['charisma_score'] is not None

def test_roster_not_inferred_from_finance(store,tmp_path):
    survey(store,tmp_path);pedigree(store,tmp_path)
    for i in range(6):article(store,i,.4)
    assert score(store,election_id='2024-S-TEST-SPECIAL')['charisma_score'] is None

def test_backup_consistent(store,tmp_path):
    destination=tmp_path/'backup.sqlite';store.backup(destination)
    with sqlite3.connect(destination) as con:
        assert con.execute('SELECT COUNT(*) FROM cs_candidates').fetchone()[0]==1
    with pytest.raises(ValueError):store.backup(store.path)

def test_score_snapshot_idempotent(store):
    score(store);score(store)
    assert store.con.execute('SELECT COUNT(*) FROM cs_scores').fetchone()[0]==1

@pytest.mark.parametrize('weights',[(.5,.5,.5),(1,-1,1),(1,0)])
def test_weight_validation(weights):
    with pytest.raises(ValueError):ScoreConfig(weights=weights)
