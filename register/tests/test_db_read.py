"""验证 mark_read_ids 只标记传入的展示消息 id。"""

import os
import sys
from contextlib import contextmanager

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db


class FakeCursor:
    def __init__(self, recorder):
        self.recorder = recorder
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        self.recorder.append((sql, params))
        self.rowcount = len(params) - 2   # conv_id, reader_id, 其余为 ids


class FakeConn:
    def __init__(self, recorder):
        self.recorder = recorder

    def cursor(self):
        return FakeCursor(self.recorder)

    def commit(self):
        pass


@pytest.fixture
def recorded(monkeypatch):
    calls = []

    @contextmanager
    def fake_connect():
        yield FakeConn(calls)

    monkeypatch.setattr(db, "connect", fake_connect)
    return calls


def test_mark_read_ids_only_touches_passed_ids(recorded):
    n = db.mark_read_ids(5, 10, [101, 102, 103])
    assert n == 3
    sql, params = recorded[-1]
    assert "id IN (%s,%s,%s)" in sql
    assert params == (5, 10, 101, 102, 103)


def test_mark_read_ids_empty_noop(recorded):
    assert db.mark_read_ids(5, 10, []) == 0
    assert recorded == []


def test_mark_all_read_has_no_id_filter(recorded):
    db.mark_all_read(5, 10)
    sql, params = recorded[-1]
    assert "id IN" not in sql
    assert params == (5, 10)
