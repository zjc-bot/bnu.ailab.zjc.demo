'use strict';

/* 图形验证码：点击刷新 */
const cap = document.getElementById('cap');
if (cap) {
  cap.addEventListener('click', function () {
    cap.src = '/captcha.png?t=' + Date.now();
  });
}

/* 需要二次确认的表单：<form data-confirm="..."> */
document.querySelectorAll('form[data-confirm]').forEach(function (f) {
  f.addEventListener('submit', function (e) {
    if (!confirm(f.dataset.confirm)) e.preventDefault();
  });
});

/* 重新发送邮箱验证码 */
const resend = document.getElementById('resend');
if (resend) {
  let left = 0;
  let timer = null;
  const tip = document.getElementById('resend-tip');

  function render() {
    if (left > 0) {
      resend.disabled = true;
      resend.textContent = '重新发送（' + left + 's）';
      left -= 1;
    } else {
      resend.disabled = false;
      resend.textContent = '重新发送验证码';
      if (timer) { clearInterval(timer); timer = null; }
    }
  }

  resend.addEventListener('click', function () {
    resend.disabled = true;
    resend.textContent = '发送中…';

    fetch('/api/resend', {
      method: 'POST',
      headers: { 'X-CSRF-Token': resend.dataset.csrf }
    })
      .then(function (r) {
        return r.json().catch(function () { return {}; })
          .then(function (d) {
            if (!r.ok) throw new Error(d.error || '发送失败');
            return d;
          });
      })
      .then(function () {
        tip.hidden = false;
        tip.textContent = '已重新发送，请查收邮箱。';
        left = 60;
        timer = setInterval(render, 1000);
        render();
      })
      .catch(function (e) {
        tip.hidden = false;
        tip.textContent = e.message;
        resend.disabled = false;
        resend.textContent = '重新发送验证码';
      });
  });
}
