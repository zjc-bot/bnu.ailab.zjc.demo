/* 头像裁剪：选图 → Cropper.js 框选 → 圆形实时预览 → canvas 导出 → 上传 */
(function () {
  'use strict';

  var csrf = (document.querySelector('meta[name="csrf"]') || {}).content || '';
  var fileInput = document.getElementById('avatarFile');
  var pickBtn = document.getElementById('avatarPick');
  var chooseBtn = document.getElementById('avatarBtn');
  var modal = document.getElementById('cropModal');
  var image = document.getElementById('cropImage');
  var preview = document.getElementById('cropPreview');
  var saveBtn = document.getElementById('cropSave');

  if (!fileInput || !modal || !image) return;
  if (typeof Cropper === 'undefined') {
    console.warn('[avatar] Cropper.js 未加载');
    return;
  }

  var cropper = null;
  var currentURL = null;
  var MAX_INPUT = 8 * 1024 * 1024;      /* 输入放宽到 8MB */
  var MAX_EDGE = 1600;                  /* 自动降采样后的最长边 */
  var MIN_EDGE = 40;                    /* 降采样后仍需保底 */

  function openPicker() { fileInput.click(); }
  if (pickBtn) pickBtn.addEventListener('click', openPicker);
  if (chooseBtn) chooseBtn.addEventListener('click', openPicker);

  /* 格式兜底：有些浏览器把 JPG 报成 image/jpg，或 file.type 为空，
     所以 MIME 之外再看一遍扩展名。 */
  function looksLikeImage(file) {
    var okMime = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']
      .indexOf((file.type || '').toLowerCase()) >= 0;
    var okExt = /\.(jpe?g|png|webp)$/i.test(file.name || '');
    return okMime || okExt;
  }

  fileInput.addEventListener('change', function () {
    var file = fileInput.files && fileInput.files[0];
    if (!file) return;

    if (file.size > MAX_INPUT) {
      window.alert('图片不能超过 8MB');
      fileInput.value = '';
      return;
    }
    if (!looksLikeImage(file)) {
      window.alert('只支持 JPG / PNG / WebP 格式');
      fileInput.value = '';
      return;
    }

    /* 先用 FileReader 读进来，自动等比缩到 MAX_EDGE，再交给裁剪器。
       手机直出的 4000×3000 原图直接喂 Cropper 会很卡，甚至加载失败。 */
    var reader = new FileReader();
    reader.onload = function (e) {
      var probe = new Image();
      probe.onload = function () {
        var w = probe.naturalWidth, h = probe.naturalHeight;

        if (Math.min(w, h) < MIN_EDGE) {
          window.alert('图片太小，短边至少 ' + MIN_EDGE + ' 像素');
          fileInput.value = '';
          return;
        }

        var scale = Math.min(1, MAX_EDGE / Math.max(w, h));
        var tw = Math.round(w * scale), th = Math.round(h * scale);
        var canvas = document.createElement('canvas');
        canvas.width = tw;
        canvas.height = th;
        var ctx = canvas.getContext('2d');
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'high';
        ctx.fillStyle = '#fff';
        ctx.fillRect(0, 0, tw, th);
        ctx.drawImage(probe, 0, 0, tw, th);

        /* 缩小的图转 dataURL 给裁剪器用 */
        var prepared = canvas.toDataURL('image/jpeg', 0.92);
        showCropper(prepared);
      };
      probe.onerror = function () {
        window.alert('图片无法读取，请换一张');
        fileInput.value = '';
      };
      probe.src = e.target.result;
    };
    reader.onerror = function () {
      window.alert('图片读取失败');
      fileInput.value = '';
    };
    reader.readAsDataURL(file);
  });

  function showCropper(src) {
    if (currentURL) URL.revokeObjectURL(currentURL);
    currentURL = null;

    image.src = src;
    modal.hidden = false;

    /* 图片加载完再初始化 Cropper，否则报 "Image load failed" */
    image.onload = function () {
      if (cropper) cropper.destroy();

      cropper = new Cropper(image, {
        aspectRatio: 1,
        viewMode: 1,             /* 裁剪框不能移出图片 */
        dragMode: 'move',
        autoCropArea: 0.85,
        movable: true,
        zoomable: true,
        scalable: false,
        rotatable: false,
        cropBoxMovable: true,
        cropBoxResizable: false,
        background: false,
        responsive: false,
        checkCrossOrigin: false,
        crop: function () { updatePreview(); }
      });
      updatePreview();
    };
  }

  function updatePreview() {
    if (!cropper) return;
    var canvas = cropper.getCroppedCanvas({
      width: 160,
      height: 160,
      imageSmoothingEnabled: true,
      imageSmoothingQuality: 'high'
    });
    if (!canvas) return;
    preview.innerHTML = '';
    var img = document.createElement('img');
    img.src = canvas.toDataURL('image/png');
    preview.appendChild(img);
  }

  function closeModal() {
    modal.hidden = true;
    if (cropper) { cropper.destroy(); cropper = null; }
    if (currentURL) { URL.revokeObjectURL(currentURL); currentURL = null; }
    fileInput.value = '';
  }

  modal.querySelectorAll('[data-close]').forEach(function (el) {
    el.addEventListener('click', closeModal);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !modal.hidden) closeModal();
  });

  var zoomIn = document.getElementById('cropZoomIn');
  var zoomOut = document.getElementById('cropZoomOut');
  var reset = document.getElementById('cropReset');
  if (zoomIn) zoomIn.addEventListener('click', function () { cropper && cropper.zoom(0.12); });
  if (zoomOut) zoomOut.addEventListener('click', function () { cropper && cropper.zoom(-0.12); });
  if (reset) reset.addEventListener('click', function () { cropper && cropper.reset(); });

  if (saveBtn) {
    saveBtn.addEventListener('click', function () {
      if (!cropper) return;
      saveBtn.disabled = true;
      saveBtn.textContent = '处理中…';

      /* 像素级裁剪，不是 CSS 遮罩 */
      cropper.getCroppedCanvas({
        width: 320,
        height: 320,
        imageSmoothingEnabled: true,
        imageSmoothingQuality: 'high',
        fillColor: '#fff'
      }).toBlob(function (blob) {
        if (!blob) {
          saveBtn.disabled = false;
          saveBtn.textContent = '确认使用';
          return;
        }
        var fd = new FormData();
        fd.append('csrf', csrf);
        fd.append('avatar', blob, 'avatar.webp');

        fetch('/api/pet/avatar', { method: 'POST', body: fd })
          .then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (d) {
              if (!r.ok) throw new Error(d.error || '上传失败');
              return d;
            });
          })
          .then(function () { window.location.reload(); })
          .catch(function (e) {
            window.alert(e.message);
            saveBtn.disabled = false;
            saveBtn.textContent = '确认使用';
          });
      }, 'image/webp', 0.92);
    });
  }
})();
