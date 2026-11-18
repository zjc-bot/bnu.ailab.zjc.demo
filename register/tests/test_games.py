"""对战房间管理单元测试（纯逻辑，不连数据库、不启服务）。"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from games import manager  # noqa: E402


@pytest.fixture(autouse=True)
def clean_rooms():
    for rid in list(manager._rooms):
        manager.destroy(rid)
    yield
    for rid in list(manager._rooms):
        manager.destroy(rid)


def test_create_and_snapshot():
    snap = manager.create_room(1, "gomoku", 10, 20)
    assert snap["players"] == [10, 20]
    assert snap["turn"] == 0
    assert snap["status"] == "active"
    assert manager.get_room(1) is not None


def test_duplicate_room_rejected():
    manager.create_room(1, "gomoku", 10, 20)
    with pytest.raises(manager.RoomError):
        manager.create_room(1, "gomoku", 10, 20)


def test_move_switches_turn():
    manager.create_room(1, "gomoku", 10, 20)
    snap = manager.apply_move(1, 10, {"x": 0, "y": 0}, {"board": [[1]]})
    assert snap["turn"] == 1
    assert snap["seq"] == 1
    assert snap["state"] == {"board": [[1]]}


def test_wrong_turn_rejected():
    manager.create_room(1, "gomoku", 10, 20)
    with pytest.raises(manager.RoomError, match="还没轮到你"):
        manager.apply_move(1, 20, {"x": 0, "y": 0}, {})


def test_non_player_rejected():
    manager.create_room(1, "gomoku", 10, 20)
    with pytest.raises(manager.RoomError):
        manager.apply_move(1, 99, {"x": 0, "y": 0}, {})


def test_invalid_move_rejected():
    manager.create_room(1, "gomoku", 10, 20)
    with pytest.raises(manager.RoomError, match="无效的着法"):
        manager.apply_move(1, 10, {}, {})


def test_finish_and_apply_rejected():
    manager.create_room(1, "gomoku", 10, 20)
    manager.finish(1, {"winner": 10})
    with pytest.raises(manager.RoomError, match="对局已结束"):
        manager.apply_move(1, 10, {"x": 1, "y": 1}, {})


def test_destroy():
    manager.create_room(1, "gomoku", 10, 20)
    assert manager.destroy(1) is True
    assert manager.get_room(1) is None
