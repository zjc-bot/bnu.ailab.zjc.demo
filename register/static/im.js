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

  var tab = 'chats';
  var convs = [];
  var friends = [];
  var requests = [];
  var activeConv = 0;
  var activePeer = null;
  var myId = 0;
  var lastMsgId = 0;
  var sending = false;
  var aiMode = false;          /* 当前是否在跟 AI 对话 */
  var aiBusy = false;
  var EMO_RE = /\[\[emo:\w+\]\]/g;
  var AI_AVATAR = '/static/whale/avatar.webp?v=1';   /* 小鲸头像 */

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

  /* ---------- 左栏渲染 ---------- */
  function renderList() {
    listEl.replaceChildren();

    if (tab === 'chats') {
      /* 固定的 AI 会话项，排在最顶部 */
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
      aiBtn.addEventListener('click', function () { openAI(); });
      listEl.appendChild(aiBtn);

      if (!convs.length) {
        var p = document.createElement('p');
        p.className = 'im-empty-mini';
        p.textContent = '还没有会话，点右上角 ＋ 加好友';
        listEl.appendChild(p);
        return;
      }
      convs.forEach(function (c) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'im-row' +
          (c.id === activeConv ? ' on' : '') +
          (c.unread > 0 ? ' unread' : '');
        btn.innerHTML =
          avatar(c.nickname, c.avatar_url) +
          '<div class="im-row-info">' +
            '<div class="im-row-top">' +
              '<span class="im-row-name">' + esc(c.nickname) + '</span>' +
              '<span class="im-row-time">' + esc(shortTime(c.last_at)) + '</span>' +
            '</div>' +
            '<div class="im-row-bottom">' +
              '<span class="im-row-last">' + esc(c.last_text || '暂无消息') + '</span>' +
              (c.unread > 0
                ? '<span class="im-dot" title="' + c.unread + ' 条未读"></span>' : '') +
            '</div>' +
          '</div>';
        btn.addEventListener('click', function () { openConv(c); });
        listEl.appendChild(btn);
      });
      return;
    }

    /* 好友 tab：申请置顶 */
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
      yes.type = 'button';
      yes.className = 'btn primary sm2';
      yes.textContent = '同意';
      yes.addEventListener('click', function () { handleReq(r.id, true); });

      var no = document.createElement('button');
      no.type = 'button';
      no.className = 'btn ghost sm2';
      no.textContent = '忽略';
      no.addEventListener('click', function () { handleReq(r.id, false); });

      btns.append(yes, no);
      box.appendChild(btns);
      listEl.appendChild(box);
    });

    if (!friends.length && !requests.length) {
      var empty = document.createElement('p');
      empty.className = 'im-empty-mini';
      empty.textContent = '还没有好友，点右上角 ＋ 添加';
      listEl.appendChild(empty);
      return;
    }

    friends.forEach(function (f) {
      var row = document.createElement('button');
      row.type = 'button';
      row.className = 'im-row';
      row.innerHTML =
        avatar(f.nickname, f.avatar_url) +
        '<div class="im-row-info">' +
          '<div class="im-row-top"><span class="im-row-name">' + esc(f.nickname) + '</span></div>' +
          '<div class="im-row-bottom"><span class="im-row-last">' + esc(f.real_name) + '</span></div>' +
        '</div>';
      row.addEventListener('click', function () { startChatWith(f); });
      listEl.appendChild(row);
    });
  }

  /* ---------- 加载 ---------- */
  function loadConvs() {
    return api('GET', '/api/conversations').then(function (d) {
      convs = d.items || [];
      renderList();
    });
  }

  function loadFriends() {
    return Promise.all([
      api('GET', '/api/friends'),
      api('GET', '/api/friends/requests')
    ]).then(function (rs) {
      friends = rs[0].friends || [];
      requests = rs[1].requests || [];
      reqBadge.hidden = requests.length === 0;
      reqBadge.textContent = requests.length;
      renderList();
    });
  }

  /* ---------- AI 对话 ---------- */
  function openAI() {
    aiMode = true;
    activeConv = 0;
    activePeer = null;
    document.getElementById('btnRemove').hidden = true;
    document.getElementById('btnExport').hidden = false;
    renderList();

    blank.hidden = true;
    chat.hidden = false;

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

    document.getElementById('headName').textContent = c.nickname;
    document.getElementById('headSub').textContent =
      c.real_name + ' · ' + c.student_no;

    bodyEl.replaceChildren();
    api('GET', '/api/messages?conv=' + c.id).then(function (d) {
      myId = d.me || 0;
      var msgs = d.messages || [];
      renderFresh(msgs, myId);
      lastMsgId = msgs.length ? msgs[msgs.length - 1].id : 0;
      loadConvs();
    }).catch(function (e) { toast(e.message); });
  }

  function startChatWith(f) {
    aiMode = false;
    document.getElementById('btnRemove').hidden = false;
    document.getElementById('btnExport').hidden = true;
    document.getElementById('headAv').classList.remove('ai');
    fillAvatar(document.getElementById('headAv'), f.nickname, f.avatar_url);
    var found = convs.find(function (c) { return c.peer_id === f.id; });
    if (found) { openConv(found); return; }

    blank.hidden = true;
    chat.hidden = false;
    activeConv = 0;
    activePeer = f;
    document.getElementById('headName').textContent = f.nickname;
    document.getElementById('headSub').textContent = f.real_name + ' · ' + f.student_no;

    bodyEl.replaceChildren();
    var tip = document.createElement('p');
    tip.className = 'im-date';
    tip.textContent = '发条消息开始聊天吧';
    bodyEl.appendChild(tip);
    lastDate = '';
    lastSender = null;
    lastMsgId = 0;
  }

  /* ---------- 消息渲染 ---------- */
  var lastDate = '';
  var lastSender = null;

  function appendMsg(m, me, animate) {
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
    if (animate) row.style.opacity = '0';

    var av = document.createElement('div');
    av.className = 'im-msg-av';
    if (!mine && activePeer && activePeer.avatar_url) {
      var img = document.createElement('img');
      img.src = activePeer.avatar_url;
      img.alt = '';
      av.appendChild(img);
    } else {
      av.textContent = mine ? '我' : avatar(activePeer && activePeer.nickname);
    }

    var wrap = document.createElement('div');
    wrap.className = 'im-bubble-wrap';

    var bubble = document.createElement('div');
    bubble.className = 'im-bubble';
    bubble.textContent = m.content;      /* textContent 防 XSS */

    var time = document.createElement('div');
    time.className = 'im-time' + (mine && m.read_at ? ' im-read' : '');
    time.textContent = shortTime(m.created_at) + (mine && m.read_at ? ' 已读' : '');

    wrap.append(bubble, time);
    row.append(av, wrap);
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
    api('GET', '/api/messages?conv=' + activeConv + '&after=' + lastMsgId)
      .then(function (d) {
        var msgs = d.messages || [];
        if (msgs.length) {
          myId = d.me || myId;
          msgs.forEach(function (m) { appendMsg(m, myId, true); });
          lastMsgId = msgs[msgs.length - 1].id;
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

    sending = true;
    sendBtn.disabled = true;
    input.value = '';
    autoGrow();

    if (aiMode) { sendAI(text); return; }
    if (!activeConv) { toast('请先选择一个会话'); sending = false; sendBtn.disabled = false; return; }

    api('POST', '/api/messages', { conv: activeConv, content: text })
      .then(function (d) {
        appendMsg({
          sender_id: myId,
          content: text,
          created_at: d.at,
          read_at: null
        }, myId, true);
        lastMsgId = d.id;
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
                bubble.textContent += obj.text || '';
                scrollBottom();
              } else if (ev === 'error') {
                bubble.classList.remove('typing');
                bubble.textContent = obj.message || '出错了';
              }
            });
            return pump();
          });
        }
        return pump();
      })
      .catch(function (e) {
        bubble.classList.remove('typing');
        bubble.textContent = e.message;
      })
      .finally(function () {
        bubble.textContent = bubble.textContent.replace(EMO_RE, '').trim();
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
        loadFriends();
        loadConvs();
      })
      .catch(function (e) { toast(e.message); });
  });

  /* ---------- Tab 切换 ---------- */
  document.querySelectorAll('.im-tab').forEach(function (b) {
    b.addEventListener('click', function () {
      document.querySelectorAll('.im-tab').forEach(function (x) {
        x.classList.remove('on');
      });
      b.classList.add('on');
      tab = b.dataset.tab;
      renderList();
    });
  });

  /* ---------- 提示 ---------- */
  function toast(msg) {
    var t = document.createElement('div');
    t.textContent = msg;
    t.style.cssText =
      'position:fixed;left:50%;top:70px;transform:translateX(-50%);' +
      'background:#111827;color:#fff;padding:9px 16px;border-radius:8px;' +
      'font-size:13px;z-index:200;box-shadow:0 8px 24px rgba(0,0,0,.2)';
    document.body.appendChild(t);
    setTimeout(function () { t.remove(); }, 2600);
  }

  /* ---------- 启动 ---------- */
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
