"""Targeted, anonymized NLI baseline. Model confidence is NOT calibrated accuracy."""
from __future__ import annotations
import json
import re
from collections import Counter
from .store import unpack_body
from .util import normal,digest

MODEL='MoritzLaurer/deberta-v3-base-zeroshot-v2.0-c'


def name_pattern(alias):
    words=re.findall(r'\w+',alias,re.UNICODE)
    if not words: return r'(?!)'  # Invalid aliases must not become zero-width matches.
    return r'(?<!\w)'+r'[\W_]+'.join(re.escape(w) for w in words)+r'(?!\w)'


def target_context(text,aliases,*,max_windows=4,max_chars=1500):
    patterns=[re.compile(name_pattern(a),re.I) for a in sorted(aliases,key=len,reverse=True)]
    hits=sorted({m.start() for p in patterns for m in p.finditer(text)})
    if not hits: return [],''
    windows=[]
    for pos in hits:
        if windows and pos<windows[-1][1]: continue
        windows.append((max(0,pos-300),min(len(text),pos+max_chars-300)))
        if len(windows)>=max_windows: break
    originals=[text[a:b] for a,b in windows]
    masked=[]
    for s in originals:
        for p in patterns: s=p.sub('TARGET_CANDIDATE',s)
        # A surname may belong to a rival or relative even after a full-name hit.
        # Leave unresolved surname references intact; mask verified full aliases only.
        masked.append(s)
    return masked,'\n[...]\n'.join(originals)[:2200]


class NLIAnnotator:
    def __init__(self,model=MODEL,revision=None,device=-1,batch_size=8,pipeline_override=None):
        self.batch_size=batch_size
        if pipeline_override is None:
            from transformers import pipeline
            kwargs={'model':model,'device':device}
            if revision: kwargs['revision']=revision
            self.pipe=pipeline('zero-shot-classification',**kwargs)
            revision=getattr(self.pipe.model.config,'_commit_hash',None) or revision or 'unresolved'
        else:
            self.pipe=pipeline_override; revision=revision or 'test-double'
        self.model_id=model+'@'+revision+':target-nli-v2'
        self.labels=[
            'the text portrays TARGET_CANDIDATE favorably',
            'the text portrays TARGET_CANDIDATE unfavorably',
            'the text is neutral or mixed about TARGET_CANDIDATE']

    def predict(self,contexts):
        if not contexts: raise ValueError('No target-specific context to annotate')
        # Short contexts are intentional; full document truncation can remove the named target.
        out=self.pipe(contexts,candidate_labels=self.labels,hypothesis_template='{}.',multi_label=False,
                      batch_size=self.batch_size)
        if isinstance(out,dict): out=[out]
        positive=negative=neutral=0.
        for row in out:
            scores=dict(zip(row['labels'],row['scores']))
            positive+=float(scores[self.labels[0]]); negative+=float(scores[self.labels[1]])
            neutral+=float(scores[self.labels[2]])
        n=len(out); positive/=n; negative/=n; neutral/=n
        return {'sentiment':positive-negative,'confidence':max(positive,negative,neutral),
                'probabilities':{'positive':positive,'negative':negative,'neutral_or_mixed':neutral}}


def annotate_pending(store,annotator,*,max_pairs=100,checkpoint_path=None):
    rows=store.rows('''SELECT v.*,c.candidate_id,c.aliases_json,c.name FROM cs_versions v
       JOIN cs_article_candidates ac USING(article_id) JOIN cs_candidates c USING(candidate_id)
       WHERE NOT EXISTS(SELECT 1 FROM cs_annotations n WHERE n.version_id=v.version_id
         AND n.candidate_id=c.candidate_id AND n.model_id=?)
       ORDER BY v.retrieved_at,v.version_id,c.candidate_id LIMIT ?''',(annotator.model_id,max_pairs))
    alias_counts=Counter()
    for c in store.rows('SELECT aliases_json FROM cs_candidates'):
        alias_counts.update(set(normal(a) for a in json.loads(c['aliases_json'])))
    counts={'annotated':0,'needs_review':0,'no_name_match':0}
    try:
        for row in rows:
            body=unpack_body(row); text=row['title']+'\n'+body
            aliases=json.loads(row['aliases_json'])
            contexts,evidence=target_context(text,aliases)
            if not contexts:
                store.annotation(row['version_id'],row['candidate_id'],0.,model_id=annotator.model_id,
                    confidence=0.,entity_status='no_match',reviewed=False,evidence=row['title'] or '[No target text]',
                    diagnostics={'reason':'full-name alias absent; surname-only matching not attempted'})
                counts['no_name_match']+=1; store.con.commit(); continue
            matched=[a for a in aliases if re.search(name_pattern(a),text,re.I)]
            # Full-name homonyms are not automatically assigned. Context matching is still only a heuristic.
            unique_name=any(alias_counts[normal(a)]==1 for a in matched)
            office_context=bool(re.search(r'\b(senat\w*|congress\w*|presiden\w*|representative|candidate|campaign|election|governor|legislatur\w*)\b',text,re.I))
            entity='exact_name_context' if unique_name and office_context else 'needs_review'
            pred=annotator.predict(contexts)
            diag={'probabilities':pred['probabilities'],'context_windows':len(contexts),'body_available':bool(body),
                  'masking':'full aliases only; surname references unresolved','validated_on_political_gold_set':False,
                  'quoted_or_attributed_claim_present':bool(re.search(r'[“”"]|\b(accused|alleged|claimed)\b',evidence,re.I)),
                  'warnings':['portrayal proxy, not proven outlet endorsement','contextual excerpts may omit nuance']}
            store.annotation(row['version_id'],row['candidate_id'],pred['sentiment'],model_id=annotator.model_id,
                  confidence=pred['confidence'],entity_status=entity,reviewed=False,evidence=evidence,diagnostics=diag)
            store.con.commit(); counts['annotated']+=1
            if entity=='needs_review': counts['needs_review']+=1
            if checkpoint_path and counts['annotated']%25==0: store.backup(checkpoint_path)
    finally:
        if checkpoint_path: store.backup(checkpoint_path)
    return counts
