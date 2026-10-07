"""End-to-end SYNTHETIC example. No real politicians, polls, articles, or model predictions."""
from __future__ import annotations
import csv
from pathlib import Path
import pandas as pd
from charisma_lab.store import Store
from charisma_lab.importers import import_surveys, import_pedigree
from charisma_lab.scoring import ScoreConfig, score_candidate
from charisma_lab.util import dumps


def write_csv(path, rows):
    with Path(path).open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run_demo(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    db = root / 'SYNTHETIC_DEMO.sqlite'
    with Store(db) as store:
        for cid, name in [('SYN-A', 'Alex Rowan'), ('SYN-B', 'Jordan Vale')]:
            store.candidate(cid, name, known_at='2020-01-01', source_url='synthetic://identity-fixture')
        polls = []
        for wave, date, f, u in [('spring', '2024-03-21', .65, .25), ('autumn', '2024-09-26', .38, .53)]:
            polls.append(dict(candidate_id='SYN-A', wave_id=wave, pollster='Synthetic Pollster',
                geography='US', population='rv', metric='favorability', field_end=date,
                available_at=date, source_url='synthetic://poll-fixture/' + wave,
                favorable=f, unfavorable=u, sample_size=1000, dont_know=1-f-u))
        write_csv(root / 'synthetic_surveys.csv', polls)
        import_surveys(store, root / 'synthetic_surveys.csv')
        p = dict(candidate_id='SYN-A', effective_at='2024-03-01', available_at='2024-03-01',
            years_elected=12, general_wins=5, general_contests=6, mean_outperformance_pp=8,
            baseline_train_end='2010-01-01', history_complete=1, source_url='synthetic://pedigree-fixture')
        write_csv(root / 'synthetic_pedigree.csv', [p])
        import_pedigree(store, root / 'synthetic_pedigree.csv')
        for period, date, sentiment in [('spring', '2024-03-20', .6), ('autumn', '2024-09-25', -.7)]:
            for i in range(6):
                title = f'SYNTHETIC {period} Senate campaign report {i}: Alex Rowan'
                body = title + '. ' + f'Invented test document {period} number {i}. ' * 25
                vid = store.article(url=f'https://outlet{i % 3}.example/{period}-{i}',
                    title=title, body=body, candidate_ids=['SYN-A'], published_at=date,
                    retrieved_at=date, availability_basis='synthetic_fixture',
                    rights_note='Generated synthetic fixture; not real journalism.')
                store.annotation(vid, 'SYN-A', sentiment, model_id='synthetic:known-fixture-label',
                    reviewed=True, evidence=title, diagnostics={'synthetic': True},annotated_at=date,
                    annotation_basis='synthetic_fixture',annotation_evidence_url='synthetic://known-fixture-label')
        store.con.commit()
        cfg = ScoreConfig(require_reviewed=True, outlet_domains=tuple(f'outlet{i}.example' for i in range(3)))
        results = [score_candidate(store, 'SYN-A', date, geography='US', population='rv', config=cfg)
                   for date in ['2024-03-31', '2024-10-01']]
        results.append(score_candidate(store, 'SYN-B', '2024-10-01', geography='US', population='rv', config=cfg))
        assert results[0]['charisma_score'] > results[1]['charisma_score']
        assert results[0]['pedigree_score'] == results[1]['pedigree_score']
        assert results[2]['charisma_score'] is None
        assert all(r['forecast_ready'] is False for r in results)
        (root / 'synthetic_scores.json').write_text(dumps(results), encoding='utf-8')
        frame = pd.DataFrame([{k: r[k] for k in ['candidate_id', 'as_of', 'favorability_score',
            'recency_score', 'pedigree_score', 'charisma_score', 'forecast_ready']} for r in results])
        frame['dataset'] = 'SYNTHETIC; NOT REAL POLITICAL ESTIMATES'
        frame.to_csv(root / 'synthetic_scores.csv', index=False)
        (root / 'WARNING.txt').write_text('All observations and scores here are synthetic software-test fixtures.\n')
    return frame


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default='reports/demo')
    print(run_demo(parser.parse_args().out).to_string(index=False))
