"""学习分享室前端可靠性回归（不依赖数据库或第三方测试库）。"""

from pathlib import Path
import re
import subprocess
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[1]
JS_PATH = ROOT / "static" / "archive.js"
CSS_PATH = ROOT / "static" / "archive.css"
TEMPLATE_PATH = ROOT / "templates" / "archive.html"
PROFILE_PATH = ROOT / "templates" / "profile.html"


_NODE_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const source = fs.readFileSync(process.argv[1], 'utf8');

class ClassList {
  constructor(el) { this.el = el; this.names = new Set(); }
  add(...names) { names.forEach(name => this.names.add(name)); }
  remove(...names) { names.forEach(name => this.names.delete(name)); }
  contains(name) { return this.names.has(name); }
  toggle(name, force) {
    const on = force === undefined ? !this.names.has(name) : force;
    if (on) this.names.add(name); else this.names.delete(name);
    return on;
  }
}

class Element {
  constructor(id = '', tag = 'div') {
    this.id = id;
    this.tagName = tag.toUpperCase();
    this.dataset = {};
    this.style = { setProperty(key, value) { this[key] = value; } };
    this.children = [];
    this.listeners = {};
    this.attributes = {};
    this.hidden = false;
    this.disabled = false;
    this.inert = false;
    this.isConnected = true;
    this.textContent = '';
    this.classList = new ClassList(this);
    this.pointerCaptures = 0;
    this._innerHTML = '';
  }
  set innerHTML(value) {
    this._innerHTML = String(value);
    this.children = [];
    if (this.id === 'hit') {
      for (const match of this._innerHTML.matchAll(/<article class="piece" data-i="(\d+)"/g)) {
        const el = new Element('', 'article');
        el.classList.add('piece');
        el.dataset.i = match[1];
        el.attributes.role = 'button';
        el.attributes['aria-haspopup'] = 'dialog';
        el.attributes['aria-controls'] = 'detailOverlay';
        el.attributes['aria-expanded'] = 'false';
        this.children.push(el);
      }
    } else if (this.id === 'nav') {
      for (const match of this._innerHTML.matchAll(/<button[^>]*data-cat="([^"]*)"/g)) {
        const el = new Element('', 'button');
        el.dataset.cat = match[1];
        el.children.push(new Element('', 'span'));
        this.children.push(el);
      }
    } else if (this.id === 'detailSheet') {
      for (const id of ['dClose', 'dPrev', 'dNext']) {
        if (this._innerHTML.includes(`id="${id}"`)) {
          this.children.push(new Element(id, 'button'));
        }
      }
    }
  }
  get innerHTML() { return this._innerHTML; }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === 'inert') this.inert = true;
  }
  removeAttribute(name) {
    delete this.attributes[name];
    if (name === 'inert') this.inert = false;
  }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  dispatch(type, values = {}) {
    const event = {
      target: values.target || this,
      currentTarget: this,
      defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true; },
      ...values,
    };
    for (const fn of this.listeners[type] || []) fn(event);
    return event;
  }
  focus() { document.activeElement = this; }
  contains(el) { return el === this || this.children.includes(el); }
  querySelectorAll(selector) {
    if (selector === '.piece') return this.children.filter(el => el.classList.contains('piece'));
    if (selector === 'button') return this.children.filter(el => el.tagName === 'BUTTON');
    if (selector === '.slot') return this.children.filter(el => el.tagName === 'SPAN');
    if (selector.includes('button, a[href]')) {
      return this.children.filter(el => el.tagName === 'BUTTON' || el.tagName === 'A');
    }
    return [];
  }
  setPointerCapture() { this.pointerCaptures += 1; }
  hasPointerCapture() { return this.pointerCaptures > 0; }
  closest() { return null; }
}

const ids = [
  'viewport', 'hit', 'stage', 'nav', 'count', 'archiveStatus',
  'archiveStatusText', 'archiveRetry', 'next', 'shuffle', 'reset',
  'detailOverlay', 'detailSheet',
];
const elements = Object.fromEntries(ids.map(id => [id, new Element(id)]));
elements.detailOverlay.inert = true;
const document = {
  activeElement: null,
  currentScript: { getAttribute: name => name === 'data-archive-api' ? '/api/archive.json' : null },
  getElementById: id => elements[id] || elements.detailSheet.children.find(el => el.id === id) || null,
  querySelectorAll: () => [],
};
const window = {
  innerWidth: 1280,
  innerHeight: 800,
  listeners: {},
  matchMedia: () => ({ matches: false }),
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); },
  dispatch(type, values = {}) {
    const event = {
      target: this,
      defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true; },
      ...values,
    };
    for (const fn of this.listeners[type] || []) fn(event);
    return event;
  },
};
const payload = {
  items: [
    { kind: 'poster', cat: 'ai', catLabel: '人工智能' },
    { kind: 'sheet', cat: 'edu', catLabel: '教育技术' },
    { kind: 'ticket', cat: 'math', catLabel: '数学' },
  ].map(({ kind, cat, catLabel }, index) => ({
    id: index + 1, code: `I-0${index + 1}`, cat, catLabel, kind,
    x: 210 + index * 260, y: 80, w: 240, h: 200, r: index - 1, z: index + 1,
    title: `成果 ${index + 1}`, year: '2026', status: '已发布', st: '',
    summary: `摘要 ${index + 1}`, content: `正文 ${index + 1}`, tags: ['测试'],
    owner: '社区成员', metric: String(index), metricLabel: '赞', rows: [], red: '', refs: '',
  })),
  stats: [{ value: 3, label: '公开想法' }],
  tags: [{ id: 'all', label: '全部' }],
};
window.__ARCHIVE__ = payload;
const context = {
  window, document, console,
  performance: { now: () => 0 },
  setTimeout, clearTimeout,
};
vm.runInNewContext(source, context, { filename: 'archive.js' });
"""


def _run_node(body):
    script = _NODE_HARNESS + "\n(async () => {\n" + textwrap.dedent(body) + "\n})().catch(error => { console.error(error); process.exit(1); });\n"
    result = subprocess.run(
        ["node", "-e", script, str(JS_PATH)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_archive_template_has_dialog_and_recoverable_error_contract():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert 'id="viewport"' in template
    assert 'id="detailOverlay" role="dialog" aria-modal="true"' in template
    overlay_tag = re.search(r'<div[^>]*id="detailOverlay"[^>]*>', template).group(0)
    assert 'aria-hidden="true"' in overlay_tag
    assert re.search(r"\sinert(?:\s|>)", overlay_tag)
    assert 'id="archiveStatus" role="alert"' in template
    assert 'id="archiveRetry" type="button">重试</button>' in template
    assert 'data-archive-api="{{ url_for(\'archive_api.archive_json\') }}"' in template


def test_archive_cards_and_details_show_author_category():
    _run_node(r"""
        const hit = document.getElementById('hit');
        const detail = document.getElementById('detailSheet');
        assert.match(hit.innerHTML, /class="piece-category">人工智能<\/span>/);
        assert.match(hit.innerHTML, /class="piece-category">教育技术<\/span>/);
        assert.match(hit.innerHTML, /class="piece-category">数学<\/span>/);
        assert.doesNotMatch(hit.innerHTML, /海报|实验记录|会议门票/);

        const pieces = hit.querySelectorAll('.piece');
        pieces[0].dispatch('keydown', { key: 'Enter' });
        assert.match(detail.innerHTML, /class="d-kind">人工智能<\/span>/);
        assert.doesNotMatch(detail.innerHTML, /class="d-kind">海报<\/span>/);
        document.getElementById('dNext').dispatch('click');
        assert.match(detail.innerHTML, /class="d-kind">教育技术<\/span>/);

        context.applyData({
          items: [{ ...payload.items[0], catLabel: '<img src=x onerror=alert(1)>' }],
          stats: [], tags: [{ id: 'all', label: '全部' }],
        });
        assert.match(hit.innerHTML, /&lt;img src=x onerror=alert\(1\)&gt;/);
        assert.doesNotMatch(hit.innerHTML, /<img src=x/);
        context.applyData({
          items: [{ ...payload.items[0], catLabel: '' }],
          stats: [], tags: [{ id: 'all', label: '全部' }],
        });
        assert.match(hit.innerHTML, /class="piece-category">其他<\/span>/);
    """)


def test_archive_keyboard_modal_navigation_focus_and_inert():
    _run_node("""
        const hit = document.getElementById('hit');
        const overlay = document.getElementById('detailOverlay');
        const viewport = document.getElementById('viewport');
        const pieces = hit.querySelectorAll('.piece');
        assert.equal(window.listeners.keydown.length, 1, '方向键只能有一个全局处理器');
        assert.equal(pieces[0].attributes.role, 'button');
        assert.equal(pieces[0].attributes['aria-haspopup'], 'dialog');

        pieces[0].focus();
        pieces[0].dispatch('keydown', { key: 'Enter' });
        assert.equal(document.getElementById('dClose') === document.activeElement, true);
        assert.equal(viewport.inert, true);
        assert.equal(viewport.attributes['aria-hidden'], 'true');
        assert.equal(overlay.inert, false);
        assert.match(document.getElementById('detailSheet').innerHTML, /I-01/);

        window.dispatch('keydown', { key: 'ArrowRight' });
        assert.match(document.getElementById('detailSheet').innerHTML, /I-02/, '一次按键只能推进一项');
        window.dispatch('keydown', { key: 'ArrowRight', repeat: true });
        assert.match(document.getElementById('detailSheet').innerHTML, /I-02/, '长按重复事件不重复推进');
        window.dispatch('keydown', { key: 'ArrowLeft' });
        assert.match(document.getElementById('detailSheet').innerHTML, /I-01/);
        window.dispatch('keydown', { key: 'ArrowLeft' });
        assert.match(document.getElementById('detailSheet').innerHTML, /I-03/, '上一项应循环到末项');
        window.dispatch('keydown', { key: 'ArrowRight' });
        assert.match(document.getElementById('detailSheet').innerHTML, /I-01/, '下一项应循环到首项');

        document.getElementById('dNext').dispatch('click');
        assert.match(document.getElementById('detailSheet').innerHTML, /I-02/);
        window.dispatch('keydown', { key: 'Tab' });
        assert.equal(document.activeElement.id, 'dClose', 'Tab 不能离开弹窗');
        window.dispatch('keydown', { key: 'Tab', shiftKey: true });
        assert.equal(document.activeElement.id, 'dNext', 'Shift+Tab 应循环到最后一个控件');
        window.dispatch('keydown', { key: 'Escape' });
        assert.equal(overlay.classList.contains('open'), false);
        assert.equal(viewport.inert, false);
        assert.equal(overlay.inert, true);
        assert.equal(document.activeElement, pieces[0], '关闭后恢复触发纸片焦点');

        pieces[0].dispatch('keydown', { key: ' ' });
        assert.equal(overlay.classList.contains('open'), true, 'Space 应打开纸片');
        window.dispatch('keydown', { key: 'Escape' });
        window.dispatch('keydown', { key: 'ArrowRight' });
        assert.equal(document.getElementById('count').textContent, '02 / 03');

        window.innerWidth = 390;
        window.matchMedia = () => ({ matches: true });
        context.fit();
        assert.equal(document.getElementById('stage').style.transform, '', '窄屏不能整体缩放');
        pieces[0].dispatch('pointerdown', { button: 0, pointerId: 1 });
        assert.equal(pieces[0].pointerCaptures, 0, '窄屏触摸不应被拖拽捕获');
        pieces[0].dispatch('click');
        assert.equal(overlay.classList.contains('open'), true, '窄屏轻触应打开详情');
        window.dispatch('keydown', { key: 'Escape' });
        assert.equal(document.activeElement, pieces[0]);
    """)


def test_archive_http_failure_is_visible_and_retry_recovers():
    _run_node("""
        window.__ARCHIVE__ = null;
        let jsonCalls = 0;
        let fetchCalls = 0;
        let unavailable = true;
        context.fetch = async () => {
          fetchCalls += 1;
          if (unavailable) {
            return {
              ok: false,
              status: 503,
              json: async () => { jsonCalls += 1; return {}; },
            };
          }
          return { ok: true, status: 200, json: async () => payload };
        };
        await context.loadArchive();
        assert.equal(fetchCalls, 1);
        assert.equal(jsonCalls, 0, 'HTTP 失败时不应尝试解析 JSON');
        assert.equal(document.getElementById('archiveStatus').hidden, false);
        assert.match(document.getElementById('archiveStatusText').textContent, /HTTP 503/);
        assert.equal(document.getElementById('archiveRetry').disabled, false);
        assert.match(document.getElementById('hit').innerHTML, /暂时无法加载/);

        unavailable = false;
        document.currentScript = null;
        document.getElementById('archiveRetry').dispatch('click');
        await new Promise(resolve => setTimeout(resolve, 0));
        assert.equal(fetchCalls, 2);
        assert.equal(document.getElementById('archiveStatus').hidden, true);
        assert.equal(document.getElementById('hit').querySelectorAll('.piece').length, 3);
    """)


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("network", "网络连接失败"),
        ("json", "JSON"),
        ("contract", "格式不正确"),
    ],
)
def test_archive_bad_responses_have_recoverable_errors(mode, message):
    _run_node(f"""
        window.__ARCHIVE__ = null;
        context.fetch = async () => {{
          if ({mode!r} === 'network') throw new TypeError('Failed to fetch');
          return {{
            ok: true,
            status: 200,
            json: async () => {{
              if ({mode!r} === 'json') throw new SyntaxError('bad json');
              return {{ items: 'not-an-array' }};
            }},
          }};
        }};
        await context.loadArchive();
        assert.equal(document.getElementById('archiveStatus').hidden, false);
        assert.ok(document.getElementById('archiveStatusText').textContent.includes({message!r}));
        assert.equal(document.getElementById('archiveRetry').disabled, false);
        assert.equal(document.getElementById('hit').querySelectorAll('.piece').length, 0);
    """)


def test_archive_narrow_layout_is_responsive_with_touch_targets():
    css = CSS_PATH.read_text(encoding="utf-8")
    mobile = css.split("@media (max-width: 900px)", 1)[1].split("@media (max-width: 600px)", 1)[0]
    assert "body { overflow: auto; }" in mobile
    assert "width: 100%; height: auto;" in mobile
    assert "transform: none !important;" in mobile
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in mobile
    assert "touch-action: pan-y" in mobile
    assert "min-height: 44px" in mobile
    assert ".detail-sheet .close { width: 44px; height: 44px; }" in mobile
    assert ".detail-sheet .d-nav button { min-height: 44px; }" in mobile


def test_profile_api_key_confirmation_is_native_and_self_contained():
    profile = PROFILE_PATH.read_text(encoding="utf-8")
    assert 'data-confirm="删除自带的 API Key？' in profile
    assert "window.confirm(form.dataset.confirm" in profile
    assert "if (!window.confirm" in profile
    assert "event.preventDefault()" in profile
    assert not re.search(r"<script[^>]+src=[^>]*app\.js", profile)

    inline_scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", profile, re.S)
    script = next(value for value in inline_scripts if "data-confirm" in value)
    node_script = r"""
const vm = require('vm');
const assert = require('assert/strict');
let submit;
let answer = false;
const messages = [];
const form = {
  dataset: { confirm: '删除自带的 API Key？' },
  addEventListener(type, fn) { if (type === 'submit') submit = fn; },
};
vm.runInNewContext(process.argv[1], {
  document: { querySelectorAll: () => [form] },
  window: { confirm: message => { messages.push(message); return answer; } },
});
let event = { defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
submit(event);
assert.equal(event.defaultPrevented, true);
assert.deepEqual(messages, ['删除自带的 API Key？']);
answer = true;
event = { defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
submit(event);
assert.equal(event.defaultPrevented, false);
"""
    result = subprocess.run(
        ["node", "-e", node_script, script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
