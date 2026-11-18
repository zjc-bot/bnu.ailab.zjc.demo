/* 对话：SSE 流式接收 + 逐字渲染 + 情绪联动 */
(function () {
  'use strict';

  var input = document.getElementById('imInput');
  var sendBtn = document.getElementById('imSend');
  var body = document.getElementById('imBody');
  var csrf = (document.querySelector('meta[name="csrf"]') || {}).content || '';
  if (!input || !sendBtn || !body) return;

  input.disabled = false;
  sendBtn.disabled = false;

  var busy = false;
  var EMO_RE = /\[\[emo:\w+\]\]/g;

  function scrollBottom() {
    body.scrollTop = body.scrollHeight;
  }

  function makeAvatar() {
    var av = document.createElement('img');
    av.className = 'im-msg-av';
    av.src = document.querySelector('.im-head-av')
      ? document.querySelector('.im-head-av').src
      : '';
    av.alt = '';
    return av;
  }

  function addMsg(who, text) {
    var wrap = document.createElement('div');
    wrap.className = 'im-msg ' + (who === 'me' ? 'me' : 'other');

    var bubble = document.createElement('div');
    bubble.className = 'im-bubble';
    bubble.textContent = text || '';

    if (who === 'me') {
      var mine = document.createElement('div');
      mine.className = 'im-msg-av letter';
      mine.textContent = '我';
      wrap.append(mine, bubble);
    } else {
      wrap.append(makeAvatar(), bubble);
    }

    body.appendChild(wrap);
    scrollBottom();
    return bubble;
  }

  function typingBubble() {
    var b = addMsg('other', '');
    b.classList.add('typing');
    b.textContent = '……';
    return b;
  }

  function handleEvent(raw, bubble) {
    var ev = '', data = '';
    raw.split('\n').forEach(function (l) {
      if (l.indexOf('event: ') === 0) ev = l.slice(7).trim();
      else if (l.indexOf('data: ') === 0) data = l.slice(6);
    });
    if (!data) return;

    var obj;
    try { obj = JSON.parse(data); } catch (e) { return; }

    if (ev === 'delta') {
      if (bubble.classList.contains('typing')) {
        bubble.classList.remove('typing');
        bubble.textContent = '';
      }
      bubble.textContent += obj.text || '';
      scrollBottom();
    } else if (ev === 'end') {
      bubble.textContent = bubble.textContent.replace(EMO_RE, '').trim();
      scrollBottom();
    } else if (ev === 'error') {
      bubble.classList.remove('typing');
      bubble.textContent = obj.message || '出错了';
    }
  }

  function send() {
    var text = input.value.trim();
    if (!text || busy) return;

    busy = true;
    sendBtn.disabled = true;
    input.value = '';
    autoGrow();

    addMsg('me', text);
    var bubble = typingBubble();

    fetch('/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': csrf,
      },
      body: JSON.stringify({ text: text }),
    })
      .then(function (r) {
        if (!r.ok) {
          return r.json().catch(function () { return {}; }).then(function (d) {
            throw new Error(d.error || ('请求失败 ' + r.status));
          });
        }
        if (!r.body || !r.body.getReader) {
          throw new Error('浏览器不支持流式响应');
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
            parts.forEach(function (p) {
              if (p.trim()) handleEvent(p, bubble);
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
        busy = false;
        sendBtn.disabled = false;
        input.focus();
      });
  }

  /* 输入框自适应高度 */
  function autoGrow() {
    input.style.height = 'auto';
    input.style.height = Math.min(120, input.scrollHeight) + 'px';
  }

  input.addEventListener('input', autoGrow);
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  sendBtn.addEventListener('click', send);

  /* 加载历史对话：有记录时清掉静态欢迎语，逐条渲染 */
  function loadHistory() {
    fetch('/api/chat/history', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : { messages: [] }; })
      .then(function (d) {
        var list = d.messages || [];
        if (!list.length) return;
        body.textContent = '';
        list.forEach(function (m) {
          var text = (m.text || '').replace(EMO_RE, '').trim();
          addMsg(m.role === 'user' ? 'me' : 'other', text);
        });
        scrollBottom();
      })
      .catch(function () { /* 历史拉取失败不影响新对话 */ });
  }

  /* 打开页面时滚到最新并恢复历史 */
  scrollBottom();
  loadHistory();
})();
