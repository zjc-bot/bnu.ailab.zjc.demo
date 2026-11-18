/* 零依赖 SVG 折线图：平滑曲线 + 数据点 + 十字准星 + 跟随气泡
 *
 * 交互规范参考：
 *   - crosshair 吸附最近数据点，而非跟随鼠标像素
 *   - 悬停同时给出 X 轴日期、Y 轴数值、tooltip 读数
 *   - 命中区（12px）大于标记本身（3px），读者瞄的是日期
 *   - 网格线低对比，数据线承担视觉重量
 */
(function () {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';

  function el(name, attrs) {
    var e = document.createElementNS(NS, name);
    if (attrs) {
      for (var k in attrs) {
        if (Object.prototype.hasOwnProperty.call(attrs, k)) {
          e.setAttribute(k, attrs[k]);
        }
      }
    }
    return e;
  }

  /* 把最大值向上取整到好看的刻度 */
  function niceMax(v) {
    if (!v || v <= 0) return 4;
    var mag = Math.pow(10, Math.floor(Math.log10(v)));
    var n = v / mag;
    var step;
    if (n <= 1) step = 1;
    else if (n <= 2) step = 2;
    else if (n <= 5) step = 5;
    else step = 10;
    return step * mag;
  }

  /* Fritsch–Carlson 单调三次插值
   *
   * Catmull-Rom 会在数据突增处产生过冲（先下凹再上升），
   * 因为它不考虑斜率符号。单调插值通过对切线做限幅，
   * 保证：数据单调递增的区间内，曲线也严格单调，
   * 且不会越过相邻两个数据点的值域。
   */
  function smoothPath(pts) {
    var n = pts.length;
    if (n < 2) return '';
    if (n === 2) {
      return 'M' + pts[0][0] + ',' + pts[0][1] + ' L' + pts[1][0] + ',' + pts[1][1];
    }

    var dx = [], delta = [];
    for (var i = 0; i < n - 1; i++) {
      dx[i] = pts[i + 1][0] - pts[i][0];
      delta[i] = dx[i] === 0 ? 0 : (pts[i + 1][1] - pts[i][1]) / dx[i];
    }

    /* 初始切线：端点取单侧差分，中间取两侧平均 */
    var m = new Array(n);
    m[0] = delta[0];
    m[n - 1] = delta[n - 2];
    for (var j = 1; j < n - 1; j++) {
      if (delta[j - 1] * delta[j] <= 0) {
        m[j] = 0;                       // 极值点，切线置平，避免过冲
      } else {
        m[j] = (delta[j - 1] + delta[j]) / 2;
      }
    }

    /* 单调性限幅：α² + β² > 9 时把切线压回安全范围 */
    for (var k = 0; k < n - 1; k++) {
      if (delta[k] === 0) {
        m[k] = 0;
        m[k + 1] = 0;
        continue;
      }
      var a = m[k] / delta[k];
      var b = m[k + 1] / delta[k];
      var s = a * a + b * b;
      if (s > 9) {
        var tau = 3 / Math.sqrt(s);
        m[k] = tau * a * delta[k];
        m[k + 1] = tau * b * delta[k];
      }
    }

    /* Hermite 转三次 Bezier */
    var d = 'M' + pts[0][0] + ',' + pts[0][1];
    for (var t = 0; t < n - 1; t++) {
      var h = dx[t];
      var c1x = pts[t][0] + h / 3;
      var c1y = pts[t][1] + (h / 3) * m[t];
      var c2x = pts[t + 1][0] - h / 3;
      var c2y = pts[t + 1][1] - (h / 3) * m[t + 1];
      d += ' C' + c1x + ',' + c1y + ' ' + c2x + ',' + c2y +
           ' ' + pts[t + 1][0] + ',' + pts[t + 1][1];
    }
    return d;
  }

  function render(container) {
    var raw = container.getAttribute('data-chart');
    if (!raw) return;

    var cfg;
    try {
      cfg = JSON.parse(raw);
    } catch (e) {
      return;
    }

    var labels = cfg.labels || [];
    var values = cfg.values || [];
    var color = cfg.color || '#2563eb';
    var unit = cfg.unit || '';
    var height = cfg.height || 200;
    var area = cfg.area !== false;

    container.replaceChildren();

    if (!values.length) {
      var empty = document.createElement('p');
      empty.className = 'chart-empty';
      empty.textContent = '暂无数据';
      container.appendChild(empty);
      return;
    }

    var W = container.clientWidth || 600;
    var H = height;
    var pad = { t: 18, r: 18, b: 28, l: 42 };
    var iw = W - pad.l - pad.r;
    var ih = H - pad.t - pad.b;
    if (iw <= 20 || ih <= 20) return;

    var maxV = niceMax(Math.max.apply(null, values));
    var n = values.length;
    var stepX = n > 1 ? iw / (n - 1) : 0;

    var pts = values.map(function (v, i) {
      var x = n === 1 ? pad.l + iw / 2 : pad.l + stepX * i;
      return [x, pad.t + ih - (v / maxV) * ih];
    });

    var svg = el('svg', {
      viewBox: '0 0 ' + W + ' ' + H,
      width: '100%',
      height: H,
      role: 'img',
      'aria-label': (cfg.title || '折线图')
    });

    /* --- 横向网格 + Y 轴刻度 --- */
    var ticks = 4;
    for (var i = 0; i <= ticks; i++) {
      var gy = pad.t + (ih / ticks) * i;
      svg.appendChild(el('line', {
        x1: pad.l, y1: gy, x2: pad.l + iw, y2: gy,
        stroke: '#f1f2f4', 'stroke-width': 1
      }));
      var val = Math.round(maxV - (maxV / ticks) * i);
      var yl = el('text', {
        x: pad.l - 9, y: gy + 4,
        'text-anchor': 'end', 'font-size': 10.5, fill: '#9ca3af'
      });
      yl.textContent = val;
      svg.appendChild(yl);
    }

    /* --- X 轴标签：抽稀，避免拥挤 --- */
    var skip = Math.ceil(n / 7);
    labels.forEach(function (lb, i) {
      if (i % skip !== 0 && i !== n - 1) return;
      var t = el('text', {
        x: pad.l + stepX * i, y: H - 9,
        'text-anchor': 'middle', 'font-size': 10.5, fill: '#9ca3af'
      });
      t.textContent = lb;
      svg.appendChild(t);
    });

    /* --- 面积渐变 --- */
    var defs = el('defs');
    var gid = 'g' + Math.random().toString(36).slice(2, 9);
    var grad = el('linearGradient', { id: gid, x1: '0', y1: '0', x2: '0', y2: '1' });
    grad.appendChild(el('stop', { offset: '0%', 'stop-color': color, 'stop-opacity': '0.20' }));
    grad.appendChild(el('stop', { offset: '100%', 'stop-color': color, 'stop-opacity': '0' }));
    defs.appendChild(grad);
    svg.appendChild(defs);

    var line = n > 1 ? smoothPath(pts) : '';

    if (area && line) {
      var areaD = line +
        ' L' + pts[pts.length - 1][0] + ',' + (pad.t + ih) +
        ' L' + pts[0][0] + ',' + (pad.t + ih) + ' Z';
      svg.appendChild(el('path', { d: areaD, fill: 'url(#' + gid + ')' }));
    }

    /* --- 折线：入场动画（单点时只画点，不画线）--- */
    if (line) {
      var path = el('path', {
        d: line, fill: 'none', stroke: color,
        'stroke-width': 2, 'stroke-linecap': 'round', 'stroke-linejoin': 'round'
      });
      svg.appendChild(path);
      try {
        var len = path.getTotalLength ? path.getTotalLength() : 0;
        if (len > 0) {
          path.style.strokeDasharray = len;
          path.style.strokeDashoffset = len;
          path.style.transition = 'stroke-dashoffset .75s ease-out';
          requestAnimationFrame(function () {
            path.style.strokeDashoffset = 0;
          });
        }
      } catch (e) { /* 忽略 */ }
    }

    /* --- 数据点 --- */
    var dots = el('g');
    pts.forEach(function (p, i) {
      var c = el('circle', {
        cx: p[0], cy: p[1], r: 2.8,
        fill: '#fff', stroke: color, 'stroke-width': 1.8
      });
      var t = el('title');
      t.textContent = labels[i] + '：' + values[i] + unit;
      c.appendChild(t);
      dots.appendChild(c);
    });
    svg.appendChild(dots);

    /* --- 十字准星层（默认隐藏） --- */
    var cross = el('g', { style: 'opacity:0;transition:opacity .12s;' });
    var vline = el('line', {
      y1: pad.t, y2: pad.t + ih,
      stroke: '#9ca3af', 'stroke-width': 1, 'stroke-dasharray': '4 3'
    });
    var hline = el('line', {
      x1: pad.l, x2: pad.l + iw,
      stroke: '#9ca3af', 'stroke-width': 1, 'stroke-dasharray': '4 3'
    });
    var halo = el('circle', { r: 8, fill: color, opacity: '0.18' });
    var focus = el('circle', { r: 4.5, fill: color, stroke: '#fff', 'stroke-width': 2 });
    var xTagBg = el('rect', { height: 17, rx: 4, fill: '#111827', opacity: '0.9' });
    var xTag = el('text', {
      y: H - 9, 'text-anchor': 'middle', 'font-size': 10.5,
      fill: '#fff', 'dominant-baseline': 'middle'
    });
    var yTagBg = el('rect', { width: 34, height: 17, rx: 4, fill: color });
    var yTag = el('text', {
      'text-anchor': 'middle', 'font-size': 10.5, fill: '#fff',
      'dominant-baseline': 'middle'
    });
    cross.append(vline, hline, halo, focus, yTagBg, yTag, xTagBg, xTag);
    svg.appendChild(cross);

    /* --- HTML 气泡 --- */
    var tip = document.createElement('div');
    tip.className = 'chart-tip';
    tip.hidden = true;
    container.appendChild(tip);

    container.appendChild(svg);

    /* --- 交互 --- */
    var hit = el('rect', {
      x: pad.l, y: pad.t, width: iw, height: ih,
      fill: 'transparent', style: 'cursor:crosshair'
    });
    svg.appendChild(hit);

    var current = -1;

    function show(idx) {
      if (idx < 0 || idx >= n) return;
      if (idx === current) return;
      current = idx;

      var p = pts[idx];
      vline.setAttribute('x1', p[0]);
      vline.setAttribute('x2', p[0]);
      hline.setAttribute('y1', p[1]);
      hline.setAttribute('y2', p[1]);
      halo.setAttribute('cx', p[0]);
      halo.setAttribute('cy', p[1]);
      focus.setAttribute('cx', p[0]);
      focus.setAttribute('cy', p[1]);

      /* X 轴标签 */
      xTag.textContent = labels[idx];
      var tw = Math.max(34, labels[idx].length * 7 + 12);
      xTagBg.setAttribute('width', tw);
      xTagBg.setAttribute('x', p[0] - tw / 2);
      xTagBg.setAttribute('y', H - 19);
      xTag.setAttribute('x', p[0]);
      xTag.setAttribute('y', H - 10.5);

      /* Y 轴标签 */
      var vy = Math.round(values[idx]);
      yTag.textContent = vy + unit;
      var yw = String(vy).length * 6.5 + unit.length * 7 + 12;
      yTagBg.setAttribute('width', yw);
      yTagBg.setAttribute('x', pad.l - 9 - yw / 2 - 2);
      yTagBg.setAttribute('y', p[1] - 8.5);
      yTag.setAttribute('x', pad.l - 11 - yw / 2);
      yTag.setAttribute('y', p[1] + 0.5);

      cross.style.opacity = 1;

      /* 气泡 */
      tip.replaceChildren();
      var d = document.createElement('div');
      d.className = 'chart-tip-k';
      d.textContent = labels[idx];
      var v = document.createElement('div');
      v.className = 'chart-tip-v';
      v.textContent = vy + unit;
      tip.append(d, v);

      tip.hidden = false;
      var box = container.getBoundingClientRect();
      var scale = box.width / W;
      var left = p[0] * scale;
      var top = p[1] * scale;
      var tw2 = tip.offsetWidth || 80;
      var th2 = tip.offsetHeight || 40;

      /* 边界翻转，避免被容器裁切 */
      var tx = left + 12;
      if (tx + tw2 > box.width - 4) tx = left - tw2 - 12;
      if (tx < 4) tx = 4;
      var ty = top - th2 - 10;
      if (ty < 2) ty = top + 14;

      tip.style.left = tx + 'px';
      tip.style.top = ty + 'px';
    }

    function hide() {
      current = -1;
      cross.style.opacity = 0;
      tip.hidden = true;
    }

    function onMove(ev) {
      var box = svg.getBoundingClientRect();
      var scale = W / box.width;
      var x = (ev.clientX - box.left) * scale;
      var idx = Math.round((x - pad.l) / (stepX || 1));
      if (idx < 0) idx = 0;
      if (idx > n - 1) idx = n - 1;
      show(idx);
    }

    hit.addEventListener('mousemove', onMove);
    hit.addEventListener('mouseleave', hide);
    hit.addEventListener('touchmove', function (ev) {
      if (ev.touches && ev.touches.length) onMove(ev.touches[0]);
    }, { passive: true });
    hit.addEventListener('touchend', hide);
  }

  function initAll() {
    document.querySelectorAll('[data-chart]').forEach(render);
  }

  function onResize() {
    clearTimeout(onResize._t);
    onResize._t = setTimeout(initAll, 180);
  }

  /* 容器自身尺寸变化（侧栏收放、分栏切换）也要重绘 */
  function observeBoxes() {
    if (!window.ResizeObserver) return;
    var ro = new ResizeObserver(function (entries) {
      var need = false;
      entries.forEach(function (e) {
        var w = e.contentRect.width;
        if (e.target.__lastW && Math.abs(e.target.__lastW - w) > 8) need = true;
        e.target.__lastW = w;
      });
      if (need) {
        clearTimeout(observeBoxes._t);
        observeBoxes._t = setTimeout(initAll, 120);
      }
    });
    document.querySelectorAll('[data-chart]').forEach(function (el) {
      ro.observe(el);
    });
  }

  function boot() {
    initAll();
    observeBoxes();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
  window.addEventListener('resize', onResize);
})();
