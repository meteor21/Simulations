"""Race-level, expanding-cycle backtest. No claimed predictive gain until real results are supplied."""
from __future__ import annotations
import numpy as np
import pandas as pd


def walk_forward(data:pd.DataFrame,baseline_features:list[str],extra_features:list[str]):
    """One row per race at a common declared horizon. Numeric features, binary target 'won'.

    Required: election_id,cycle,as_of,election_date,won. All preprocessing is fitted on prior cycles.
    You must construct candidate A/B differences and as-of economic/poll features upstream.
    This tests association/prediction, NOT the causal effect of charisma.
    """
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import make_pipeline
    from sklearn.metrics import brier_score_loss,log_loss
    df=data.copy()
    required=['election_id','cycle','as_of','election_date','won']+baseline_features+extra_features
    missing=set(required)-set(df.columns)
    if missing: raise ValueError('Missing backtest columns: '+str(sorted(missing)))
    identifiers=['election_id','cycle','as_of','election_date']
    if df[identifiers].isna().any().any() or any(df[c].astype(str).str.strip().eq('').any() for c in identifiers):
        raise ValueError('Missing race identity or temporal metadata.')
    features=baseline_features+extra_features
    if set(features)&set(identifiers+['won','outcome_available_at']):
        raise ValueError('Outcome and race metadata cannot be predictor features.')
    cycles=pd.to_numeric(df.cycle,errors='raise')
    if not np.isfinite(cycles).all() or (cycles%1!=0).any(): raise ValueError('Cycles must be finite integers.')
    df['cycle']=cycles.astype(int)
    if df.duplicated(['cycle','election_id']).any():
        raise ValueError('Use ONE race-level row per cycle and election_id, not candidate or snapshot duplicates.')
    asof=pd.to_datetime(df.as_of,utc=True); dates=pd.to_datetime(df.election_date,utc=True)
    if asof.isna().any() or dates.isna().any(): raise ValueError('Missing snapshot or election dates.')
    outcome_dates=pd.to_datetime(df['outcome_available_at'],utc=True) if 'outcome_available_at' in df else dates
    if outcome_dates.isna().any() or (outcome_dates<dates).any():
        raise ValueError('Outcome availability must be observed and on or after the election.')
    if (asof>=dates).any(): raise ValueError('Some snapshots are on or after election time.')
    if not set(df.won.dropna().unique())<={0,1} or df.won.isna().any(): raise ValueError('won must be binary and observed.')
    results=[];predictions=[]
    for cycle in sorted(df.cycle.unique())[1:]:
        train=df[df.cycle<cycle]; test=df[df.cycle==cycle]
        if (outcome_dates.loc[df.cycle<cycle]>=asof.loc[df.cycle==cycle].min()).any():
            raise ValueError('Training outcome was not available before the test snapshot.')
        if train.won.nunique()<2: continue
        for name,cols in [('baseline',baseline_features),('baseline_plus_standing',baseline_features+extra_features)]:
            if not cols: raise ValueError('Provide at least one baseline feature.')
            X=train[cols].apply(pd.to_numeric,errors='raise'); Xt=test[cols].apply(pd.to_numeric,errors='raise')
            pipeline=make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),
                                   StandardScaler(),LogisticRegression(max_iter=2000,C=1))
            pipeline.fit(X,train.won)
            p=pipeline.predict_proba(Xt)[:,1]
            results.append({'test_cycle':int(cycle),'model':name,'train_races':len(train),'test_races':len(test),
                            'brier':float(brier_score_loss(test.won,p)),
                            'log_loss':float(log_loss(test.won,p,labels=[0,1]))})
            predictions.extend({'election_id':rid,'test_cycle':int(cycle),'model':name,'won':int(y),'p':float(prob)}
                               for rid,y,prob in zip(test.election_id,test.won,p))
    return pd.DataFrame(results),pd.DataFrame(predictions)


def annotation_audit(gold:pd.DataFrame):
    """Gold CSV columns: true_label, predicted_label, entity_correct, office, outlet (optional).
    Returns observed evaluation metrics, never a made-up validation status.
    """
    from sklearn.metrics import f1_score,accuracy_score,confusion_matrix
    require={'true_label','predicted_label','entity_correct'}
    if not require<=set(gold): raise ValueError('Missing gold-label columns')
    if gold.empty or not set(gold.entity_correct.unique()) <= {0,1}:
        raise ValueError('Gold set must be nonempty; entity_correct must be binary.')
    labels=['negative','neutral','positive']
    if not (set(gold.true_label)|set(gold.predicted_label))<=set(labels): raise ValueError('Invalid sentiment label')
    report={'n':len(gold),'macro_f1':float(f1_score(gold.true_label,gold.predicted_label,labels=labels,average='macro',zero_division=0)),
            'accuracy':float(accuracy_score(gold.true_label,gold.predicted_label)),
            'entity_accuracy':float(gold.entity_correct.mean()),
            'confusion_matrix':confusion_matrix(gold.true_label,gold.predicted_label,labels=labels).tolist(),
            'labels':labels}
    return report
