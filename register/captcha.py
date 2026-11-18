"""图形验证码：Pillow 生成，服务端校验，一次一用。

设计取舍：
  不使用 reCAPTCHA / hCaptcha —— 国内访问不稳定，且引入第三方脚本
  与现有 CSP（script-src 'self'）冲突。自研验证码无外部依赖。
"""

import io
import os
import random

from PIL import Image, ImageDraw, ImageFont, ImageFilter

# 去掉易混淆的 I O 0 1
CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
LENGTH = 4
WIDTH, HEIGHT = 128, 44

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
]


def _font(size):
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def generate():
    """返回 (PNG 字节流, 明文验证码)。"""
    text = "".join(random.choices(CHARS, k=LENGTH))

    img = Image.new("RGB", (WIDTH, HEIGHT), (247, 248, 250))
    draw = ImageDraw.Draw(img)

    # 背景噪点
    for _ in range(180):
        draw.point(
            (random.randint(0, WIDTH), random.randint(0, HEIGHT)),
            fill=(random.randint(170, 215),) * 3,
        )

    # 干扰线
    for _ in range(4):
        draw.line(
            [
                (random.randint(0, WIDTH), random.randint(0, HEIGHT)),
                (random.randint(0, WIDTH), random.randint(0, HEIGHT)),
            ],
            fill=(random.randint(150, 200),) * 3,
            width=1,
        )

    # 字符：逐个旋转贴入，避免整体规则排布
    font = _font(30)
    step = WIDTH // (LENGTH + 1)
    for i, ch in enumerate(text):
        layer = Image.new("RGBA", (40, 44), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        d.text((6, 4), ch, font=font,
               fill=(random.randint(20, 70), random.randint(20, 70), random.randint(90, 150)))
        layer = layer.rotate(random.uniform(-18, 18), resample=Image.BICUBIC)
        img.paste(layer, (step * (i + 1) - 16, random.randint(1, 6)), layer)

    img = img.filter(ImageFilter.SMOOTH)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue(), text
