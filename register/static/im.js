/* 消息：会话列表 / 轮询 / 加好友 / 好友申请 */
(function () {
  'use strict';

  var csrf = (document.querySelector('meta[name="csrf"]') || {}).content || '';
  var listEl = document.getElementById('imList');
  var bodyEl = document.getElementById('imBody');
  var input = document.getElementById('imInput');
  var sendBtn = document.getElementById('imSend');
  var blank = document.getElementById('imBlank');
  var chat = document.getElementById('imChat');
  var reqBadge = document.getElementById('reqBadge');

  if (!listEl || !bodyEl) return;

  /* 移动端「列表 ↔ 会话」两态：由 CSS 的 .im.chat-open 控制显隐。
     桌面端该 class 不带样式，双栏布局不受影响。 */
  var imRoot = document.querySelector('.im');
  function setChatOpen(on) {
    if (imRoot) imRoot.classList.toggle('chat-open', !!on);
  }

  var convs = [];
  var friends = [];
  var requests = [];
  var convsLoaded = false;
  var friendsLoaded = false;
  var activeConv = 0;
  var activePeer = null;
  var myId = 0;
  var lastMsgId = 0;
  var seenIds = new Set();     // 消息去重：轮询与发送并发时避免重复追加
  var sending = false;
  var aiMode = false;          /* 当前是否在跟 AI 对话 */
  var aiBusy = false;
  var aiRoundCount = 0;
  var aiEntryDismissed = false;

  /* ---------- 消息交互（§9B）：引用 / 转发 / 删除 / 多选 ---------- */
  var quotes = {};             // {msgId: {sender_id, content}} 引用摘要
  var quoteTarget = null;      // 当前待引用的消息 {id, sender_id, content}
  var multiMode = false;
  var selectedIds = new Set();
  var ctxMenu = null;
  var quoteBar = null;
  var multiBar = null;

  var EMO_RE = /\[\[emo:\w+\]\]/g;
  var AI_AVATAR = '/static/whale/avatar.webp?v=1';   /* 小鲸头像 */
  var AI_UNAVAILABLE = '小鲸暂时联系不上，稍后再试就好。';
  var GUIDE_PREFIX = 'bnu.im.guide.';
  var guideMemory = {};
  var homeGuide = document.getElementById('homeGuide');
  var aiExportGuide = document.getElementById('aiExportGuide');

  /* ---------- 场景（像素蓝天白云，情绪联动） ---------- */
  var stage = document.getElementById('imStage');
  var stagePet = document.getElementById('stagePet');
  var stageMood = document.getElementById('stageMood');
  var MOOD_TEXT = {
    happy: '开心～', sad: '有点难过', angry: '哼，生气了',
    sleep: '困了…', surprised: '诶！', neutral: '在这里陪你'
  };
  var moodTimer = null;
  function setStage(show) {
    if (stage) stage.hidden = !show;
  }
  function reactMood(emo) {
    if (!stagePet || !stageMood) return;
    var key = MOOD_TEXT[emo] ? emo : 'neutral';
    stagePet.dataset.emotion = key;
    stageMood.textContent = MOOD_TEXT[key];
    clearTimeout(moodTimer);
    moodTimer = setTimeout(function () {
      stagePet.dataset.emotion = 'neutral';
      stageMood.textContent = MOOD_TEXT.neutral;
    }, 3000);
  }

  /* ---------- 工具 ---------- */
  function api(method, path, payload) {
    var opt = {
      method: method,
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': csrf
      }
    };
    if (payload !== undefined) opt.body = JSON.stringify(payload);
    return fetch(path, opt).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) throw new Error(d.error || ('请求失败 ' + r.status));
        return d;
      });
    });
  }

  function esc(s) {
    var d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  /* ---------- 一次性新手引导（§9A.4） ---------- */
  function guideSeen(name) {
    if (guideMemory[name]) return true;
    try { return localStorage.getItem(GUIDE_PREFIX + name) === '1'; }
    catch (e) { return false; }
  }

  function markGuide(name) {
    guideMemory[name] = true;
    try { localStorage.setItem(GUIDE_PREFIX + name, '1'); } catch (e) {}
  }

  function dismissHomeGuide() {
    markGuide('homeEmpty');
    if (homeGuide) homeGuide.hidden = true;
  }

  function maybeShowHomeGuide() {
    if (!homeGuide || !convsLoaded || !friendsLoaded) return;
    /* 已有联系人或会话说明用户已完成这一步，不再补播引导。 */
    if (friends.length || convs.length) {
      dismissHomeGuide();
      return;
    }
    if (guideSeen('homeEmpty')) return;
    markGuide('homeEmpty');
    homeGuide.hidden = false;
  }

  function dismissAIEntryGuide() {
    aiEntryDismissed = true;
    markGuide('aiEntry');
    var tip = document.getElementById('aiEntryGuide');
    if (tip) tip.remove();
  }

  function appendAIEntryGuide() {
    if (aiEntryDismissed || guideSeen('aiEntry') || document.getElementById('aiEntryGuide')) return;
    var tip = document.createElement('div');
    tip.className = 'im-guide im-ai-guide';
    tip.id = 'aiEntryGuide';
    tip.setAttribute('role', 'status');
    var head = document.createElement('div');
    head.className = 'im-guide-head';
    var text = document.createElement('span');
    text.className = 'im-guide-text';
    text.textContent = '这是小鲸，可以随时找它聊天，对话能导出保存';
    var skip = document.createElement('button');
    skip.type = 'button';
    skip.className = 'im-guide-dismiss';
    skip.textContent = '跳过';
    skip.addEventListener('click', dismissAIEntryGuide);
    head.append(text, skip);
    tip.appendChild(head);
    listEl.appendChild(tip);
  }

  function countAIRounds(messages) {
    var rounds = 0;
    var awaitingReply = false;
    (messages || []).forEach(function (m) {
      if (m.role === 'user') awaitingReply = true;
      else if (m.role === 'assistant' && awaitingReply) {
        rounds++;
        awaitingReply = false;
      }
    });
    return rounds;
  }

  function maybeShowAIExportGuide() {
    if (!aiExportGuide || !aiMode || aiRoundCount < 3 || guideSeen('aiExport')) return;
    markGuide('aiExport');
    aiExportGuide.hidden = false;
  }

  function dismissAIExportGuide() {
    markGuide('aiExport');
    if (aiExportGuide) aiExportGuide.hidden = true;
  }

  /* ---------- 消息交互 UI（全部 JS 创建，不改模板/CSS，避免与并行改动冲突） ---------- */

  function senderName(sid) {
    if (sid === myId) return '我';
    if (sid && activePeer && sid === activePeer.id) return activePeer.nickname;
    return '对方';
  }

  function closeCtxMenu() {
    if (ctxMenu) { ctxMenu.remove(); ctxMenu = null; }
  }

  function showCtxMenu(x, y, msgEl) {
    closeCtxMenu();
    if (aiMode || multiMode) return;
    var mid = Number(msgEl.getAttribute('data-mid'));
    if (!mid) return;
    var m = msgEl._msg || { id: mid };
    var items = [
      ['引用', function () { setQuote(m); }],
      ['转发', function () { openForward([mid]); }],
      ['删除', function () { doDelete([mid]); }],
      ['多选', function () { enterMulti(mid); }],
      ['复制文本', function () { copyText(m.content || ''); }]
    ];
    var menu = document.createElement('div');
    menu.style.cssText = 'position:fixed;z-index:300;background:var(--surface);border:1px solid var(--line);' +
      'border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.15);min-width:112px;padding:4px;';
    items.forEach(function (it) {
      var b = document.createElement('button');
      b.type = 'button';
      b.textContent = it[0];
      b.style.cssText = 'display:block;width:100%;text-align:left;border:0;background:none;' +
        'padding:7px 12px;font-size:var(--font-size-sm);color:var(--text);cursor:pointer;border-radius:5px;';
      b.onmouseenter = function () { b.style.background = 'var(--surface-muted)'; };
      b.onmouseleave = function () { b.style.background = 'none'; };
      b.addEventListener('click', function () { closeCtxMenu(); it[1](); });
      menu.appendChild(b);
    });
    document.body.appendChild(menu);
    var w = 120, h = items.length * 33 + 8;
    menu.style.left = Math.max(8, Math.min(x, window.innerWidth - w - 8)) + 'px';
    menu.style.top = Math.max(8, Math.min(y, window.innerHeight - h - 8)) + 'px';
    ctxMenu = menu;
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { toast('已复制'); })
        .catch(function () { toast('复制失败'); });
    } else {
      toast('当前浏览器不支持自动复制');
    }
  }

  function setQuote(m) {
    quoteTarget = { id: m.id, sender_id: m.sender_id, content: (m.content || '').slice(0, 60) };
    renderQuoteBar();
    input.focus();
  }

  function clearQuote() {
    quoteTarget = null;
    renderQuoteBar();
  }

  function renderQuoteBar() {
    if (quoteBar) { quoteBar.remove(); quoteBar = null; }
    if (!quoteTarget) return;
    var bar = document.createElement('div');
    bar.style.cssText = 'display:flex;align-items:center;gap:8px;padding:6px 10px;' +
      'background:var(--surface-muted);border-left:3px solid var(--primary);font-size:var(--font-size-sm);color:var(--muted);';
    var txt = document.createElement('span');
    txt.style.cssText = 'flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
    txt.textContent = '引用 ' + senderName(quoteTarget.sender_id) + '：' + quoteTarget.content;
    var x = document.createElement('button');
    x.type = 'button';
    x.textContent = '×';
    x.title = '取消引用';
    x.style.cssText = 'border:0;background:none;font-size:18px;line-height:1;cursor:pointer;color:var(--muted);';
    x.addEventListener('click', clearQuote);
    bar.append(txt, x);
    var host = document.getElementById('imCompose');
    if (!host) host = input.parentNode;
    if (host && host.parentNode) host.parentNode.insertBefore(bar, host);
    quoteBar = bar;
  }

  /* ---------- 多选批量 ---------- */

  function setMsgActionsVisible(visible) {
    document.querySelectorAll('.im-msg-more').forEach(function (b) {
      b.style.display = visible ? '' : 'none';
    });
  }

  function enterMulti(firstId) {
    multiMode = true;
    selectedIds = new Set(firstId ? [firstId] : []);
    document.querySelectorAll('.im-msg[data-mid]').forEach(function (el) {
      var cb = el.querySelector('.im-ms-check');
      if (cb) cb.style.display = '';
    });
    setMsgActionsVisible(false);
    renderMultiBar();
  }

  function exitMulti() {
    multiMode = false;
    selectedIds.clear();
    document.querySelectorAll('.im-ms-check').forEach(function (cb) { cb.style.display = 'none'; });
    setMsgActionsVisible(true);
    if (multiBar) { multiBar.remove(); multiBar = null; }
  }

  function renderMultiBar() {
    if (multiBar) { multiBar.remove(); multiBar = null; }
    if (!multiMode) return;
    var bar = document.createElement('div');
    bar.style.cssText = 'display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:7px 10px;' +
      'background:var(--info-bg);border-bottom:1px solid var(--info-line);font-size:var(--font-size-sm);';
    var info = document.createElement('span');
    info.textContent = '已选 ' + selectedIds.size + ' 条（上限 50）';
    info.style.cssText = 'flex:1;color:var(--primary-dark);';
    bar.appendChild(info);
    var all = document.querySelectorAll('.im-msg[data-mid]');
    var btnDefs = [
      ['全选', function () {
        // 与服务端 50 条上限对齐；DOM 消息数会随轮询累积，不能无限全选
        var picked = 0;
        all.forEach(function (el) {
          if (picked >= 50) return;
          var id = Number(el.getAttribute('data-mid'));
          if (!selectedIds.has(id)) { selectedIds.add(id); picked++; }
          else picked++;
        });
        syncChecks(); renderMultiBar();
        if (all.length > 50) toast('已选满 50 条，更多消息请分批操作');
      }],
      ['取消', function () { selectedIds.clear(); syncChecks(); renderMultiBar(); }],
      ['转发', function () { openForward(Array.from(selectedIds)); }],
      ['删除', function () { doDelete(Array.from(selectedIds)); }],
      ['退出', exitMulti]
    ];
    btnDefs.forEach(function (d) {
      var b = document.createElement('button');
      b.type = 'button';
      b.textContent = d[0];
      b.style.cssText = 'border:1px solid var(--info-line);background:var(--surface);color:var(--primary-dark);' +
        'padding:3px 10px;border-radius:5px;cursor:pointer;font-size:var(--font-size-sm);';
      b.addEventListener('click', d[1]);
      bar.appendChild(b);
    });
    var chat = document.getElementById('imChat');
    if (chat) chat.insertBefore(bar, chat.firstChild);
    multiBar = bar;
  }

  function syncChecks() {
    document.querySelectorAll('.im-msg[data-mid]').forEach(function (el) {
      var cb = el.querySelector('.im-ms-check');
      if (cb) cb.checked = selectedIds.has(Number(el.getAttribute('data-mid')));
    });
  }

  function doDelete(ids) {
    ids = (ids || []).filter(function (i) { return Number(i) > 0; });
    if (!ids.length) { toast('请先选择消息'); return; }
    if (!window.confirm('删除选中的 ' + ids.length + ' 条消息？只会从你的视图移除，对方仍能看到。')) return;
    api('POST', '/api/messages/delete', { conv: activeConv, ids: ids })
      .then(function (d) {
        toast('已删除 ' + d.deleted + ' 条');
        ids.forEach(function (id) {
          var el = document.querySelector('.im-msg[data-mid="' + id + '"]');
          if (el) el.remove();
        });
        seenIds = new Set(
          Array.from(document.querySelectorAll('.im-msg[data-mid]'))
            .map(function (el) { return Number(el.getAttribute('data-mid')); })
        );
        if (multiMode) { exitMulti(); }
      })
      .catch(function (e) { toast(e.message); });
  }

  function openForward(ids) {
    ids = (ids || []).filter(function (i) { return Number(i) > 0; });
    if (!ids.length) { toast('请先选择消息'); return; }
    if (!friends.length) { toast('还没有好友可转发'); return; }
    var menu = document.createElement('div');
    menu.style.cssText = 'position:fixed;z-index:300;background:var(--surface);border:1px solid var(--line);' +
      'border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.15);min-width:180px;padding:4px;';
    var label = document.createElement('div');
    label.textContent = '转发到：';
    label.style.cssText = 'padding:5px 10px;font-size:var(--font-size-sm);color:var(--muted);';
    menu.appendChild(label);
    friends.forEach(function (f) {
      var b = document.createElement('button');
      b.type = 'button';
      b.textContent = f.nickname || f.real_name;
      b.style.cssText = 'display:block;width:100%;text-align:left;border:0;background:none;' +
        'padding:7px 10px;font-size:var(--font-size-sm);cursor:pointer;border-radius:5px;';
      b.addEventListener('click', function () {
        menu.remove();
        var target = convs.find(function (c) { return c.peer_id === f.id; });
        if (!target) { toast('先和对方聊一句，再转发'); return; }
        api('POST', '/api/messages/forward',
            { conv: activeConv, to_conv: target.id, ids: ids })
          .then(function (d) { toast('已转发 ' + d.forwarded + ' 条'); if (multiMode) exitMulti(); })
          .catch(function (e) { toast(e.message); });
      });
      menu.appendChild(b);
    });
    document.body.appendChild(menu);
    var host = document.getElementById('imSend');
    var r = host ? host.getBoundingClientRect() : { left: 100, top: 200 };
    menu.style.left = Math.max(8, r.left - 180) + 'px';
    menu.style.top = Math.max(8, r.top - friends.length * 33 - 40) + 'px';
    setTimeout(function () {
      document.addEventListener('click', function close(e) {
        if (!menu.contains(e.target)) { menu.remove(); document.removeEventListener('click', close); }
      });
    }, 0);
  }

  function shortTime(v) {
    if (!v) return '';
    var d = new Date(v.replace(' ', 'T'));
    if (isNaN(d.getTime())) return '';
    var now = new Date();
    var hm = String(d.getHours()).padStart(2, '0') + ':' +
             String(d.getMinutes()).padStart(2, '0');
    if (d.toDateString() === now.toDateString()) return hm;
    if (d.getFullYear() === now.getFullYear()) {
      return (d.getMonth() + 1) + '/' + d.getDate();
    }
    return String(d.getFullYear()).slice(2) + '/' + (d.getMonth() + 1);
  }

  function dateLabel(v) {
    if (!v) return '';
    var d = new Date(v.replace(' ', 'T'));
    var now = new Date();
    var yest = new Date(now.getTime() - 86400000);
    if (d.toDateString() === now.toDateString()) return '今天';
    if (d.toDateString() === yest.toDateString()) return '昨天';
    return d.getFullYear() + '年' + (d.getMonth() + 1) + '月' + d.getDate() + '日';
  }

  /* 有头像图就显示图片，否则退回昵称首字 */
  function avatar(name, url, cls) {
    var klass = cls || 'im-av';
    if (url) {
      return '<img class="' + esc(klass) + '" src="' + esc(url) + '" alt="' + esc(name || '') + '">';
    }
    return '<div class="' + esc(klass) + '">' + esc((name || '?').charAt(0)) + '</div>';
  }

  /* 给纯文字容器填头像（顶部、气泡用） */
  function fillAvatar(el, name, url) {
    el.innerHTML = '';
    if (url) {
      var img = document.createElement('img');
      img.src = url;
      img.alt = name || '';
      el.appendChild(img);
    } else {
      el.textContent = (name || '?').charAt(0);
    }
  }

  /* ---------- 左栏渲染（合并：小鲸 + 申请 + 好友会话） ---------- */
  function renderList() {
    listEl.replaceChildren();

    /* 小鲸：固定置顶，作为普通联系人出现 */
    var aiBtn = document.createElement('button');
    aiBtn.type = 'button';
    aiBtn.className = 'im-row im-ai-row' + (aiMode ? ' on' : '');
    aiBtn.innerHTML =
      '<img class="im-av im-ai-av" src="' + AI_AVATAR + '" alt="小鲸">' +
      '<div class="im-row-info">' +
        '<div class="im-row-top">' +
          '<span class="im-row-name">小鲸 <span class="im-tag">AI</span></span>' +
          '<span class="im-row-time">在线</span>' +
        '</div>' +
        '<div class="im-row-bottom">' +
          '<span class="im-row-last">点我聊聊实验室的事</span>' +
          '<span class="im-online-dot"></span>' +
        '</div>' +
      '</div>';
    aiBtn.addEventListener('click', function () {
      dismissAIEntryGuide();
      openAI();
    });
    listEl.appendChild(aiBtn);
    appendAIEntryGuide();

    /* 好友申请：置顶显示 */
    requests.forEach(function (r) {
      var box = document.createElement('div');
      box.className = 'im-req';
      box.innerHTML =
        '<div class="im-req-name">' + esc(r.nickname) + ' 想加你好友</div>' +
        '<div class="im-req-meta">' + esc(r.student_no) + ' · ' + esc(shortTime(r.at)) + '</div>' +
        (r.note ? '<div class="im-req-note">' + esc(r.note) + '</div>' : '');

      var btns = document.createElement('div');
      btns.className = 'im-req-btns';
      var yes = document.createElement('button');
      yes.type = 'button'; yes.className = 'btn primary sm2'; yes.textContent = '同意';
      yes.addEventListener('click', function () { handleReq(r.id, true); });
      var no = document.createElement('button');
      no.type = 'button'; no.className = 'btn ghost sm2'; no.textContent = '忽略';
      no.addEventListener('click', function () { handleReq(r.id, false); });
      btns.append(yes, no);
      box.appendChild(btns);
      listEl.appendChild(box);
    });

    /* 好友列表：与会话数据合并，显示最后一条消息与未读 */
    friends.forEach(function (f) {
      var conv = convs.find(function (c) { return c.peer_id === f.id; });
      var row = document.createElement('button');
      row.type = 'button';
      row.className = 'im-row' +
        (!aiMode && conv && conv.id === activeConv ? ' on' : '') +
        (conv && conv.unread > 0 ? ' unread' : '');
      var last = conv ? (conv.last_text || '暂无消息') : '发条消息开始聊天吧';
      row.innerHTML =
        avatar(f.nickname, f.avatar_url) +
        '<div class="im-row-info">' +
          '<div class="im-row-top">' +
            '<span class="im-row-name">' + esc(f.nickname) + '</span>' +
            (conv ? '<span class="im-row-time">' + esc(shortTime(conv.last_at)) + '</span>' : '') +
          '</div>' +
          '<div class="im-row-bottom">' +
            '<span class="im-row-last">' + esc(last) + '</span>' +
            (conv && conv.unread > 0
              ? '<span class="im-dot" title="' + conv.unread + ' 条未读"></span>' : '') +
          '</div>' +
        '</div>';
      row.addEventListener('click', function () {
        if (conv) openConv(conv); else startChatWith(f);
      });
      listEl.appendChild(row);
    });

    if (!friends.length && !requests.length) {
      var empty = document.createElement('p');
      empty.className = 'im-empty-mini';
      empty.textContent = '还没有好友，点右上角 ＋ 添加';
      listEl.appendChild(empty);
    }
  }

  /* ---------- 加载 ---------- */
  function loadConvs() {
    return api('GET', '/api/conversations').then(function (d) {
      convs = d.items || [];
      convsLoaded = true;
      renderList();
      maybeShowHomeGuide();
    });
  }

  function loadFriends() {
    return Promise.all([
      api('GET', '/api/friends'),
      api('GET', '/api/friends/requests')
    ]).then(function (rs) {
      friends = rs[0].friends || [];
      requests = rs[1].requests || [];
      friendsLoaded = true;
      reqBadge.hidden = requests.length === 0;
      reqBadge.textContent = requests.length;
      renderList();
      maybeShowHomeGuide();
    });
  }

  /* ---------- AI 对话 ---------- */
  function openAI() {
    aiMode = true;
    activeConv = 0;
    activePeer = null;
    setStage(true);                       /* 显示像素场景 */
    reactMood('neutral');
    document.getElementById('btnRemove').hidden = true;
    document.getElementById('btnExport').hidden = false;
    renderList();

    blank.hidden = true;
    chat.hidden = false;
    setChatOpen(true);

    document.getElementById('headName').textContent = '小鲸';
    document.getElementById('headSub').textContent = 'AI 导览员 · 在线';
    var av = document.getElementById('headAv');
    av.classList.add('ai');
    av.innerHTML = '<img src="' + AI_AVATAR + '" alt="小鲸">';

    bodyEl.replaceChildren();
    var hello = document.createElement('div');
    hello.className = 'im-date';
    hello.textContent = '和 AI 导览员小鲸对话';
    bodyEl.appendChild(hello);

    /* 拉取历史 */
    fetch('/api/chat/history', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : { messages: [] }; })
      .then(function (d) {
        var list = d.messages || [];
        aiRoundCount = countAIRounds(list);
        maybeShowAIExportGuide();
        if (!list.length) {
          addMsg('other', '你好，我是小鲸。有什么想聊的？');
          return;
        }
        bodyEl.replaceChildren();
        list.forEach(function (m) {
          var text = (m.text || '').replace(EMO_RE, '').trim();
          if (text) addMsg(m.role === 'user' ? 'me' : 'other', text);
        });
        scrollBottom();
      })
      .catch(function () {});
  }

  /* ---------- 打开会话 ---------- */
  function openConv(c) {
    aiMode = false;
    aiRoundCount = 0;
    if (aiExportGuide) aiExportGuide.hidden = true;
    dismissHomeGuide();
    setStage(false);                      /* 好友会话不显示场景 */
    document.getElementById('btnRemove').hidden = false;
    document.getElementById('btnExport').hidden = true;
    document.getElementById('headAv').classList.remove('ai');
    fillAvatar(document.getElementById('headAv'), c.nickname, c.avatar_url);
    activeConv = c.id;
    activePeer = { id: c.peer_id, nickname: c.nickname, real_name: c.real_name,
                   avatar_url: c.avatar_url };
    lastMsgId = 0;
    renderList();
    blank.hidden = true;
    chat.hidden = false;
    setChatOpen(true);

    document.getElementById('headName').textContent = c.nickname;
    document.getElementById('headSub').textContent =
      c.real_name + ' · ' + c.student_no;

    bodyEl.replaceChildren();
    clearQuote();
    if (multiMode) exitMulti();
    closeCtxMenu();
    api('GET', '/api/messages?conv=' + c.id).then(function (d) {
      if (activeConv !== c.id) return;        // 已切走则丢弃旧会话响应
      myId = d.me || 0;
      quotes = d.quotes || {};
      var msgs = d.messages || [];
      renderFresh(msgs, myId);
      if (d.has_older) {
        var tip = document.createElement('div');
        tip.className = 'im-date';
        tip.textContent = '仅显示最近 50 条，更早的消息未展示';
        bodyEl.insertBefore(tip, bodyEl.firstChild);
      }
      lastMsgId = msgs.length ? msgs[msgs.length - 1].id : 0;
      loadConvs();
    }).catch(function (e) { toast(e.message); });
  }

  function startChatWith(f) {
    aiMode = false;
    aiRoundCount = 0;
    if (aiExportGuide) aiExportGuide.hidden = true;
    dismissHomeGuide();
    setStage(false);                      /* 好友会话不显示场景 */
    document.getElementById('btnRemove').hidden = false;
    document.getElementById('btnExport').hidden = true;
    document.getElementById('headAv').classList.remove('ai');
    fillAvatar(document.getElementById('headAv'), f.nickname, f.avatar_url);
    var found = convs.find(function (c) { return c.peer_id === f.id; });
    if (found) { openConv(found); return; }

    /* 新好友尚无会话：先幂等建会话，成功后当作普通会话打开。
       否则 activeConv=0 会导致 send() 拦截，第一条消息永远发不出去。 */
    api('POST', '/api/conversations', { peer_id: f.id })
      .then(function (d) {
        openConv({ id: d.id, peer_id: f.id, nickname: f.nickname,
                   real_name: f.real_name, student_no: f.student_no,
                   avatar_url: f.avatar_url });
      })
      .catch(function (e) { toast(e.message); });
  }

  /* ---------- 消息渲染 ---------- */
  var lastDate = '';
  var lastSender = null;

  function appendMsg(m, me, animate) {
    if (m.id) {
      if (seenIds.has(m.id)) return;
      seenIds.add(m.id);
    }
    var dstr = dateLabel(m.created_at);
    if (dstr !== lastDate) {
      var div = document.createElement('div');
      div.className = 'im-date';
      div.textContent = dstr;
      bodyEl.appendChild(div);
      lastDate = dstr;
      lastSender = null;
    }

    var mine = m.sender_id === me;
    var same = lastSender === m.sender_id;
    var row = document.createElement('div');
    row.className = 'im-msg ' + (mine ? 'me' : 'other') +
                    ' ' + (same ? 'tight' : 'gap');
    if (m.id) row.setAttribute('data-mid', m.id);
    row._msg = m;                         // 右键菜单取原文用
    if (animate) row.style.opacity = '0';

    // 多选复选框（默认隐藏，进入多选时显示）
    var check = document.createElement('input');
    check.type = 'checkbox';
    check.className = 'im-ms-check';
    check.style.cssText = 'display:none;align-self:center;margin-right:6px;cursor:pointer;';
    check.checked = selectedIds.has(m.id);
    check.addEventListener('change', function () {
      if (check.checked) selectedIds.add(m.id); else selectedIds.delete(m.id);
      renderMultiBar();
    });
    row.appendChild(check);

    // 右键菜单
    row.addEventListener('contextmenu', function (e) {
      e.preventDefault();
      showCtxMenu(e.clientX, e.clientY, row);
    });

    var av = document.createElement('div');
    av.className = 'im-msg-av';
    if (!mine && activePeer && activePeer.avatar_url) {
      var img = document.createElement('img');
      img.src = activePeer.avatar_url;
      img.alt = '';
      av.appendChild(img);
    } else {
      // avatar() 返回 HTML 串，不能赋给 textContent（会字面显示标签）。
      // 无头像时只显示昵称首字即可。
      var name = mine ? '我' : (activePeer && activePeer.nickname) || '?';
      av.textContent = String(name).charAt(0);
    }

    var wrap = document.createElement('div');
    wrap.className = 'im-bubble-wrap';

    var bubble = document.createElement('div');
    bubble.className = 'im-bubble';

    // 转发标记（§9B.4：文本快照，from_conv 只作视觉提示）
    if (m.forward_from) {
      var fwd = document.createElement('div');
      fwd.textContent = '转发消息';
      fwd.style.cssText = 'font-size:var(--font-size-xs);color:var(--muted);margin-bottom:4px;' +
        'border-bottom:1px dashed var(--line-strong);padding-bottom:3px;';
      bubble.appendChild(fwd);
    }

    // 引用块（§9B.3）：摘要由服务端随消息返回，查不到则降级占位
    if (m.quote_id) {
      var q = quotes[String(m.quote_id)];
      var qbox = document.createElement('div');
      qbox.style.cssText = 'font-size:var(--font-size-xs);color:var(--muted);background:rgba(0,0,0,.05);' +
        'border-left:3px solid var(--primary);padding:4px 8px;margin-bottom:5px;border-radius:3px;' +
        'cursor:pointer;max-width:260px;';
      qbox.textContent = q
        ? senderName(q.sender_id) + '：' + q.content
        : '原消息已删除';
      qbox.title = '点击跳到原消息';
      qbox.addEventListener('click', function () {
        var orig = document.querySelector('.im-msg[data-mid="' + m.quote_id + '"]');
        if (orig) { orig.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
        else { toast('原消息不在当前加载范围内'); }
      });
      bubble.appendChild(qbox);
    }

    var body = document.createElement('div');
    body.textContent = m.content;        /* textContent 防 XSS */
    bubble.appendChild(body);

    var time = document.createElement('div');
    time.className = 'im-time' + (mine && m.read_at ? ' im-read' : '');
    time.textContent = shortTime(m.created_at) + (mine && m.read_at ? ' 已读' : '');

    // 「⋯」按钮：右键之外的可靠入口（触摸设备 / 浏览器拦截右键时仍可用）
    var more = document.createElement('button');
    more.type = 'button';
    more.className = 'im-msg-more';
    more.textContent = '⋯';
    more.title = '消息操作';
    more.style.cssText = 'border:0;background:none;color:var(--muted);font-size:18px;' +
      'line-height:1;cursor:pointer;padding:0 6px;opacity:.45;align-self:center;flex:none;';
    more.setAttribute('aria-label', '消息操作');
    more.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      var r = more.getBoundingClientRect();
      showCtxMenu(r.left - 110, r.bottom + 4, row);
    });
    row.addEventListener('mouseenter', function () { more.style.opacity = '1'; });
    row.addEventListener('mouseleave', function () { more.style.opacity = '.45'; });

    wrap.append(bubble, time);
    row.append(av, wrap, more);
    bodyEl.appendChild(row);

    if (animate) {
      requestAnimationFrame(function () {
        row.style.transition = 'opacity .2s';
        row.style.opacity = '1';
      });
    }

    lastSender = m.sender_id;
  }

  function renderFresh(msgs, me) {
    lastDate = '';
    lastSender = null;
    seenIds = new Set();         // 切换会话后重置去重集合
    bodyEl.replaceChildren();
    msgs.forEach(function (m) { appendMsg(m, me, false); });
    scrollBottom();
  }

  /* AI 用的简易气泡 */
  function addMsg(who, text) {
    var row = document.createElement('div');
    row.className = 'im-msg ' + (who === 'me' ? 'me' : 'other') + ' gap';

    var av = document.createElement('div');
    av.className = 'im-msg-av' + (who === 'other' ? ' ai' : '');
    if (who === 'other') {
      av.innerHTML = '<img src="' + AI_AVATAR + '" alt="">';
    } else {
      av.textContent = '我';
    }

    var wrap = document.createElement('div');
    wrap.className = 'im-bubble-wrap';
    var bubble = document.createElement('div');
    bubble.className = 'im-bubble';
    bubble.textContent = text;
    wrap.appendChild(bubble);

    row.append(av, wrap);
    bodyEl.appendChild(row);
    scrollBottom();
    return bubble;
  }

  function scrollBottom() {
    bodyEl.scrollTop = bodyEl.scrollHeight;
  }

  /* ---------- 轮询 ---------- */
  function poll() {
    if (!activeConv) return;
    var pollConv = activeConv;       // 固定发起时的会话，回调里校验未切换
    var pollAfter = lastMsgId;
    api('GET', '/api/messages?conv=' + pollConv + '&after=' + pollAfter)
      .then(function (d) {
        if (activeConv !== pollConv) return;   // 用户已切走，丢弃旧会话的在途响应
        var msgs = d.messages || [];
        if (msgs.length) {
          myId = d.me || myId;
          if (d.quotes) {
            Object.keys(d.quotes).forEach(function (k) { quotes[k] = d.quotes[k]; });
          }
          msgs.forEach(function (m) { appendMsg(m, myId, true); });
          if (msgs[msgs.length - 1].id > lastMsgId) {
            lastMsgId = msgs[msgs.length - 1].id;
          }
          scrollBottom();
          loadConvs();
        }
      })
      .catch(function () {});
  }

  /* ---------- 发送 ---------- */
  function send() {
    var text = input.value.trim();
    if (!text || sending) return;
    if (aiBusy) return;

    if (!aiMode && !activeConv) {
      /* 会话尚未建好（新好友点击后接口在途），保留输入内容，提示重试 */
      toast('会话准备中，请稍后再发');
      return;
    }

    sending = true;
    sendBtn.disabled = true;
    input.value = '';
    autoGrow();

    if (aiMode) { sendAI(text); return; }

    var sendConv = activeConv;
    var qid = quoteTarget ? quoteTarget.id : null;
    clearQuote();
    api('POST', '/api/messages', { conv: sendConv, content: text, quote_id: qid })
      .then(function (d) {
        if (activeConv !== sendConv) return;   // 已切走则不再操作当前视图
        appendMsg({
          id: d.id,                  // 带 id，配合 seenIds 防止在途 poll 重复追加
          sender_id: myId,
          content: text,
          quote_id: d.quote_id,
          created_at: d.at,
          read_at: null
        }, myId, true);
        if (d.id > lastMsgId) lastMsgId = d.id;
        scrollBottom();
        loadConvs();
      })
      .catch(function (e) {
        input.value = text;
        toast(e.message);
      })
      .finally(function () {
        sending = false;
        sendBtn.disabled = false;
        input.focus();
      });
  }

  /* ---------- AI 流式发送 ---------- */
  function sendAI(text) {
    aiBusy = true;
    var gotReply = false;
    addMsg('me', text);
    var bubble = addMsg('other', '…');
    bubble.classList.add('typing');

    fetch('/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': csrf
      },
      body: JSON.stringify({ text: text })
    })
      .then(function (r) {
        if (!r.ok) {
          return r.json().catch(function () { return {}; }).then(function (d) {
            throw new Error(d.error || ('请求失败 ' + r.status));
          });
        }
        var reader = r.body.getReader();
        var decoder = new TextDecoder();
        var buf = '';

        function pump() {
          return reader.read().then(function (res) {
            if (res.done) return;
            buf += decoder.decode(res.value, { stream: true });
            var parts = buf.split('\n\n');
            buf = parts.pop();
            parts.forEach(function (chunk) {
              var ev = '', data = '';
              chunk.split('\n').forEach(function (line) {
                if (line.indexOf('event: ') === 0) ev = line.slice(7).trim();
                else if (line.indexOf('data: ') === 0) data = line.slice(6);
              });
              if (!data) return;
              var obj;
              try { obj = JSON.parse(data); } catch (e) { return; }
              if (ev === 'delta') {
                bubble.classList.remove('typing');
                if (obj.text) gotReply = true;
                bubble.textContent += obj.text || '';
                scrollBottom();
              } else if (ev === 'end') {
                /* 情绪联动：驱动场景里的像素角色换表情 */
                if (obj.emotion) reactMood(obj.emotion);
              } else if (ev === 'error') {
                bubble.classList.remove('typing');
                gotReply = false;
                bubble.textContent = obj.message || AI_UNAVAILABLE;
              }
            });
            return pump();
          });
        }
        return pump();
      })
      .catch(function () {
        bubble.classList.remove('typing');
        gotReply = false;
        bubble.textContent = AI_UNAVAILABLE;
      })
      .finally(function () {
        bubble.textContent = bubble.textContent.replace(EMO_RE, '').trim();
        if (gotReply && bubble.textContent && bubble.textContent !== '…') {
          aiRoundCount++;
          maybeShowAIExportGuide();
        }
        aiBusy = false;
        sending = false;
        sendBtn.disabled = false;
        input.focus();
      });
  }

  function autoGrow() {
    input.style.height = 'auto';
    input.style.height = Math.min(120, input.scrollHeight) + 'px';
  }

  /* ---------- 加好友 ---------- */
  var addModal = document.getElementById('addModal');
  var searchNo = document.getElementById('searchNo');
  var searchResult = document.getElementById('searchResult');
  var noteField = document.getElementById('noteField');
  var sendReqBtn = document.getElementById('sendReq');
  var addHint = document.getElementById('addHint');
  var foundUser = null;

  function openAdd() {
    dismissHomeGuide();
    addModal.hidden = false;
    searchNo.value = '';
    searchResult.hidden = true;
    noteField.hidden = true;
    sendReqBtn.disabled = true;
    addHint.textContent = '';
    foundUser = null;
    searchNo.focus();
  }
  function closeAdd() { addModal.hidden = true; }

  document.getElementById('btnAdd').addEventListener('click', openAdd);
  document.getElementById('btnAdd2').addEventListener('click', openAdd);
  addModal.querySelectorAll('[data-close]').forEach(function (el) {
    el.addEventListener('click', closeAdd);
  });

  function doSearch() {
    var no = searchNo.value.trim();
    if (!no) { addHint.textContent = '请输入学号'; return; }
    addHint.textContent = '查找中…';
    api('GET', '/api/users/search?no=' + encodeURIComponent(no))
      .then(function (d) {
        if (!d.found) {
          foundUser = null;
          searchResult.hidden = true;
          noteField.hidden = true;
          sendReqBtn.disabled = true;
          addHint.textContent = '没有找到该学号';
          return;
        }
        foundUser = d.user;
        searchResult.hidden = false;
        searchResult.innerHTML =
          '<div class="im-av">' + avatar(d.user.nickname) + '</div>' +
          '<div class="im-result-main">' +
            '<div class="im-result-name">' + esc(d.user.nickname) + '</div>' +
            '<div class="im-result-meta">' + esc(d.user.real_name) + ' · ' +
              esc(d.user.student_no) + '</div>' +
          '</div>';
        if (d.user.is_friend) {
          addHint.textContent = '已经是好友了';
          sendReqBtn.disabled = true;
        } else {
          noteField.hidden = false;
          sendReqBtn.disabled = false;
          addHint.textContent = '';
        }
      })
      .catch(function (e) { addHint.textContent = e.message; });
  }

  document.getElementById('searchBtn').addEventListener('click', doSearch);
  searchNo.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { e.preventDefault(); doSearch(); }
  });

  sendReqBtn.addEventListener('click', function () {
    if (!foundUser) return;
    sendReqBtn.disabled = true;
    api('POST', '/api/friends/request', {
      student_no: foundUser.student_no,
      note: document.getElementById('reqNote').value.trim()
    }).then(function (d) {
      addHint.textContent = d.message || '申请已发送';
      closeAdd();
      toast(d.message || '申请已发送');
    }).catch(function (e) {
      addHint.textContent = e.message;
      sendReqBtn.disabled = false;
    });
  });

  function handleReq(id, accept) {
    api('POST', '/api/friends/handle', { id: id, accept: accept })
      .then(function () {
        loadFriends();
        loadConvs();
      })
      .catch(function (e) { toast(e.message); });
  }

  document.getElementById('btnExport').addEventListener('click', function () {
    if (!aiMode) return;
    dismissAIExportGuide();
    window.location.href = '/api/chat/export?format=md';
    toast('对话记录已开始下载');
  });

  document.getElementById('btnRemove').addEventListener('click', function () {
    if (!activePeer || !activePeer.id) return;
    if (!window.confirm('删除好友「' + activePeer.nickname + '」？聊天记录会一并清除。')) return;
    api('POST', '/api/friends/remove', { id: activePeer.id })
      .then(function () {
        activeConv = 0;
        activePeer = null;
        chat.hidden = true;
        blank.hidden = false;
        setChatOpen(false);
        loadFriends();
        loadConvs();
      })
      .catch(function (e) { toast(e.message); });
  });

  /* ---------- 提示 ---------- */
  function toast(msg) {
    var t = document.createElement('div');
    t.className = 'toast';
    t.setAttribute('role', 'status');
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(function () { t.remove(); }, 2600);
  }

  /* ---------- 启动 ---------- */
  var backBtn = document.getElementById('imBack');
  if (backBtn) {
    backBtn.addEventListener('click', function () {
      setChatOpen(false);
    });
  }
  if (document.getElementById('homeGuideDismiss')) {
    document.getElementById('homeGuideDismiss').addEventListener('click', dismissHomeGuide);
  }
  if (document.getElementById('aiExportGuideDismiss')) {
    document.getElementById('aiExportGuideDismiss')
      .addEventListener('click', dismissAIExportGuide);
  }

  document.addEventListener('click', function (e) {
    if (ctxMenu && !ctxMenu.contains(e.target)) closeCtxMenu();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { closeCtxMenu(); if (multiMode) exitMulti(); }
  });

  input.addEventListener('input', autoGrow);
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });
  sendBtn.addEventListener('click', send);

  loadConvs().catch(function () {});
  loadFriends().catch(function () {});
  setInterval(poll, 2000);
  setInterval(function () { loadFriends().catch(function () {}); }, 15000);
})();
