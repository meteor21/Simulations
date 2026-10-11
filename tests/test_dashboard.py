"""Rendering security and missingness of the public dashboard; synthetic inputs."""
import csv
import io
import json
import re
import xml.etree.ElementTree as ET

import pytest

from charisma_lab.dashboard import write_dashboard
from charisma_lab.dashboard_data import build_dashboard_data
from test_dashboard_data import checkpoint


def render_data(folder):
    return build_dashboard_data(folder, source_repository='example/repository', analysis_run_id=5678, code_revision='def456')


def test_dashboard_contains_only_public_files_and_preserves_missing_scores(checkpoint, tmp_path):
    data=render_data(checkpoint[0])
    output=tmp_path/'site'
    result=write_dashboard(data,output)
    assert set(result['output_files'])=={'index.html','data.json','candidate_coverage.csv','README.md',
                                        'coverage.svg','pipeline.svg','budget.svg','.nojekyll','.midterm-dashboard.json'}
    assert json.loads((output/'data.json').read_text())==data
    rows=list(csv.DictReader((output/'candidate_coverage.csv').open()))
    assert rows[0]['media_recency_score']==rows[1]['media_recency_score']==''
    assert rows[0]['national_urls']=='1' and rows[1]['national_urls']=='0'
    assert 'not verified candidate mentions' in (output/'README.md').read_text()
    for name in ('coverage.svg','pipeline.svg','budget.svg'):
        assert ET.fromstring((output/name).read_text()).tag.endswith('svg')


def test_untrusted_names_cannot_break_out_of_inline_json_or_inject_scripts(checkpoint,tmp_path):
    data=render_data(checkpoint[0]);data['candidates'][0]['name']='</script><script>window.PWNED=true</script>'
    data['candidates'][1]['name']='![tracker](https://unapproved.example.org/image)'
    output=tmp_path/'site';write_dashboard(data,output)
    content=(output/'index.html').read_text()
    assert '<script>window.PWNED' not in content
    match=re.search(r'<script id="dashboard-data" type="application/json">(.*?)</script>',content,re.S)
    assert json.loads(match.group(1))['candidates'][0]['name']==data['candidates'][0]['name']
    assert 'innerHTML' not in content
    assert not re.search(r'<script[^>]+src=',content)
    assert '![tracker](' not in (output/'README.md').read_text()


def test_csv_keeps_zero_and_escapes_spreadsheet_formulas(checkpoint,tmp_path):
    data=render_data(checkpoint[0]);data['candidates'][0]['name']='=HYPERLINK("https://example.org")'
    data['candidates'][0]['features']['media_recency_score']=0
    output=tmp_path/'site';write_dashboard(data,output)
    row=next(csv.DictReader((output/'candidate_coverage.csv').open()))
    assert row['name'].startswith("'=")
    assert row['media_recency_score']=='0'
    assert '| 0.0 |' in (output/'README.md').read_text()


def test_public_dashboard_refuses_to_overwrite_an_existing_database(checkpoint,tmp_path):
    output=tmp_path/'site';output.mkdir();database=output/'elections.sqlite';database.write_bytes(b'KEEP')
    with pytest.raises(ValueError,match='dedicated'):
        write_dashboard(render_data(checkpoint[0]),output)
    assert database.read_bytes()==b'KEEP'


def test_public_dashboard_refuses_symlink_destination(checkpoint,tmp_path):
    actual=tmp_path/'actual';actual.mkdir();linked=tmp_path/'linked';linked.symlink_to(actual,target_is_directory=True)
    with pytest.raises(ValueError,match='symlinks'):
        write_dashboard(render_data(checkpoint[0]),linked)
    assert list(actual.iterdir())==[]
