"""Political-orientation proposals from an independent source-level corpus.

Never learn outlet ideology from whether it praises a Republican or a Democrat.
No candidate-query corpus is accepted as an independent outlet-bias sample.
"""
from __future__ import annotations
import json
import zlib
from collections import defaultdict
from .util import digest,dumps,iso,now


def import_independent_bias_samples(store,path):
    count=0
    with open(path,encoding='utf-8') as f:
        for line in f:
            if not line.strip(): continue
            r=json.loads(line)
            required=['domain','url','title','body','published_at','available_at','sampling_frame','rights_note','evidence_url']
            if any(not r.get(k) for k in required): raise ValueError('Missing independent bias-sample fields')
            if r['sampling_frame'] not in {'outlet_politics_random','outlet_politics_systematic','human_balanced_outlet_sample'}:
                raise ValueError('Candidate searches cannot be used to estimate general outlet ideology')
            if len(r['body'])<200: raise ValueError('Bias assessment needs substantive permitted text, not only a headline')
            if iso(r['available_at'])<iso(r['published_at']): raise ValueError('Sample availability precedes publication')
            sid=digest([r['domain'],r['url'],r['body']])
            store.con.execute('INSERT OR IGNORE INTO sa_independent_bias_sample VALUES(?,?,?,?,?,?,?,?,?,?)',
                (sid,r['domain'],r['url'],r['title'],zlib.compress(r['body'].encode()),iso(r['published_at']),
                 iso(r['available_at']),r['sampling_frame'],r['rights_note'],r['evidence_url']))
            count+=1
    store.con.commit(); return count


class IdeologyProposer:
    """A zero-shot heuristic, deliberately never an approved source rating.

    Uses the same local transformer pipeline as target annotation, with separate
    hypotheses and version IDs. Class scores are uncalibrated, not uncertainty.
    """
    labels=[
      'the narrator advocates a distinctly left-wing or progressive political position',
      'the narrator advocates a moderately left-leaning political position',
      'the narrator explicitly argues for a centrist or ideologically balanced political position',
      'the narrator advocates a moderately right-leaning political position',
      'the narrator advocates a distinctly right-wing or conservative political position',
      'the narrator reports or quotes political views without a discernible ideological position of their own']
    def __init__(self,nli_annotator):
        self.pipe=nli_annotator.pipe
        self.model_id=nli_annotator.model_id+':ideology-proposal-v1'
        self.batch_size=nli_annotator.batch_size

    def propose(self,store,domain,start,end,*,min_articles=30,max_articles=120):
        if min_articles<10: raise ValueError('Require at least 10 distinct articles; 30+ recommended')
        a,b=iso(start),iso(end)
        rows=store.rows('''SELECT * FROM sa_independent_bias_sample WHERE domain=?
                AND published_at>=? AND published_at<=? ORDER BY sample_id LIMIT ?''',(domain,a,b,max_articles))
        # Deduplicate repeated syndicated content inside the sample.
        unique={digest(zlib.decompress(r['body_z']).decode()):r for r in rows}; rows=list(unique.values())
        if len(rows)<min_articles: return {'domain':domain,'status':'insufficient_independent_sample','articles':len(rows)}
        averages=[]; evidence=[]
        for r in rows:
            body=zlib.decompress(r['body_z']).decode()
            # Explicit deterministic excerpts, never silently feeding truncated whole articles.
            contexts=[body[:1400],body[max(0,len(body)//2-700):len(body)//2+700],body[-1400:]]
            out=self.pipe(contexts,candidate_labels=self.labels,hypothesis_template='{}.',multi_label=False,
                          batch_size=self.batch_size)
            if isinstance(out,dict): out=[out]
            probabilities=[dict(zip(x['labels'],x['scores'])) for x in out]
            avg={k:sum(float(p[k]) for p in probabilities)/len(probabilities) for k in self.labels}
            cue=1-avg[self.labels[-1]]
            score=sum(i*avg[k] for i,k in zip([-2,-1,0,1,2],self.labels[:5]))/max(cue,1e-12)
            averages.append((score,cue)); evidence.append({'url':r['url'],'published_at':r['published_at'],
                 'sample_id':r['sample_id'],'ideological_cue_score':cue,'uncalibrated_ordinal_score':score})
        detected=[score for score,cue in averages if cue>=.65]
        if len(detected)<max(10,len(rows)//3): label='Unknown'; score=None
        else:
            score=sum(detected)/len(detected)
            label='Left' if score< -1.25 else 'Lean Left' if score<-.35 else 'Center' if score<=.35 else 'Lean Right' if score<=1.25 else 'Right'
        aid=store.bias(domain=domain,provider=self.model_id,label=label,valid_from=a,valid_to=b,
            available_at=now(),evidence_url=rows[0]['evidence_url'],method='model_provisional',status='provisional',
            confidence_label='uncalibrated_model_proposal',sample_n=len(rows),
            native_score=score,native_scale='heuristic expected ordinal [-2,+2]; not calibrated to any external provider' if score is not None else '',
            license_note='Analysis of user-supplied permitted corpus; no external provider rating implied',
            metadata={'sample':evidence,'independent_sample_required':True,'trained_for_ideology':False,
                      'human_review_required':True,'model_id':self.model_id,'not_automatically_used_for_features':True})
        store.event('AnalysisAgent','bias_proposal',domain=domain,assessment_id=aid,articles=len(rows),label=label)
        return {'domain':domain,'assessment_id':aid,'articles':len(rows),'status':'provisional_needs_human_review','label':label}
