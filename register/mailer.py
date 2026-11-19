"""邮件发送：北师大企业邮（网易托管），SMTP over SSL 465。"""

import html
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.mail.bnu.edu.cn")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
FROM_NAME = os.environ.get("SMTP_FROM_NAME", "BNU AI Lab")

TEXT_TPL = """BNU AI Lab 注册验证码

    验证码：{code}

    有效期 {ttl} 分钟。如果不是你本人操作，请忽略本邮件。

—— 本邮件由系统自动发出，请勿直接回复
"""

HTML_TPL = """<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f5f6f8;
  font-family:-apple-system,'Microsoft YaHei',sans-serif;">
  <div style="max-width:480px;margin:32px auto;background:#fff;border-radius:12px;
    border:1px solid #e5e7eb;overflow:hidden;">
    <div style="background:#2563eb;padding:18px 24px;">
      <span style="color:#fff;font-size:15px;font-weight:600;">BNU AI Lab</span>
    </div>
    <div style="padding:24px;">
      <p style="margin:0 0 16px;color:#111827;font-size:14px;">你的注册验证码：</p>
      <div style="background:#f3f4f6;border-radius:8px;padding:16px;text-align:center;
        font-size:28px;letter-spacing:6px;font-weight:600;color:#2563eb;
        font-family:Consolas,monospace;">{code}</div>
      <p style="margin:16px 0 0;color:#6b7280;font-size:13px;">
        有效期 {ttl} 分钟，仅可使用一次。</p>
      <p style="margin:8px 0 0;color:#9ca3af;font-size:12px;">
        如果不是你本人操作，请忽略本邮件，你的邮箱不会被注册。</p>
    </div>
    <div style="padding:14px 24px;border-top:1px solid #f1f2f4;color:#9ca3af;
      font-size:11px;">本邮件由系统自动发出，请勿直接回复</div>
  </div>
</body></html>
"""


class MailError(Exception):
    pass


def send_code(to_email, code, ttl_minutes=5):
    if not SMTP_USER or not SMTP_PASS:
        raise MailError("SMTP 未配置（SMTP_USER / SMTP_PASS 为空）")

    msg = EmailMessage()
    msg["Subject"] = f"【BNU AI Lab】注册验证码 {code}"
    msg["From"] = formataddr((FROM_NAME, SMTP_USER))
    msg["To"] = to_email
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=SMTP_USER.split("@")[-1])

    msg.set_content(TEXT_TPL.format(code=code, ttl=ttl_minutes))
    msg.add_alternative(
        HTML_TPL.format(code=code, ttl=ttl_minutes), subtype="html"
    )

    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=25) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise MailError(f"SMTP 认证失败：{e.smtp_code}") from e
    except Exception as e:
        raise MailError(f"发信失败：{type(e).__name__}: {e}") from e


# ---------- 通用发送 ----------

def _send(to_email, subject, text, html):
    if not SMTP_USER or not SMTP_PASS:
        raise MailError("SMTP 未配置")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((FROM_NAME, SMTP_USER))
    msg["To"] = to_email
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=SMTP_USER.split("@")[-1])
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=25) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise MailError(f"SMTP 认证失败：{e.smtp_code}") from e
    except Exception as e:
        raise MailError(f"发信失败：{type(e).__name__}: {e}") from e


_BASE_STYLE = (
    "max-width:480px;margin:32px auto;background:#fff;border-radius:12px;"
    "border:1px solid #e5e7eb;overflow:hidden;"
    "font-family:-apple-system,'Microsoft YaHei',sans-serif;"
)


def _wrap(heading, body_html):
    return (
        '<!DOCTYPE html><html><body style="margin:0;padding:0;background:#f5f6f8;">'
        f'<div style="{_BASE_STYLE}">'
        '<div style="background:#1d4ed8;padding:18px 24px;">'
        '<span style="color:#fff;font-size:15px;font-weight:600;">BNU AI Lab</span></div>'
        f'<div style="padding:24px;">{heading}{body_html}</div>'
        '<div style="padding:14px 24px;border-top:1px solid #f1f2f4;color:#9ca3af;'
        'font-size:11px;">本邮件由系统自动发出，请勿直接回复</div>'
        '</div></body></html>'
    )


# ---------- 重置密码 ----------

def send_reset_link(to_email, nickname, reset_url, ttl_minutes=30):
    subject = "【BNU AI Lab】重置登录密码"
    text = f"""{nickname}，你好：

我们收到重置你 BNU AI Lab 账号密码的请求。

    重置链接（{ttl_minutes} 分钟内有效，仅可使用一次）：
    {reset_url}

如果不是你本人操作，请忽略本邮件，你的密码不会被修改。
如果你连续收到此类邮件，建议尽快登录并修改密码。
"""
    body = (
        f'<p style="margin:0 0 14px;color:#111827;font-size:14px;">'
        f'{html.escape(str(nickname))}，你好：</p>'
        '<p style="margin:0 0 16px;color:#374151;font-size:13.5px;">'
        '我们收到重置你 BNU AI Lab 账号密码的请求。点击下方按钮设置新密码：</p>'
        f'<div style="text-align:center;margin:20px 0;">'
        f'<a href="{reset_url}" style="display:inline-block;background:#1d4ed8;color:#fff;'
        f'text-decoration:none;padding:11px 26px;border-radius:8px;font-size:14px;'
        f'font-weight:500;">设置新密码</a></div>'
        f'<p style="margin:0;color:#6b7280;font-size:12.5px;">'
        f'链接 {ttl_minutes} 分钟内有效，仅可使用一次。</p>'
        '<p style="margin:10px 0 0;color:#9ca3af;font-size:12px;">'
        '如果不是你本人操作，请忽略本邮件，你的密码不会被修改。</p>'
    )
    _send(to_email, subject, text, _wrap("", body))


# ---------- 异地登录提醒 ----------

def send_login_alert(to_email, nickname, ip, ua, when):
    subject = "【BNU AI Lab】检测到新地点登录"
    text = f"""{nickname}，你好：

你的账号刚刚从一个新的网络位置登录：

    时间：{when}
    IP：{ip}
    设备：{ua}

如果这是你本人操作，可以忽略本邮件。
如果不是你本人，请立即登录并修改密码，或联系实验室管理员。
"""
    body = (
        f'<p style="margin:0 0 14px;color:#111827;font-size:14px;">'
        f'{html.escape(str(nickname))}，你好：</p>'
        '<p style="margin:0 0 16px;color:#374151;font-size:13.5px;">'
        '你的账号刚刚从一个<strong>新的网络位置</strong>登录：</p>'
        '<div style="background:#fef3c7;border:1px solid #fde68a;border-radius:8px;'
        'padding:14px 16px;margin-bottom:16px;font-size:13px;color:#92400e;">'
        f'<div style="margin-bottom:5px;">时间：{html.escape(str(when))}</div>'
        f'<div style="margin-bottom:5px;">IP：<span style="font-family:monospace;">{html.escape(str(ip))}</span></div>'
        f'<div>设备：{html.escape(str(ua))}</div></div>'
        '<p style="margin:0;color:#374151;font-size:13px;">'
        '如果这是你本人操作，可以忽略本邮件。</p>'
        '<p style="margin:6px 0 0;color:#b91c1c;font-size:13px;">'
        '如果不是你本人，请立即登录并修改密码，或联系实验室管理员。</p>'
    )
    _send(to_email, subject, text, _wrap("", body))
