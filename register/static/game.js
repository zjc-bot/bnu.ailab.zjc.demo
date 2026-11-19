/* 五子棋对战：Socket.IO 客户端（PvP + 小鲸 PvE + 持久化邀请） */
(function () {
  'use strict';

  var uid = Number((document.querySelector('meta[name="uid"]') || {}).content || 0);
  var boardEl = document.getElementById('gmBoard');
  var statusEl = document.getElementById('gmStatus');
  var resignBtn = document.getElementById('gmResign');
  var leaveBtn = document.getElementById('gmLeave');
  var difficultyEl = document.getElementById('gmDifficulty');
  var aiStartBtn = document.getElementById('gmAIStart');
  var invitesEl = document.getElementById('gmInvites');
  var inviteListEl = document.getElementById('gmInviteList');
  var pageGuide = document.getElementById('gmPageGuide');
  var firstMoveGuide = document.getElementById('gmFirstMoveGuide');
  if (!boardEl || !uid) return;

  var GUIDE_PREFIX = 'bnu.games.guide.';
  var socket = io({ transports: ['websocket', 'polling'] });
  var room = 0;
  var mySeat = 0;        // 1=先手(P1黑) 2=后手(P2白)
  var curTurn = 1;
  var over = false;
  var pendingInvites = [];
  var friendNames = {};

  document.querySelectorAll('[data-invite]').forEach(function (b) {
    friendNames[Number(b.dataset.invite)] = b.dataset.name || '好友';
  });

  function guideSeen(name) {
    try { return localStorage.getItem(GUIDE_PREFIX + name) === '1'; }
    catch (e) { return false; }
  }

  function markGuide(name) {
    try { localStorage.setItem(GUIDE_PREFIX + name, '1'); } catch (e) {}
  }

  function setStatus(text, danger) {
    statusEl.textContent = text;
    statusEl.className = 'gm-status' + (danger ? ' gm-status-error' : '');
  }

  function showPageGuide() {
    if (!pageGuide || guideSeen('page')) return;
    pageGuide.hidden = false;
  }

  function dismissPageGuide() {
    markGuide('page');
    if (pageGuide) pageGuide.hidden = true;
  }

  function maybeShowFirstMoveGuide() {
    if (!firstMoveGuide || guideSeen('firstMove')) return;
    firstMoveGuide.hidden = false;
  }

  function dismissFirstMoveGuide() {
    markGuide('firstMove');
    if (firstMoveGuide) firstMoveGuide.hidden = true;
  }

  if (document.getElementById('gmPageGuideDismiss')) {
    document.getElementById('gmPageGuideDismiss')
      .addEventListener('click', dismissPageGuide);
  }
  if (document.getElementById('gmFirstMoveGuideDismiss')) {
    document.getElementById('gmFirstMoveGuideDismiss')
      .addEventListener('click', dismissFirstMoveGuide);
  }

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

  function reasonText(reason) {
    if (reason === 'resign') return '认输结束';
    if (reason === 'draw') return '棋盘已满';
    if (reason === 'ai_error') return 'AI 暂时不可用，本局按和棋处理';
    if (reason === 'checkmate') return '将死';
    if (reason === 'uno_out') return '先出完牌';
    return '五子连珠';
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
      var draw = result.reason === 'draw' || result.reason === 'ai_error';
      var win = draw ? '和棋' : (result.winner === uid ? '你赢了' : '对方获胜');
      setStatus(win + ' · ' + reasonText(result.reason) + '　刷新查看战绩');
      over = true;
      resignBtn.disabled = true;
      dismissFirstMoveGuide();
      return;
    }
    var mine = turn === mySeat;
    setStatus(mine ? '轮到你落子（' + (mySeat === 1 ? '黑' : '白') + '）'
                   : '等待对方落子…');
  }

  function place(x, y) {
    if (over || !room || curTurn !== mySeat) return;
    socket.emit('game:move', { room: room, move: { x: x, y: y } }, function (r) {
      if (r && r.ok === false) {
        setStatus(r.error || '落子失败', true);
        return;
      }
      dismissFirstMoveGuide();
    });
  }

  function normalizeInvite(raw) {
    var conv = Number(raw.conv_id || raw.room || 0);
    return {
      id: Number(raw.id || conv),
      room: conv,
      game: raw.game || 'gomoku',
      from_id: Number(raw.from_id || raw.from || 0),
      from_name: raw.from_name || friendNames[Number(raw.from_id || raw.from)] || '好友',
      created_at: raw.created_at || '刚刚'
    };
  }

  function applyInvites(items) {
    pendingInvites = (items || []).map(normalizeInvite).filter(function (it) {
      return it.room > 0;
    });
    renderInvites();
    if (!room && pendingInvites.length) {
      setStatus('有 ' + pendingInvites.length + ' 条待处理对战邀请');
    }
  }

  function removeInvite(targetRoom) {
    pendingInvites = pendingInvites.filter(function (it) {
      return it.room !== targetRoom;
    });
    renderInvites();
  }

  function renderInvites() {
    if (!invitesEl || !inviteListEl) return;
    inviteListEl.replaceChildren();
    invitesEl.hidden = pendingInvites.length === 0;
    pendingInvites.forEach(function (it) {
      var box = document.createElement('div');
      box.className = 'gm-invite';
      var text = document.createElement('div');
      text.className = 'gm-invite-text';
      text.textContent = it.from_name + ' 邀请你下五子棋 · ' + it.created_at;
      var btns = document.createElement('div');
      btns.className = 'gm-invite-btns';
      var yes = document.createElement('button');
      yes.type = 'button'; yes.className = 'btn primary sm2'; yes.textContent = '接受';
      yes.addEventListener('click', function () { joinRoom(it.room, true); });
      var no = document.createElement('button');
      no.type = 'button'; no.className = 'btn ghost sm2'; no.textContent = '拒绝';
      no.addEventListener('click', function () {
        socket.emit('game:invite:decline', { room: it.room }, function (r) {
          if (r && r.ok === false) { setStatus(r.error || '操作失败', true); return; }
          removeInvite(it.room);
          setStatus('已拒绝对战邀请');
        });
      });
      btns.append(yes, no);
      box.append(text, btns);
      inviteListEl.appendChild(box);
    });
  }

  function addInvite(raw) {
    var it = normalizeInvite(raw);
    if (pendingInvites.some(function (p) { return p.room === it.room; })) return;
    pendingInvites.unshift(it);
    renderInvites();
  }

  function joinRoom(targetRoom, fromInvite) {
    var previousRoom = room;
    room = targetRoom;
    mySeat = 0;
    curTurn = 1;
    over = false;
    buildBoard();
    socket.emit('game:join', { room: targetRoom }, function (j) {
      if (!j || j.ok === false) {
        room = previousRoom;
        setStatus((j && j.error) || '无法加入对局', true);
        return;
      }
      mySeat = j.seat || 1;   // 座位由服务端下发，不自行推断
      resignBtn.disabled = false;
      leaveBtn.disabled = false;
      maybeShowFirstMoveGuide();
      if (fromInvite) removeInvite(targetRoom);
      setStatus(mySeat === 1 ? '对局已开始，轮到你落子（黑）'
                             : '对局已开始，等待对方落子…');
    });
  }

  /* ---------- 好友邀请 ---------- */
  document.querySelectorAll('[data-invite]').forEach(function (b) {
    b.addEventListener('click', function () {
      var to = Number(b.dataset.invite);
      var name = friendNames[to] || '好友';
      socket.emit('game:invite', { to: to, game: 'gomoku' }, function (r) {
        if (!r || r.ok === false) {
          setStatus((r && r.error) || '邀请失败', true);
          return;
        }
        setStatus(r.delivered
          ? '已邀请 ' + name + '，等待对方接受…'
          : '邀请已保存，' + name + ' 上线后在「对战」页可见');
        joinRoom(r.room, false);
      });
    });
  });

  /* ---------- AI 对战 ---------- */
  if (aiStartBtn) {
    aiStartBtn.addEventListener('click', function () {
      if (room && !over && !window.confirm('当前对局会结束，确定重新开一局吗？')) return;
      var difficulty = difficultyEl ? difficultyEl.value : 'normal';
      socket.emit('game:ai:start', { game: 'gomoku', difficulty: difficulty }, function (r) {
        if (!r || r.ok === false) {
          setStatus((r && r.error) || 'AI 对局创建失败', true);
          return;
        }
        joinRoom(r.room, false);
        var label = { easy: '简单', normal: '普通', hard: '困难' }[r.difficulty] || '普通';
        setStatus('正在和小鲸（' + label + '）对战，轮到你落子');
      });
    });
  }

  /* ---------- 事件 ---------- */
  socket.on('game:invites', function (d) {
    applyInvites(d && d.items);
  });

  socket.on('game:invited', function (d) {
    addInvite({
      conv_id: d.room,
      room: d.room,
      game: d.game,
      from_id: d.from,
      from_name: friendNames[d.from] || '好友',
      created_at: '刚刚'
    });
    setStatus('收到一条对战邀请，可在左侧接受或拒绝');
  });

  socket.on('game:invite:declined', function () {
    setStatus('对方拒绝了对战邀请');
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
    socket.emit('game:resign', { room: room }, function (r) {
      if (r && r.ok === false) setStatus(r.error || '认输失败', true);
    });
  });

  leaveBtn.addEventListener('click', function () {
    room = 0; mySeat = 0; over = false;
    resignBtn.disabled = true;
    leaveBtn.disabled = true;
    buildBoard();
    if (firstMoveGuide) firstMoveGuide.hidden = true;
    setStatus('已离开对局');
  });

  socket.on('connect', function () {
    setStatus('已连接，选择好友发起对局，或和小鲸开一局');
    socket.emit('game:invites', {}, function (r) {
      if (r && r.ok) applyInvites(r.items);
    });
  });
  socket.on('disconnect', function () {
    setStatus('连接已断开，正在重连…', true);
  });

  socket.on('connect_error', function () {
    setStatus('连接失败：请刷新重试', true);
  });

  buildBoard();
  showPageGuide();
})();
