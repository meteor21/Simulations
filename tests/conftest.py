import pytest
from charisma_lab.store import Store

@pytest.fixture
def store(tmp_path):
    with Store(tmp_path/'test.sqlite') as s:
        s.candidate('C1','Alex Rowan',known_at='2020-01-01',source_url='synthetic://test')
        yield s
