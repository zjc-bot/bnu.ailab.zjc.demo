'use strict';

const csrf = (document.querySelector('meta[name="csrf"]') || {}).content || '';

const state = {
  q: '',
  page: 1,
  size: 20,
  sort: 'student_no',
  order: 'asc',
  major: '',
};
let lastTotal = 0;

const $ = (id) => document.getElementById(id);
const rowsEl = $('rows');

/* ---------- 基础请求 ---------- */
async function api(url, opts = {}) {
  const res = await fetch(url, {
    credentials: 'same-origin',
    ...opts,
    // headers 必须合并：opts.headers 若只带 X-CSRF-Token，整体覆盖会丢掉
    // Content-Type，导致 Flask get_json() 返回 None、增删改必失败。
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
  });
  if (res.status === 401) {
    location.href = '/login';
    throw new Error('未登录');
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || '请求失败');
  return data;
}

function toast(msg, bad) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.toggle('bad', !!bad);
  t.hidden = false;
  clearTimeout(t._t);
  t._t = setTimeout(() => (t.hidden = true), 2400);
}

/* ---------- 统计 ---------- */
async function loadStats() {
  try {
    const s = await api('/api/stats');
    $('stat-total').textContent = s.total;
    $('stat-majors').textContent = s.majors;
    $('stat-dorms').textContent = s.dorms;

    const box = $('stat-major-chips');
    box.replaceChildren();
    s.by_major.forEach((m) => {
      const el = document.createElement('span');
      el.className = 'chip';
      const b = document.createElement('b');
      b.textContent = m.c;
      el.append(document.createTextNode((m.major || '未填') + ' '), b);
      box.append(el);
    });

    const optMajor = $('opt-major');
    if (optMajor.options.length <= 1) {
      s.by_major.forEach((m) => {
        if (!m.major) return;
        const o = document.createElement('option');
        o.value = m.major;
        o.textContent = m.major;
        optMajor.append(o);
      });
    }
  } catch (e) {
    /* 忽略 */
  }
}

/* ---------- 列表 ---------- */
function cell(text, mono) {
  const td = document.createElement('td');
  if (mono) td.className = 'mono';
  td.textContent = text == null || text === '' ? '—' : String(text);
  return td;
}

function renderRows(items) {
  rowsEl.replaceChildren();

  if (!items.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 7;
    td.className = 'empty';
    td.textContent = '没有匹配的学生';
    tr.append(td);
    rowsEl.append(tr);
    return;
  }

  items.forEach((s) => {
    const tr = document.createElement('tr');
    tr.append(cell(s.student_no, true), cell(s.name));

    const tdG = document.createElement('td');
    const g = document.createElement('span');
    g.className = 'gender';
    g.textContent = s.gender || '—';
    tdG.append(g);
    tr.append(tdG);

    tr.append(cell(s.major), cell(s.dorm_room));

    const tdR = document.createElement('td');
    tdR.className = 'col-remark';
    if (s.remark) {
      const span = document.createElement('span');
      span.className = 'remark';
      span.textContent = s.remark;
      span.title = s.remark;
      tdR.append(span);
    } else {
      tdR.textContent = '—';
    }
    tr.append(tdR);

    const tdAct = document.createElement('td');
    tdAct.className = 'col-act';
    const wrap = document.createElement('div');
    wrap.className = 'row-actions';

    const bEdit = document.createElement('button');
    bEdit.className = 'btn ghost sm';
    bEdit.type = 'button';
    bEdit.textContent = '编辑';
    bEdit.addEventListener('click', () => openEdit(s));

    const bDel = document.createElement('button');
    bDel.className = 'btn danger sm';
    bDel.type = 'button';
    bDel.textContent = '删除';
    bDel.addEventListener('click', () => removeStudent(s));

    wrap.append(bEdit, bDel);
    tdAct.append(wrap);
    tr.append(tdAct);
    rowsEl.append(tr);
  });
}

function renderPager(total) {
  lastTotal = total;
  const from = total === 0 ? 0 : (state.page - 1) * state.size + 1;
  const to = Math.min(total, state.page * state.size);
  $('pager-info').textContent = `共 ${total} 条，当前 ${from}–${to}`;
  $('prev').disabled = state.page <= 1;
  $('next').disabled = to >= total;
}

async function loadList() {
  const params = new URLSearchParams({
    q: state.q,
    page: state.page,
    size: state.size,
    sort: state.sort,
    order: state.order,
  });
  if (state.major) params.set('major', state.major);

  try {
    const d = await api('/api/students?' + params.toString());
    renderRows(d.items);
    renderPager(d.total);
  } catch (e) {
    toast(e.message, true);
  }
}

/* ---------- 模态框 ---------- */
const modal = $('modal');
const form = $('form');
let editingId = null;

function openModal(title) {
  $('modal-title').textContent = title;
  $('form-err').hidden = true;
  modal.hidden = false;
}

function closeModal() {
  modal.hidden = true;
  editingId = null;
  form.reset();
}

function openCreate() {
  editingId = null;
  form.reset();
  $('f-gender').value = '';
  openModal('新增学生');
  $('f-no').focus();
}

function openEdit(s) {
  editingId = s.id;
  $('f-no').value = s.student_no || '';
  $('f-name').value = s.name || '';
  $('f-gender').value = s.gender || '';
  $('f-major').value = s.major || '';
  $('f-dorm').value = s.dorm_room || '';
  $('f-phone').value = s.phone || '';
  $('f-email').value = s.email || '';
  $('f-remark').value = s.remark || '';
  openModal('编辑学生');
}

function collect() {
  const v = (id) => $(id).value.trim() || null;
  return {
    student_no: v('f-no'),
    name: v('f-name'),
    gender: $('f-gender').value || null,
    major: v('f-major'),
    dorm_room: v('f-dorm'),
    phone: v('f-phone'),
    email: v('f-email'),
    remark: v('f-remark'),
  };
}

async function removeStudent(s) {
  const ok = confirm(`确定删除「${s.name}（${s.student_no}）」吗？此操作不可撤销。`);
  if (!ok) return;
  try {
    await api('/api/students/' + s.id, {
      method: 'DELETE',
      headers: { 'X-CSRF-Token': csrf },
    });
    toast('已删除');
    await Promise.all([loadList(), loadStats()]);
  } catch (e) {
    toast(e.message, true);
  }
}

/* ---------- 事件 ---------- */
form.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const errBox = $('form-err');
  errBox.hidden = true;

  const body = collect();
  if (!body.student_no || !body.name) {
    errBox.textContent = '学号和姓名是必填项';
    errBox.hidden = false;
    return;
  }

  const btn = form.querySelector('button[type="submit"]');
  btn.disabled = true;
  try {
    if (editingId) {
      await api('/api/students/' + editingId, {
        method: 'PUT',
        headers: { 'X-CSRF-Token': csrf },
        body: JSON.stringify(body),
      });
      toast('已保存');
    } else {
      await api('/api/students', {
        method: 'POST',
        headers: { 'X-CSRF-Token': csrf },
        body: JSON.stringify(body),
      });
      toast('已新增');
      state.page = 1;
    }
    closeModal();
    await Promise.all([loadList(), loadStats()]);
  } catch (e) {
    errBox.textContent = e.message;
    errBox.hidden = false;
  } finally {
    btn.disabled = false;
  }
});

$('btn-new').addEventListener('click', openCreate);
modal.querySelectorAll('[data-close]').forEach((el) => el.addEventListener('click', closeModal));
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !modal.hidden) closeModal();
});

let timer = null;
$('q').addEventListener('input', (e) => {
  clearTimeout(timer);
  timer = setTimeout(() => {
    state.q = e.target.value.trim();
    state.page = 1;
    loadList();
  }, 260);
});

$('opt-major').addEventListener('change', (e) => {
  state.major = e.target.value;
  state.page = 1;
  loadList();
});

$('size').addEventListener('change', (e) => {
  state.size = Number(e.target.value);
  state.page = 1;
  loadList();
});

$('prev').addEventListener('click', () => {
  if (state.page > 1) {
    state.page -= 1;
    loadList();
  }
});

$('next').addEventListener('click', () => {
  if (state.page * state.size < lastTotal) {
    state.page += 1;
    loadList();
  }
});

document.querySelectorAll('th[data-sort]').forEach((th) => {
  th.addEventListener('click', () => {
    const key = th.dataset.sort;
    if (state.sort === key) {
      state.order = state.order === 'asc' ? 'desc' : 'asc';
    } else {
      state.sort = key;
      state.order = 'asc';
    }
    document.querySelectorAll('th[data-sort]').forEach((x) => {
      x.classList.remove('sorted', 'desc');
    });
    th.classList.add('sorted');
    if (state.order === 'desc') th.classList.add('desc');
    loadList();
  });
});

/* ---------- 启动 ---------- */
loadStats();
loadList();
