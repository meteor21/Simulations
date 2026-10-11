"""Publication safety using synthetic GitHub responses; no external mutations."""
import base64
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('publish_dashboard', ROOT / 'scripts/publish_dashboard.py')
script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(script)
REPOSITORY = 'synthetic/Simulations'
HEAD_ONE = {'sha': '1' * 40, 'tree': 'a' * 40}
HEAD_TWO = {'sha': '2' * 40, 'tree': 'b' * 40}


def marker(repository=REPOSITORY):
    return {'format': script.FORMAT, 'source_repository': repository,
            'data_note': 'SYNTHETIC TEST FIXTURE: no real candidates'}


class FakeGitHub:
    def __init__(self, heads=(None,), failures=()):
        self.heads=list(heads)
        self.failures=list(failures)
        self.calls=[]
        self.inspections=0
        self.commits=0
        self.marker_override=None
        self.marker_error=None
    def __call__(self, method, endpoint, payload=None):
        self.calls.append((method,endpoint,payload))
        if 'matching-refs' in endpoint:
            head=self.heads[min(self.inspections,len(self.heads)-1)]
            self.inspections+=1
            return [] if head is None else [{'ref':'refs/heads/analysis-dashboard',
                'object':{'type':'commit','sha':head['sha']}}]
        if '/contents/' in endpoint:
            if self.marker_error: raise script.GitHubApiError(self.marker_error)
            value=self.marker_override or marker()
            data=json.dumps(value).encode()
            return {'type':'file','encoding':'base64','size':len(data),
                    'content':base64.b64encode(data).decode()}
        if method=='GET' and '/git/commits/' in endpoint:
            head=next(h for h in self.heads if h and endpoint.endswith(h['sha']))
            return {'sha':head['sha'],'tree':{'sha':head['tree']}}
        if method=='POST' and endpoint.endswith('/git/trees'):
            return {'sha':'c'*40}
        if method=='POST' and endpoint.endswith('/git/commits'):
            self.commits+=1
            return {'sha':str(self.commits+3)*40}
        if '/git/refs' in endpoint:
            if self.failures:
                code=self.failures.pop(0)
                if code: raise script.GitHubApiError(code)
            return {'object':{'sha':payload['sha']}}
        raise AssertionError('Unexpected synthetic API operation')


@pytest.fixture
def site(tmp_path,monkeypatch):
    monkeypatch.setenv('GITHUB_REPOSITORY',REPOSITORY)
    root=tmp_path/'dashboard'
    root.mkdir()
    for name in script.ALLOWED_FILES:
        (root/name).write_text('SYNTHETIC dashboard fixture\n',encoding='utf-8')
    (root/script.MARKER).write_text(json.dumps(marker()))
    return root


def install_fake(monkeypatch, heads=(None,), failures=()):
    fake=FakeGitHub(heads,failures)
    monkeypatch.setattr(script,'api',fake)
    return fake


def test_new_dedicated_branch_publishes_exact_allowlist_and_truthful_urls(site,tmp_path,monkeypatch,capsys):
    fake=install_fake(monkeypatch)
    report_path=tmp_path/'publication.json'
    report=script.publish(site,report_path)
    assert len(fake.calls)==4
    tree=next(payload for method,url,payload in fake.calls if url.endswith('/git/trees'))
    assert {item['path'] for item in tree['tree']}==script.ALLOWED_FILES
    assert 'base_tree' not in tree
    commit=next(payload for method,url,payload in fake.calls if method=='POST' and url.endswith('/git/commits'))
    assert commit['parents']==[]
    assert fake.calls[-1][2]=={'ref':'refs/heads/analysis-dashboard','sha':'4'*40}
    assert report['pages_deployed'] is False
    assert report['rendered_report_url']=='https://github.com/synthetic/Simulations/tree/analysis-dashboard'
    assert json.loads(report_path.read_text())==report
    assert 'GitHub Pages deployment is separate' in capsys.readouterr().out
    assert all('/heads/main' not in url and 'live-pilot-budget' not in url for _,url,_ in fake.calls)


def test_existing_owned_branch_preserves_history_and_unrelated_files(site,monkeypatch):
    fake=install_fake(monkeypatch,(HEAD_ONE,))
    script.publish(site)
    assert len(fake.calls)==6
    assert '/contents/.midterm-dashboard.json?ref='+HEAD_ONE['sha'] in fake.calls[1][1]
    tree=next(payload for method,url,payload in fake.calls if url.endswith('/git/trees'))
    assert tree['base_tree']==HEAD_ONE['tree']
    assert all('sha' not in item for item in tree['tree'])  # No null/deletion entries.
    commit=next(payload for method,url,payload in fake.calls if method=='POST' and url.endswith('/git/commits'))
    assert commit['parents']==[HEAD_ONE['sha']]
    assert fake.calls[-1][0]=='PATCH' and fake.calls[-1][2]['force'] is False


@pytest.mark.parametrize('problem',['missing-index','missing-marker','missing-readme','unsupported-file',
                                    'nested-directory','file-symlink','wrong-format','wrong-repository','oversize'])
def test_invalid_local_dashboard_stops_before_any_api_call(site,monkeypatch,problem):
    fake=install_fake(monkeypatch)
    if problem.startswith('missing-'):
        name={'missing-index':'index.html','missing-marker':script.MARKER,'missing-readme':'README.md'}[problem]
        (site/name).unlink()
    elif problem=='unsupported-file': (site/'pilot.sqlite').write_bytes(b'USER ELECTION DATABASE')
    elif problem=='nested-directory': (site/'extra').mkdir()
    elif problem=='file-symlink':
        (site/'coverage.svg').unlink()
        (site/'coverage.svg').symlink_to(site/'README.md')
    elif problem=='wrong-format': (site/script.MARKER).write_text(json.dumps({'format':'unrelated'}))
    elif problem=='wrong-repository': (site/script.MARKER).write_text(json.dumps(marker('other/project')))
    elif problem=='oversize':
        with (site/'index.html').open('wb') as stream: stream.truncate(script.MAX_TOTAL_BYTES+1)
    with pytest.raises(ValueError): script.publish(site)
    assert fake.calls==[]


def test_symlink_root_rejected(site,tmp_path,monkeypatch):
    fake=install_fake(monkeypatch)
    link=tmp_path/'dashboard-link'
    link.symlink_to(site,target_is_directory=True)
    with pytest.raises(ValueError,match='Symlink'): script.publish(link)
    assert fake.calls==[]


@pytest.mark.parametrize('foreign',['wrong-format','wrong-repository','missing-marker'])
def test_existing_unowned_branch_never_mutated(site,monkeypatch,foreign):
    fake=install_fake(monkeypatch,(HEAD_ONE,))
    if foreign=='wrong-format': fake.marker_override={'format':'unrelated','source_repository':REPOSITORY}
    elif foreign=='wrong-repository': fake.marker_override=marker('other/project')
    else: fake.marker_error=404
    with pytest.raises(ValueError): script.publish(site)
    assert all(method=='GET' for method,_,_ in fake.calls)


def test_owned_update_race_reparents_once_without_force(site,monkeypatch):
    fake=install_fake(monkeypatch,(HEAD_ONE,HEAD_TWO),(422,None))
    report=script.publish(site)
    assert report['publication_attempts']==2 and len(fake.calls)==12
    commits=[p for method,url,p in fake.calls if method=='POST' and url.endswith('/git/commits')]
    assert [p['parents'] for p in commits]==[[HEAD_ONE['sha']],[HEAD_TWO['sha']]]
    refs=[p for method,url,p in fake.calls if method=='PATCH']
    assert all(p['force'] is False for p in refs)


def test_create_race_retries_only_after_verifying_owned_new_branch(site,monkeypatch):
    fake=install_fake(monkeypatch,(None,HEAD_TWO),(422,None))
    report=script.publish(site)
    assert report['publication_attempts']==2
    assert fake.calls[-1][0]=='PATCH'
    commits=[p for method,url,p in fake.calls if method=='POST' and url.endswith('/git/commits')]
    assert commits[-1]['parents']==[HEAD_TWO['sha']]


def test_unchanged_head_validation_error_is_not_retried(site,monkeypatch):
    fake=install_fake(monkeypatch,(HEAD_ONE,HEAD_ONE),(422,))
    with pytest.raises(script.GitHubApiError): script.publish(site)
    assert fake.commits==1


def test_second_race_stops_after_bounded_retry(site,monkeypatch):
    fake=install_fake(monkeypatch,(HEAD_ONE,HEAD_TWO),(422,422))
    with pytest.raises(script.GitHubApiError): script.publish(site)
    assert fake.commits==2 and len(fake.calls)==12


def test_permission_denial_does_not_retry_or_bypass(site,monkeypatch):
    fake=install_fake(monkeypatch,(HEAD_ONE,),(403,))
    with pytest.raises(script.GitHubApiError,match='HTTP 403'): script.publish(site)
    assert fake.commits==1 and fake.inspections==1


def test_existing_local_report_is_preserved(site,tmp_path,monkeypatch):
    fake=install_fake(monkeypatch)
    target=tmp_path/'existing.json'
    target.write_text('USER FILE')
    with pytest.raises(ValueError,match='existing files'): script.publish(site,target)
    assert target.read_text()=='USER FILE' and fake.calls==[]


def test_api_uses_json_file_and_never_token_argv(monkeypatch):
    monkeypatch.setenv('GH_TOKEN','synthetic-secret-do-not-output')
    paths=[]
    payload={'tree':[{'path':'README.md','content':'Exact newline\nLiteral $(not-code)'}]}
    def fake_run(command,**kwargs):
        assert 'synthetic-secret-do-not-output' not in repr(command)
        path=Path(command[command.index('--input')+1])
        paths.append(path)
        assert json.loads(path.read_text())==payload
        return SimpleNamespace(returncode=0,stdout='HTTP/2.0 201 Created\ncontent-type: application/json\n\n{"sha":"ok"}',stderr='')
    monkeypatch.setattr(script.subprocess,'run',fake_run)
    assert script.api('POST','repos/synthetic/Simulations/git/trees',payload)=={'sha':'ok'}
    assert paths and all(not path.exists() for path in paths)


def test_api_errors_do_not_include_response_or_stderr(monkeypatch):
    monkeypatch.setattr(script.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=1,
        stdout='HTTP/2.0 403 Forbidden\n\n{"message":"SENSITIVE RESPONSE"}',stderr='SENSITIVE STDERR'))
    with pytest.raises(script.GitHubApiError) as caught:
        script.api('GET','repos/synthetic/Simulations/git/matching-refs/heads/analysis-dashboard')
    assert caught.value.status==403
    assert 'SENSITIVE' not in str(caught.value)


def test_unconfirmed_ref_result_is_not_reported_as_published(site,tmp_path,monkeypatch,capsys):
    fake=FakeGitHub()
    def mismatched(method,url,payload=None):
        result=fake(method,url,payload)
        if '/git/refs' in url: return {'object':{'sha':'9'*40}}
        return result
    monkeypatch.setattr(script,'api',mismatched)
    report=tmp_path/'report.json'
    with pytest.raises(ValueError,match='did not confirm'):
        script.publish(site,report)
    assert not report.exists()
    assert 'published::' not in capsys.readouterr().out
