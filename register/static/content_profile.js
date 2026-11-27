(function () {
  var csrf = document.querySelector('meta[name="csrf"]');
  var token = csrf ? csrf.content : '';
  var view = 'owned', page = 1, total = 0, seq = 0, loading = false;
  var list = document.getElementById('ownedList');
  var empty = document.getElementById('profileEmpty');
  var more = document.getElementById('profileMore');
  var toastTimer;
  function esc(v) { return String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }
  function showError(message) {
    var toast = document.getElementById('toast');
    toast.textContent = message; toast.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { toast.hidden = true; }, 5000);
  }
  function request(url, opts) {
    opts = opts || {}; opts.headers = opts.headers || {}; opts.headers['X-CSRF'] = token;
    return fetch(url, opts).then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { if (!r.ok) throw new Error(d.error || '请求失败'); return d; }); });
  }
  function card(i) {
    var tags = (i.tags || '').split(',').filter(Boolean).map(function (t) { return '<span class="tag">' + esc(t) + '</span>'; }).join('');
    var state = i.moderation_state === 'revoked' ? '<span class="tag">已撤销：' + esc(i.moderation_reason || '请查看详情') + '</span>' : '';
    var owner = view === 'owned' ? '<span class="idea-stat">★ ' + (i.favorite_count || 0) + ' · ♥ ' + (i.like_count || 0) + ' · 讨论 ' + (i.comment_count || 0) + '</span>' : '';
    var body = '<span class="tag">' + esc(i.category_label || i.category) + '</span>' + owner +
      '<h3>' + esc(i.title) + '</h3><p class="idea-excerpt">' + esc((i.content || '').slice(0, 90)) + '</p><div class="idea-tags">' + tags + state + '</div>' +
      '<p class="idea-meta">' + esc(view === 'owned' ? i.status : (i.author_nickname || i.author_id)) + ' · ' + esc(view === 'owned' ? i.updated_at : i.favorited_at) + '</p>';
    if (view !== 'favorites') return '<a class="idea-card" href="/ideas/' + Number(i.id) + '">' + body + '</a>';
    return '<article class="idea-card" data-id="' + Number(i.id) + '"><a class="idea-card-link" href="/ideas/' + Number(i.id) + '">' + body + '</a><button class="btn ghost sm2 remove-favorite" type="button">取消收藏</button></article>';
  }
  function updateEmpty() {
    empty.hidden = list.children.length > 0;
    more.hidden = list.children.length >= total;
  }
  function load(reset) {
    if (loading && !reset) return;
    if (reset) page = 1;
    var current = ++seq; loading = true; more.disabled = true;
    var params = new URLSearchParams({page: page, size: 20, q: document.getElementById('profileQ').value.trim(), category: document.getElementById('profileCategory').value, tag: document.getElementById('profileTag').value.trim()});
    if (view === 'owned') { params.set('status', document.getElementById('ownedStatus').value); params.set('sort', document.getElementById('ownedSort').value); }
    else { params.set('sort', document.getElementById('favSort').value); }
    request('/api/profile/' + (view === 'owned' ? 'ideas' : 'favorites') + '?' + params).then(function (d) {
      if (current !== seq) return;
      list = document.getElementById(view === 'owned' ? 'ownedList' : 'favoriteList');
      if (reset) list.innerHTML = '';
      (d.items || []).forEach(function (i) { list.insertAdjacentHTML('beforeend', card(i)); });
      total = d.total || 0; updateEmpty();
      var unavailable = document.getElementById('unavailable');
      unavailable.hidden = !d.unavailable_count; unavailable.textContent = d.unavailable_count ? '部分收藏已不可见，共 ' + d.unavailable_count + ' 条。' : '';
    }).catch(function (e) { if (current === seq) showError(e.message); })
      .finally(function () { if (current === seq) { loading = false; more.disabled = false; } });
  }
  function removeFavorite(button) {
    var article = button.closest('.idea-card');
    if (!article) return;
    button.disabled = true;
    request('/api/ideas/' + article.dataset.id + '/favorite', {method: 'POST'}).then(function (d) {
      if (!d.favorited) {
        article.remove(); total = Math.max(0, total - 1); updateEmpty();
        document.getElementById('favTotal').textContent = Math.max(0, Number(document.getElementById('favTotal').textContent) - 1);
      } else showError('收藏状态已变化，请刷新后重试');
    }).catch(function (e) { showError(e.message); })
      .finally(function () { button.disabled = false; });
  }
  function select(next) {
    view = next;
    document.getElementById('panelOwned').hidden = view !== 'owned'; document.getElementById('panelFavorites').hidden = view !== 'favorites';
    ['Owned', 'Favorites'].forEach(function (name) { var active = name.toLowerCase() === view; var tab = document.getElementById('tab' + name); tab.setAttribute('aria-selected', String(active)); tab.tabIndex = active ? 0 : -1; });
    list = document.getElementById(view === 'owned' ? 'ownedList' : 'favoriteList');
    load(true);
  }
  ['Owned', 'Favorites'].forEach(function (name) {
    document.getElementById('tab' + name).onclick = function () { select(name.toLowerCase()); };
    document.getElementById('tab' + name).onkeydown = function (e) {
      if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        e.preventDefault(); select(view === 'owned' ? 'favorites' : 'owned');
        document.getElementById(view === 'owned' ? 'tabOwned' : 'tabFavorites').focus();
      }
    };
  });
  ['ownedStatus', 'ownedSort', 'favSort', 'profileCategory'].forEach(function (id) { document.getElementById(id).onchange = function () { load(true); }; });
  ['profileQ', 'profileTag'].forEach(function (id) {
    document.getElementById(id).onkeydown = function (e) { if (e.key === 'Enter') load(true); };
  });
  document.getElementById('favoriteList').onclick = function (e) { if (e.target.closest('.remove-favorite')) removeFavorite(e.target.closest('.remove-favorite')); };
  document.getElementById('btnProfileMore').onclick = function () { if (!loading) { page++; load(false); } };
  request('/api/categories').then(function (d) { (d.items || []).forEach(function (c) { var o = document.createElement('option'); o.value = c.value; o.textContent = c.label; document.getElementById('profileCategory').appendChild(o); }); }).catch(function (e) { showError(e.message); });
  request('/api/tags?limit=200').then(function (d) {
    var options = document.getElementById('profileTag');
    (d.items || []).forEach(function (t) { var o = document.createElement('option'); o.value = t.name; options.appendChild(o); });
  }).catch(function () {});
  request('/api/profile/summary').then(function (d) {
    ['Published', 'Draft', 'Archived', 'Likes', 'Favorites', 'Comments'].forEach(function (k) { document.getElementById('s' + k).textContent = d[k.toLowerCase()] || 0; });
    document.getElementById('favTotal').textContent = d.visible_favorites || 0;
  }).catch(function () {});
  select(document.getElementById('main').dataset.initialView === 'favorites' ? 'favorites' : 'owned');
})();
