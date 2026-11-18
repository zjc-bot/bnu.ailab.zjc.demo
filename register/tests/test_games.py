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
    snap = manager.apply_move(1, 10, {"x": 0, "y": 0})
    assert snap["turn"] == 1
    assert snap["seq"] == 1
    assert snap["state"]["board"][0][0] == 1   # P1 落子
    assert len(snap["state"]["board"]) == 15   # 服务端棋盘


def test_wrong_turn_rejected():
    manager.create_room(1, "gomoku", 10, 20)
    with pytest.raises(manager.RoomError, match="还没轮到你"):
        manager.apply_move(1, 20, {"x": 0, "y": 0})


def test_non_player_rejected():
    manager.create_room(1, "gomoku", 10, 20)
    with pytest.raises(manager.RoomError):
        manager.apply_move(1, 99, {"x": 0, "y": 0})


def test_invalid_move_rejected():
    manager.create_room(1, "gomoku", 10, 20)
    with pytest.raises(manager.RoomError):
        manager.apply_move(1, 10, {})


def test_finish_and_apply_rejected():
    manager.create_room(1, "gomoku", 10, 20)
    manager.finish(1, {"winner": 10})
    with pytest.raises(manager.RoomError, match="对局已结束"):
        manager.apply_move(1, 10, {"x": 1, "y": 1})


def test_destroy():
    manager.create_room(1, "gomoku", 10, 20)
    assert manager.destroy(1) is True
    assert manager.get_room(1) is None


def test_snapshot_always_has_result():
    """快照必须含 result 字段，否则 game:over 广播丢胜负、重连无法恢复。"""
    snap = manager.create_room(1, "gomoku", 10, 20)
    assert "result" in snap
    assert snap["result"] is None
    snap = manager.finish(1, {"winner": 20, "reason": "resign"})
    assert snap["result"] == {"winner": 20, "reason": "resign"}
    assert manager.snapshot(1)["result"] == {"winner": 20, "reason": "resign"}


def test_client_cannot_forge_board():
    """服务端权威：apply_move 只接收坐标，棋盘由规则层派生，无法被客户端覆写。"""
    snap = manager.create_room(1, "gomoku", 10, 20)
    assert len(snap["state"]["board"]) == 15
    snap = manager.apply_move(1, 10, {"x": 7, "y": 7})
    # 棋盘必须仍是 15×15，且只在 (7,7) 落了 P1 的子
    assert len(snap["state"]["board"]) == 15
    assert snap["state"]["board"][7][7] == 1
    assert sum(row.count(1) for row in snap["state"]["board"]) == 1


def test_occupied_and_out_of_range_rejected():
    manager.create_room(1, "gomoku", 10, 20)
    manager.apply_move(1, 10, {"x": 0, "y": 0})
    # 同位置重复落子
    with pytest.raises(manager.RoomError, match="已有棋子"):
        manager.apply_move(1, 20, {"x": 0, "y": 0})
    # 越界
    with pytest.raises(manager.RoomError, match="越界"):
        manager.apply_move(1, 20, {"x": -1, "y": 0})


def test_five_in_row_wins():
    """五连自动终局，result 指向获胜玩家 uid。"""
    manager.create_room(1, "gomoku", 10, 20)
    # P1 横连五，P2 在远处陪走
    for i in range(4):
        manager.apply_move(1, 10, {"x": i, "y": 0})
        manager.apply_move(1, 20, {"x": i, "y": 5})
    snap = manager.apply_move(1, 10, {"x": 4, "y": 0})
    assert snap["status"] == "finished"
    assert snap["result"]["winner"] == 10
    assert snap["result"]["reason"] == "five_in_row"


def test_unsupported_game_move_rejected():
    """规则未接入的游戏禁止落子，防止无规则状态下伪造胜负。"""
    manager.create_room(1, "chess", 10, 20)
    with pytest.raises(manager.RoomError, match="规则尚未接入"):
        manager.apply_move(1, 10, {"x": 0, "y": 0})
