from __future__ import annotations

import json
from decimal import Decimal

from services.database import DatabaseError, QueryResult
from services.tools import ToolRunner
from services.tool_cache import ToolCache


class CountingDB:
    dataset_version = 'snapshot-1'

    def __init__(self):
        self.calls = 0
        self.fail = False

    async def query(self, sql, params=None, **kwargs):
        self.calls += 1
        if self.fail:
            raise DatabaseError('temporary query failure')
        return QueryResult(['amount'], [[Decimal('12345.6789')]])


async def test_cache_exact_arguments_and_generation():
    db = CountingDB()
    runner = ToolRunner(db)
    first = json.loads(await runner.run('run_sql', {'query': "SELECT 'A'"}))
    second = json.loads(await runner.run('run_sql', {'query': "SELECT 'A'"}))
    assert first['cache'] == 'miss' and second['cache'] == 'hit'
    assert first['rows'] == second['rows']
    assert db.calls == 1
    await runner.run('run_sql', {'query': "SELECT 'a'"})
    assert db.calls == 2  # literal case must not be normalized
    db.dataset_version = 'snapshot-2'
    await runner.run('run_sql', {'query': "SELECT 'A'"})
    assert db.calls == 3
    runner.max_rows = 5
    await runner.run('run_sql', {'query': "SELECT 'A'"})
    assert db.calls == 4


async def test_errors_are_not_cached():
    db = CountingDB()
    runner = ToolRunner(db)
    db.fail = True
    assert not json.loads(await runner.run('run_sql', {'query': 'SELECT 1'}))['ok']
    db.fail = False
    assert json.loads(await runner.run('run_sql', {'query': 'SELECT 1'}))['ok']
    assert db.calls == 2


async def test_volatile_and_unknown_functions_bypass_cache():
    db = CountingDB()
    runner = ToolRunner(db)
    for query in ('SELECT random()', 'SELECT current_timestamp', 'SELECT uuid()',
                  'SELECT unknown_function()', 'SELECT "random"()', "SELECT TIMESTAMP 'now'"):
        for _ in range(2):
            assert json.loads(await runner.run('run_sql', {'query': query}))['cache'] == 'bypass'
    assert db.calls == 12


def test_lru_and_byte_bounds():
    cache = ToolCache(2, 20)
    cache.select_generation('one')
    cache.put('a', '111'); cache.put('b', '222')
    assert cache.get('a') == '111'
    cache.put('c', '333')
    assert cache.get('b') is None
    cache.put('large', 'x' * 100)
    assert cache.get('large') is None
    assert cache.bytes <= 20
    cache.select_generation('two')
    assert cache.get('a') is None
    assert cache.bytes == 0


async def test_disconnected_database_cannot_serve_cached_success(tmp_path):
    import duckdb
    from services.database import Database
    path = tmp_path / 'snapshot.duckdb'
    connection = duckdb.connect(str(path))
    connection.execute('CREATE TABLE sample AS SELECT 42 AS n')
    connection.close()
    db = Database(path); db.connect()
    runner = ToolRunner(db)
    assert json.loads(await runner.run('run_sql', {'query': 'SELECT n FROM sample'}))['ok']
    db.close()
    result = json.loads(await runner.run('run_sql', {'query': 'SELECT n FROM sample'}))
    assert not result['ok']


async def test_replaced_snapshot_requires_reconnect(tmp_path):
    import os
    import duckdb
    from services.database import Database
    path = tmp_path / 'snapshot.duckdb'
    replacement = tmp_path / 'replacement.duckdb'
    for file, value in ((path, 1), (replacement, 2)):
        connection = duckdb.connect(str(file))
        connection.execute(f'CREATE TABLE sample AS SELECT {value} AS n')
        connection.close()
    db = Database(path); db.connect()
    runner = ToolRunner(db)
    assert json.loads(await runner.run('run_sql', {'query': 'SELECT n FROM sample'}))['rows'][0]['n'] == 1
    os.replace(replacement, path)
    result = json.loads(await runner.run('run_sql', {'query': 'SELECT n FROM sample'}))
    assert not result['ok'] and 'reconnect' in result['error']
    db.close(); db.connect()
    result = json.loads(await runner.run('run_sql', {'query': 'SELECT n FROM sample'}))
    assert result['rows'][0]['n'] == 2 and result['cache'] == 'miss'
    db.close()
