import importlib.util
from pathlib import Path
import pandas as pd
import pytest
from charisma_lab import importers
from charisma_lab.scoring import news,ScoreConfig
from charisma_lab.util import dt
from charisma_lab.evaluate import annotation_audit


def test_offline_end_to_end(tmp_path):
    path=Path(__file__).parents[1]/'examples'/'offline_demo.py'
    spec=importlib.util.spec_from_file_location('demo',path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    result=module.run_demo(tmp_path)
    assert len(result)==3 and pd.isna(result.iloc[2].charisma_score)
    assert result.iloc[0].charisma_score > result.iloc[1].charisma_score


def test_subdomain_keeps_panel_outlet(store,tmp_path):
    p=tmp_path/'outlets.csv';p.write_text('domain,name\nnews.example,Synthetic News\n')
    importers.import_outlets(store,p)
    vid=store.article(url='https://politics.news.example/test',title='Alex Rowan Senate campaign',
        candidate_ids=['C1'],published_at='2024-09-01',retrieved_at='2024-09-01')
    store.annotation(vid,'C1',.1,evidence='Alex Rowan Senate campaign',annotated_at='2024-09-01',
                     annotation_basis='synthetic_fixture',annotation_evidence_url='synthetic://article-label-fixture')
    store.con.commit()
    row=store.rows('SELECT outlet FROM cs_articles')[0]
    assert row['outlet']=='news.example'
    assert news(store,'C1',dt('2024-10-01'),ScoreConfig(outlet_domains=('news.example',)),'strict')['unique_articles']==1


def test_gold_audit():
    gold=pd.DataFrame({'true_label':['positive','negative','neutral'],
         'predicted_label':['positive','negative','neutral'],'entity_correct':[1,1,1]})
    assert annotation_audit(gold)['macro_f1']==1


@pytest.mark.parametrize('case',['empty','bad_identity','bad_label'])
def test_gold_audit_bad_values(case):
    df=pd.DataFrame({'true_label':['positive'],'predicted_label':['positive'],'entity_correct':[1]})
    if case=='empty':df=df.iloc[:0]
    if case=='bad_identity':df.loc[0,'entity_correct']=2
    if case=='bad_label':df.loc[0,'true_label']='good'
    with pytest.raises(ValueError):annotation_audit(df)
