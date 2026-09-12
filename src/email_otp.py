"""學校 Email OTP 身分驗證工具。

OTP 僅存在目前 Streamlit session；不寫入 Google Sheets、逐字稿或 log。
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import smtplib
import socket
from email.mime.text import MIMEText

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def email_allowed(
    email: str,
    allowed_domains: tuple[str, ...],
    allowed_emails: tuple[str, ...] = (),
) -> bool:
    """允許指定學校網域，或教師明確列出的測試 Email；不開放整個私人網域。"""
    normalized = normalize_email(email)
    if not EMAIL_PATTERN.fullmatch(normalized):
        return False

    normalized_emails = {
        normalize_email(item)
        for item in allowed_emails
        if normalize_email(item)
    }
    if normalized in normalized_emails:
        return True

    domain = normalized.rsplit("@", 1)[1]
    normalized_domains = tuple(
        str(item).strip().lower().lstrip("@")
        for item in allowed_domains
        if str(item).strip()
    )
    return any(domain == allowed or domain.endswith("." + allowed) for allowed in normalized_domains)


def mask_email(email: str) -> str:
    normalized = normalize_email(email)
    if "@" not in normalized:
        return "***"
    local, domain = normalized.split("@", 1)
    if len(local) <= 2:
        masked_local = local[:1] + "***"
    else:
        masked_local = local[:2] + "***"
    return f"{masked_local}@{domain}"


def participant_id_for_email(email: str) -> str:
    """由已驗證學校 Email 產生穩定的去識別代碼。"""
    digest = hashlib.sha256(normalize_email(email).encode("utf-8")).hexdigest().upper()
    return f"S{digest[:12]}"


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def new_otp_nonce() -> str:
    return secrets.token_hex(16)


def otp_digest(email: str, otp_code: str, nonce: str) -> str:
    payload = f"{normalize_email(email)}|{otp_code.strip()}|{nonce}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def otp_matches(email: str, otp_code: str, nonce: str, expected_digest: str) -> bool:
    if not otp_code or not nonce or not expected_digest:
        return False
    return hmac.compare_digest(
        otp_digest(email, otp_code, nonce),
        str(expected_digest).strip(),
    )


def _smtp_password(value: str) -> str:
    """移除 App Password 複製時可能夾帶的各類空白。"""
    return "".join(str(value or "").split())


def _is_ascii(value: str) -> bool:
    try:
        value.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def send_otp_email(
    *,
    receiver_email: str,
    otp_code: str,
    sender_email: str,
    sender_password: str,
    smtp_host: str = "smtp.gmail.com",
    smtp_port: int = 465,
) -> None:
    """以 Gmail/SMTP SSL 寄送 OTP；錯誤訊息分類但不暴露密碼。"""
    sender = normalize_email(sender_email)
    receiver = normalize_email(receiver_email)
    password = _smtp_password(sender_password)
    if not sender or not password:
        raise RuntimeError(
            "寄件信箱尚未設定。請確認 Streamlit Secrets 的 [email] 區塊；"
            "新版 sender/password 與舊版 sender_email/app_password 都支援。"
        )
    if not _is_ascii(sender):
        raise RuntimeError(
            "寄件帳號含有非英數字元。請確認 Streamlit Secrets 不是仍填著中文示範文字，"
            "而是真實可登入的寄件 Gmail/Google Workspace Email。"
        )
    if not _is_ascii(password):
        raise RuntimeError(
            "Google App Password 含有非 ASCII 字元。請重新複製 Google 產生的 App Password；"
            "不要填中文說明文字、一般 Gmail 密碼或其他註解。"
        )

    msg = MIMEText(
        "同學您好：\n\n"
        f"您的助人技巧訓練 Agent 登入驗證碼為：【 {otp_code} 】\n\n"
        "驗證碼 10 分鐘內有效，且只能使用一次。\n"
        "請勿將驗證碼提供給其他人。\n\n"
        "祝學習順利！",
        _charset="utf-8",
    )
    msg["Subject"] = "【助人技巧訓練 Agent】登入驗證碼"
    msg["From"] = sender
    msg["To"] = receiver

    try:
        with smtplib.SMTP_SSL(smtp_host, int(smtp_port), timeout=20) as server:
            server.login(sender, password)
            server.send_message(msg)
    except UnicodeEncodeError as exc:
        raise RuntimeError(
            "寄件帳號或 App Password 含有 SMTP 無法使用的字元；"
            "請確認 Secrets 中填的是實際 Gmail 與 Google App Password。"
        ) from exc
    except smtplib.SMTPAuthenticationError as exc:
        raise RuntimeError(
            "Gmail 驗證失敗：請確認寄件帳號與 Google App Password 是否正確，"
            "且該帳號允許使用 App Password。"
        ) from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise RuntimeError("收件信箱被郵件伺服器拒絕，請確認學校 Email 是否可正常收信。") from exc
    except (smtplib.SMTPConnectError, socket.timeout, TimeoutError, OSError) as exc:
        raise RuntimeError(
            f"無法連線寄信伺服器 {smtp_host}:{smtp_port}；請稍後重試或檢查 SMTP 設定。"
        ) from exc
    except smtplib.SMTPException as exc:
        raise RuntimeError("Gmail SMTP 寄信失敗；請檢查寄件帳號、App Password 與 SMTP 設定。") from exc
