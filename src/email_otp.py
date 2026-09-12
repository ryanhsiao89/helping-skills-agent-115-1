"""學校 Email OTP 身分驗證工具。

OTP 僅存在目前 Streamlit session；不寫入 Google Sheets、逐字稿或 log。
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import smtplib
from email.mime.text import MIMEText

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def email_allowed(email: str, allowed_domains: tuple[str, ...]) -> bool:
    normalized = normalize_email(email)
    if not EMAIL_PATTERN.fullmatch(normalized):
        return False
    if not allowed_domains:
        return False
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


def send_otp_email(
    *,
    receiver_email: str,
    otp_code: str,
    sender_email: str,
    sender_password: str,
    smtp_host: str = "smtp.gmail.com",
    smtp_port: int = 465,
) -> None:
    """以 Gmail/SMTP SSL 寄送 OTP；失敗時讓呼叫端顯示去敏感的錯誤。"""
    sender = normalize_email(sender_email)
    receiver = normalize_email(receiver_email)
    password = str(sender_password or "").replace(" ", "").strip()
    if not sender or not password:
        raise RuntimeError("寄件信箱尚未設定。請在 Streamlit Secrets 設定 [email] sender 與 password。")

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
    except Exception as exc:
        raise RuntimeError("驗證信寄送失敗，請確認寄件 Gmail、App Password 與網路設定。") from exc
