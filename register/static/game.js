/* 五子棋对战：Socket.IO 客户端（好友对战 PvP） */
(function () {
  'use strict';

  var uid = Number((document.querySelector('meta[name="uid"]') || {}).content || 0);
  var uname = (document.querySelector('meta[name="uname"]') || {}).content || '我';
  var boardEl = document.getElementById('gmBoard');
  var statusEl = document.getElementById('gmStatus');
  var resignBtn = document.getElementById('gmResign');
  var leaveBtn = document.getElementById('gmLeave');
  if (!boardEl || !uid) return;

  var socket = io({ transports: ['websocket', 'polling'] });
  var room = 0;
  var mySeat = 0;        // 1=先手(P1黑) 2=后手(P2白)
  var curTurn = 1;
  var over = false;

  function status(html) { statusEl.innerHTML = html; }

  function buildBoard() {
    boardEl.replaceChildren();
    for (var y = 0; y < 15; y++) {
      for (var x = 0; x < 15; x++) {
        var cell = document.createElement('div');
        cell.className = 'gm-cell';
        cell.dataset.x = x;
        cell.dataset.y = y;
        (function (cx, cy) {
          cell.addEventListener('click', function () { place(cx, cy); });
        })(x, y);
        boardEl.appendChild(cell);
      }
    }
  }

  function render(state, turn, result) {
    var grid = (state && state.board) || [];
    var cells = boardEl.children;
    for (var i = 0; i < cells.length; i++) {
      var cell = cells[i];
      var x = Number(cell.dataset.x), y = Number(cell.dataset.y);
      var v = (grid[y] && grid[y][x]) || 0;
      var old = cell.querySelector('.gm-stone');
      if (old) old.remove();
      if (v) {
        var s = document.createElement('div');
        s.className = 'gm-stone ' + (v === 1 ? 'p1' : 'p2');
        cell.appendChild(s);
      }
    }
    if (result) {
      var win = result.winner === uid ? '你赢了' : '对方获胜';
      status('<b>' + win + '</b> · ' + (result.reason === 'resign' ? '对方认输' : '五子连珠') + '　刷新查看战绩');
      over = true;
      resignBtn.disabled = true;
      return;
    }
    var mine = turn === mySeat;
    status(mine ? '轮到你落子（' + (mySeat === 1 ? '黑' : '白') + '）'
                : '等待对方落子…');
  }

  function place(x, y) {
    if (over || !room || curTurn !== mySeat) return;
    socket.emit('game:move', { room: room, move: { x: x, y: y } }, function (r) {
      if (r && r.ok === false) status('<b style="color:#b91c1c">' + (r.error || '落子失败') + '</b>');
    });
  }

  /* ---------- 邀请 ---------- */
  document.querySelectorAll('[data-invite]').forEach(function (b) {
    b.addEventListener('click', function () {
      var to = Number(b.dataset.invite);
      var name = b.dataset.name || '好友';
      socket.emit('game:invite', { to: to, game: 'gomoku' }, function (r) {
        if (!r || r.ok === false) {
          status('<b style="color:#b91c1c">' + ((r && r.error) || '邀请失败') + '</b>');
          return;
        }
        room = r.room;
        status(r.delivered
          ? '已邀请 ' + name + '，等待对方接受…'
          : '已创建对局，但 ' + name + ' 当前不在线');
        socket.emit('game:join', { room: room }, function (j) {
          if (j && j.ok) {
            mySeat = 1;   // 发起方坐先手
            resignBtn.disabled = false;
          }
        });
      });
    });
  });

  /* ---------- 事件 ---------- */
  socket.on('game:invited', function (d) {
    if (!window.confirm('好友（uid ' + d.from + '）邀请你对战，接受吗？')) return;
    room = d.room;
    socket.emit('game:join', { room: room }, function (j) {
      if (j && j.ok) {
        mySeat = 2;   // 接受方坐后手
        resignBtn.disabled = false;
      }
    });
  });

  socket.on('game:state', function (snap) {
    if (!snap || Number(snap.room) !== room) return;
    curTurn = snap.turn + 1;   // turn 是 players 下标
    if (!mySeat) mySeat = snap.players.indexOf(uid) + 1;
    render(snap.state, curTurn, snap.result);
  });

  socket.on('game:over', function (snap) {
    if (!snap || Number(snap.room) !== room) return;
    render(snap.state, curTurn, snap.result);
  });

  resignBtn.addEventListener('click', function () {
    if (!room || over) return;
    if (!window.confirm('确定认输？')) return;
    socket.emit('game:resign', { room: room });
  });

  leaveBtn.addEventListener('click', function () {
    room = 0; mySeat = 0; over = false;
    resignBtn.disabled = true;
    leaveBtn.disabled = true;
    buildBoard();
    status('已离开对局');
  });

  socket.on('connect', function () {
    status('已连接，选择好友发起对局');
  });
  socket.on('disconnect', function () {
    status('<b style="color:#b91c1c">连接已断开，正在重连…</b>');
  });

  socket.on('connect_error', function () {
    status('<b style="color:#b91c1c">连接失败：请刷新重试</b>');
  });

  buildBoard();
})();
