import csv
from datetime import datetime,timezone
import pandas as pd
import pytest
from charisma_lab.history import merged_service_years,build_pedigree_csv
from charisma_lab.util import dt
from charisma_lab.evaluate import walk_forward

def test_service_intervals_union_and_future_clip():
    intervals=[(dt('2020-01-01'),dt('2022-01-01')),(dt('2021-01-01'),dt('2025-01-01'))]
    years=merged_service_years(intervals,dt('2024-01-01'))
    assert years==pytest.approx(4,abs=.01)

def make_df():
    return pd.DataFrame([dict(election_id=f'{y}-{i}',cycle=y,as_of=f'{y}-10-01',election_date=f'{y}-11-01',
          won=i%2,baseline=(i-5)/10,standing=i/10 if y>2020 else None)
          for y in [2020,2022,2024] for i in range(12)])

def test_expanding_cycle_evaluation():
    pytest.importorskip('sklearn')
    metrics,preds=walk_forward(make_df(),['baseline'],['standing'])
    assert len(metrics)==4
    assert metrics.loc[metrics.test_cycle==2022,'train_races'].eq(12).all()
    assert metrics.loc[metrics.test_cycle==2024,'train_races'].eq(24).all()
    assert preds.p.between(0,1).all()

def test_duplicate_races_rejected():
    df=make_df();df=pd.concat([df,df.iloc[[0]]])
    with pytest.raises(ValueError,match='ONE race'):walk_forward(df,['baseline'],['standing'])

def test_future_snapshot_rejected():
    df=make_df();df.loc[0,'as_of']='2025-01-01'
    with pytest.raises(ValueError,match='on or after'):walk_forward(df,['baseline'],['standing'])
