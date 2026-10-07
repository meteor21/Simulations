"""Retained-run analysis using synthetic SQLite/artifact fixtures, never GitHub calls."""
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from charisma_lab.transfer import read_bundle
from charisma_lab.transfer import create_bundle

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('analyze_github_pilot', ROOT / 'scripts/analyze_github_pilot.py')
script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(script)
RUN = '37680664034'


@pytest.fixture
def artifacts(tmp_path,monkeypatch):
    monkeypatch.setenv('GITHUB_REPOSITORY','synthetic/repository')
    monkeypatch.setenv('GITHUB_SHA','synthetic-analysis-commit')
    fixture_db=tmp_path/'synthetic.sqlite'
    with sqlite3.connect(fixture_db) as con:
        con.execute('CREATE TABLE synthetic_fixture(value TEXT)')
        con.execute("INSERT INTO synthetic_fixture VALUES('SYNTHETIC: not real election data')")
    original={'status':'blocked','network_requested':True,'credential_present':True,
        'http_attempts_total':16,'blockers':['Source panel incomplete; fixture evidence'],
        'queue':[{'provider':'mediacloud','status':'pending','jobs':3}],
        'source_resolution':[{'domain':'synthetic.example','status':'not_found','raw_response':'DO NOT PUBLISH'}],
        'run':{'collection':{'processed':2,'processed_hits':3,'blocked':1,'errors':0}}}
    metadata={'total_count':2,'artifacts':[
        {'name':'midterm-live-pilot-state','expired':False,'size_in_bytes':fixture_db.stat().st_size,
         'workflow_run':{'id':int(RUN)}},
        {'name':f'midterm-real-results-{RUN}','expired':False,'size_in_bytes':1000,
         'workflow_run':{'id':int(RUN)}}]}
    state={'db':fixture_db,'original':original,'metadata':metadata,'calls':[],
           'state_prefix':'','report_prefix':'','analysis_calls':[]}
    def fake_gh(*args):
        state['calls'].append(args)
        if args[0]=='api': return json.dumps(metadata)
        assert args[:3]==('run','download',RUN)
        destination=Path(args[args.index('--dir')+1])
        name=args[args.index('--name')+1]
        if name=='midterm-live-pilot-state':
            target=destination/state['state_prefix']/'pilot.sqlite'
            target.parent.mkdir(parents=True)
            shutil.copyfile(fixture_db,target)
        else:
            assert name==f'midterm-real-results-{RUN}'
            target=destination/state['report_prefix']/'pilot_report.json'
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(original))
            if state.get('original_bundle'):
                folder=destination/'synthetic-exports'
                folder.mkdir()
                (folder/'candidate_sentiment_summary.csv').write_text('candidate_id\nSYNTHETIC_FIXTURE\n')
                create_bundle({'agents':folder},destination/'real-analysis.zip',dataset_kind='real',
                              source_commit='synthetic-collection-commit')
        return ''
    def fake_analyze(output,**kwargs):
        assert kwargs=={'analyze_existing':True}
        assert (output/'pilot.sqlite').read_bytes()==fixture_db.read_bytes()
        state['analysis_calls'].append((output,kwargs))
        exports=output/'exports'
        exports.mkdir()
        (exports/'candidate_sentiment_summary.csv').write_text(
            'candidate_id,media_recency_score\nSYNTHETIC_PERSON,\n')
        return {'status':'analyzed_partial','analysis_only':True,'network_requested':False,'http_attempts_this_run':0,
                'http_attempts_total':16,'selected_candidates':24}
    monkeypatch.setattr(script,'gh',fake_gh)
    monkeypatch.setattr(script,'run_pilot',fake_analyze)
    return state


@pytest.mark.parametrize('prefix',['','live-pilot','artifacts/live-pilot'])
def test_same_run_restore_preserves_original_blockers_and_exports_offline(tmp_path,artifacts,capsys,prefix):
    artifacts['state_prefix']=artifacts['report_prefix']=prefix
    output=tmp_path/'analysis'
    report=script.analyze(RUN,output,tmp_path/'analysis.zip')
    assert len(artifacts['calls'])==3
    assert artifacts['calls'][0][1]==f'repos/synthetic/repository/actions/runs/{RUN}/artifacts?per_page=100'
    assert len(artifacts['analysis_calls'])==1
    assert report['source_run_id']==int(RUN)
    assert report['original_pilot_report']==artifacts['original']
    assert report['analysis_only'] is True and report['network_requested'] is False
    assert report['bundle_created'] is True and report['provider_requests_made']==0
    assert report['analysis']['http_attempts_total']==16
    assert json.loads((output/'analysis_report.json').read_text())==report
    manifest,files=read_bundle(tmp_path/'analysis.zip')
    assert manifest['dataset_kind']=='real'  # Packaging contract; fixture rows are explicitly synthetic.
    assert manifest['source_commit']=='synthetic-analysis-commit'
    assert b'SYNTHETIC_PERSON' in files['agents/candidate_sentiment_summary.csv']
    notice=capsys.readouterr().out
    assert '::notice title=Previous collection completeness::' in notice
    assert 'Source panel incomplete' in notice and 'processed_hits' in notice
    assert 'http_attempts_total' in notice and 'pending' in notice
    assert 'DO NOT PUBLISH' not in notice


@pytest.mark.parametrize('run_id',['../123','1;echo unsafe','-1','0','abc',True])
def test_run_id_validation_precedes_any_github_operation(tmp_path,artifacts,run_id):
    with pytest.raises(ValueError,match='positive numeric'):
        script.analyze(run_id,tmp_path/'analysis',tmp_path/'analysis.zip')
    assert artifacts['calls']==artifacts['analysis_calls']==[]


def test_existing_election_database_is_never_overwritten(tmp_path,artifacts):
    output=tmp_path/'existing'
    output.mkdir()
    target=output/'pilot.sqlite'
    target.write_bytes(b'USER DATABASE MUST REMAIN')
    with pytest.raises(ValueError,match='Refusing to overwrite'):
        script.analyze(RUN,output,tmp_path/'analysis.zip')
    assert target.read_bytes()==b'USER DATABASE MUST REMAIN'
    assert artifacts['calls']==artifacts['analysis_calls']==[]


def test_existing_bundle_is_not_overwritten(tmp_path,artifacts):
    bundle=tmp_path/'analysis.zip'
    bundle.write_bytes(b'USER BUNDLE')
    with pytest.raises(ValueError,match='existing files'):
        script.analyze(RUN,tmp_path/'analysis',bundle)
    assert bundle.read_bytes()==b'USER BUNDLE'
    assert artifacts['calls']==[]


def test_missing_original_report_artifact_has_no_fresh_crawl_fallback(tmp_path,artifacts):
    artifacts['metadata']['artifacts'].pop()
    with pytest.raises(ValueError,match=f'midterm-real-results-{RUN} is missing'):
        script.analyze(RUN,tmp_path/'analysis',tmp_path/'analysis.zip')
    assert artifacts['analysis_calls']==[]
    assert not (tmp_path/'analysis/pilot.sqlite').exists()


def test_wrong_run_artifact_rejected_before_download(tmp_path,artifacts):
    artifacts['metadata']['artifacts'][0]['workflow_run']['id']=1
    with pytest.raises(ValueError,match='different source run'):
        script.analyze(RUN,tmp_path/'analysis',tmp_path/'analysis.zip')
    assert len(artifacts['calls'])==1 and not artifacts['analysis_calls']


def test_oversize_metadata_rejected_before_download(tmp_path,artifacts):
    artifacts['metadata']['artifacts'][0]['size_in_bytes']=script.MAX_ARTIFACT_BYTES+1
    with pytest.raises(ValueError,match='size limit'):
        script.analyze(RUN,tmp_path/'analysis',tmp_path/'analysis.zip')
    assert len(artifacts['calls'])==1 and not artifacts['analysis_calls']


def test_extracted_symlink_rejected(tmp_path):
    tree=tmp_path/'artifact'
    tree.mkdir()
    source=tmp_path/'outside.sqlite'
    source.write_bytes(b'SYNTHETIC')
    (tree/'pilot.sqlite').symlink_to(source)
    with pytest.raises(ValueError,match='symlinks'):
        script.locate_artifact_file(tree,'pilot.sqlite',script.MAX_CHECKPOINT_BYTES)


def test_oversize_extracted_report_rejected(tmp_path):
    tree=tmp_path/'artifact'
    tree.mkdir()
    with (tree/'pilot_report.json').open('wb') as stream: stream.truncate(script.MAX_REPORT_BYTES+1)
    with pytest.raises(ValueError,match='size limit'):
        script.locate_artifact_file(tree,'pilot_report.json',script.MAX_REPORT_BYTES)


def test_output_symlink_is_rejected_before_github(tmp_path,artifacts):
    real=tmp_path/'real'
    real.mkdir()
    link=tmp_path/'link'
    link.symlink_to(real,target_is_directory=True)
    with pytest.raises(ValueError,match='Symlink'):
        script.analyze(RUN,link,tmp_path/'analysis.zip')
    assert artifacts['calls']==[]


def test_analysis_failure_retains_original_report(tmp_path,artifacts,monkeypatch):
    def failure(*args,**kwargs): raise RuntimeError('sensitive internal exception must not be recorded')
    monkeypatch.setattr(script,'run_pilot',failure)
    with pytest.raises(RuntimeError): script.analyze(RUN,tmp_path/'analysis',tmp_path/'analysis.zip')
    report=json.loads((tmp_path/'analysis/analysis_report.json').read_text())
    assert report['original_pilot_report']==artifacts['original']
    assert report['analysis_error_type']=='RuntimeError' and report['bundle_created'] is False
    assert 'sensitive internal' not in json.dumps(report)


def test_collection_and_analysis_code_revisions_remain_distinct(tmp_path,artifacts):
    artifacts['original_bundle']=True
    report=script.analyze(RUN,tmp_path/'analysis',tmp_path/'analysis.zip')
    assert report['collection_source_commit']=='synthetic-collection-commit'
    assert report['analysis_source_commit']=='synthetic-analysis-commit'


def test_blocked_checkpoint_cannot_be_reported_as_successful_analysis(tmp_path, artifacts, monkeypatch):
    monkeypatch.setattr(script, 'run_pilot', lambda *args, **kwargs: {
        'status': 'blocked', 'network_requested': False, 'http_attempts_this_run': 0,
        'blockers': ['Candidate roster changed after requests were charged']})
    with pytest.raises(RuntimeError, match='Offline checkpoint analysis failed'):
        script.analyze(RUN, tmp_path/'analysis', tmp_path/'analysis.zip')
    report = json.loads((tmp_path/'analysis/analysis_report.json').read_text())
    assert report['bundle_created'] is False
    assert report['original_pilot_report'] == artifacts['original']
    assert not (tmp_path/'analysis.zip').exists()
