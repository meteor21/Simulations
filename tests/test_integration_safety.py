import sqlite3
import pytest
from charisma_lab.agents_store import AgentStore


def test_future_agents_schema_rejected_before_any_mutation(tmp_path):
    path = tmp_path / 'future.sqlite'
    with sqlite3.connect(path) as con:
        con.execute('CREATE TABLE cs_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        con.executemany('INSERT INTO cs_meta VALUES(?,?)',
                        [('schema_version', '1'), ('sentiment_agents_schema', '999')])
    before = path.read_bytes()
    with pytest.raises(ValueError, match='sentiment agents schema'):
        AgentStore(path)
    assert path.read_bytes() == before
    assert not path.with_name(path.name + '-wal').exists()
