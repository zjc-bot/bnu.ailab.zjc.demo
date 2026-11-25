// 想法广场 / 详情 / 发布 —— 原生 JS，沿用现有 CSRF 头约定。
(function () {
  var csrf = document.querySelector('meta[name="csrf"]');
  var CSRF = csrf ? csrf.content : '';
  var list = document.getElementById('ideaList');
  var toastEl = document.getElementById('toast');
  var page = 1, total = 0;

  function toast(msg) {
    if (!toastEl) return;
    toastEl.textContent = msg; toastEl.hidden = false;
    setTimeout(function () { toastEl.hidden = true; }, 2200);
  }
  function esc(v) {
    return String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function req(url, opts) {
    opts = opts || {};
    opts.headers = opts.headers || {};
    opts.headers['X-CSRF'] = CSRF;
    opts.headers['Content-Type'] = 'application/json';
    return fetch(url, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) throw new Error(d.error || ('请求失败 ' + r.status));
        return d;
      });
    });
  }

  // ---------- 广场 ----------
  if (list) {
    var fCategory = document.getElementById('fCategory');
    var fTag = document.getElementById('fTag');
    var fSort = document.getElementById('fSort');
    var empty = document.getElementById('ideaEmpty');
    var more = document.getElementById('ideaMore');

    function card(i) {
      var tags = (i.tags || '').split(',').filter(function (t) { return t.trim(); })
        .map(function (t) { return '<span class="tag">' + esc(t.trim()) + '</span>'; }).join('');
      var excerpt = (i.content || '').replace(/\s+/g, ' ').slice(0, 90);
      return '<a class="idea-card" href="/ideas/' + i.id + '">' +
        '<span class="idea-stat">★ ' + (i.favorite_count || 0) + ' · ♥ ' + (i.like_count || 0) + '</span>' +
        '<h3>' + esc(i.title) + '</h3>' +
        '<p class="idea-excerpt">' + esc(excerpt) + '</p>' +
        '<div class="idea-tags">' + tags + '</div>' +
        '<p class="idea-meta">' + esc(i.author_nickname || i.author_id) + ' · ' + esc(i.created_at) + '</p></a>';
    }
    function load(reset) {
      if (reset) page = 1;
      var q = '?category=' + encodeURIComponent(fCategory.value) +
        '&tag=' + encodeURIComponent(fTag.value.trim()) + '&page=' + page + '&size=20';
      req('/api/ideas' + q).then(function (d) {
        var items = d.items || []; total = d.total || 0;
        if (reset) list.innerHTML = '';
        items.forEach(function (i) { list.insertAdjacentHTML('beforeend', card(i)); });
        empty.hidden = items.length > 0 || page > 1;
        more.hidden = list.children.length >= total;
        if (fSort.value === 'hot') {
          Array.prototype.slice.call(list.children).sort(function (a, b) {
            return Number(b.dataset.hot || 0) - Number(a.dataset.hot || 0);
          });
        }
      }).catch(function (e) { toast(e.message); });
    }
    fCategory.onchange = function () { load(true); };
    fTag.onkeydown = function (e) { if (e.key === 'Enter') load(true); };
    document.getElementById('btnMore').onclick = function () { page++; load(false); };
    load(true);
  }

  // ---------- 发布 / 编辑 ----------
  var form = document.getElementById('ideaForm');
  if (form) {
    form.onsubmit = function (e) {
      e.preventDefault();
      var id = form.dataset.ideaId;
      var payload = {
        title: document.getElementById('iTitle').value.trim(),
        content: document.getElementById('iContent').value.trim(),
        category: document.getElementById('iCategory').value,
        visibility: document.getElementById('iVisibility').value,
        tags: document.getElementById('iTags').value.trim()
      };
      var url = id ? '/api/ideas/' + id : '/api/ideas';
      var method = id ? 'PUT' : 'POST';
      req(url, { method: method, body: JSON.stringify(payload) }).then(function (d) {
        toast(id ? '已保存' : '发布成功');
        setTimeout(function () { location.href = '/ideas/' + (d.id || id); }, 500);
      }).catch(function (err) { document.getElementById('formErr').textContent = err.message; });
    };
  }

  // ---------- 详情 ----------
  var main = document.getElementById('main');
  if (main && main.dataset.ideaId) {
    var id = main.dataset.ideaId;
    var btnFav = document.getElementById('btnFav');
    var btnLike = document.getElementById('btnLike');
    function toggle(kind, btn, counter, activeText, idleText) {
      req('/api/ideas/' + id + '/' + kind, { method: 'POST' }).then(function (d) {
        var on = kind === 'favorite' ? d.favorited : d.liked;
        btn.textContent = on ? activeText : idleText;
        btn.setAttribute('aria-pressed', String(on));
        // 计数以服务端为准：重新拉详情
        req('/api/ideas/' + id).then(function (item) {
          document.getElementById('favCount').textContent = item.favorite_count;
          document.getElementById('likeCount').textContent = item.like_count;
        }).catch(function () {});
      }).catch(function (e) { toast(e.message); });
    }
    if (btnFav) btnFav.onclick = function () { toggle('favorite', btnFav, 'favCount', '★ 已收藏', '☆ 收藏'); };
    if (btnLike) btnLike.onclick = function () { toggle('like', btnLike, 'likeCount', '♥ 已赞', '♡ 赞'); };

    var btnDelete = document.getElementById('btnDelete');
    if (btnDelete) btnDelete.onclick = function () {
      if (!confirm('确定删除这条想法？此操作不可恢复。')) return;
      req('/api/ideas/' + id, { method: 'DELETE' }).then(function () {
        toast('已删除'); setTimeout(function () { location.href = '/ideas'; }, 500);
      }).catch(function (e) { toast(e.message); });
    };

    var commentForm = document.getElementById('commentForm');
    if (commentForm) commentForm.onsubmit = function (e) {
      e.preventDefault();
      var input = document.getElementById('commentInput');
      if (!input.value.trim()) return;
      req('/api/ideas/' + id + '/comments', { method: 'POST', body: JSON.stringify({ content: input.value.trim() }) })
        .then(function () { location.reload(); })
        .catch(function (err) { toast(err.message); });
    };
  }
})();
