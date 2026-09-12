"""從 Streamlit Secrets 載入教師端系統設定，並維持可測試性。

Gemini API Key 不由教師端 Secrets 提供；學生會在 app.py 中自行輸入，
並只暫存在該 Streamlit session 的 session_state。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from .constants import PROMPT_VERSION_DEFAULT, RUBRIC_VERSION_DEFAULT


def _value(source: Mapping[str, Any], key: str, default: Any = None) -> Any:
    try:
        return source[key]
    except Exception:
        return default


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    text = str(value).strip()
    if not text:
        return ()
    return tuple(item.strip() for item in text.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    # 保留舊欄位以避免其他尚未更新的模組因 AttributeError 中斷；
    # 新版 load_settings 永遠不從教師端 Secrets 載入 Gemini Key。
    gemini_api_keys: tuple[str, ...]
    model_name: str
    evaluator_model_name: str
    dialogue_temperature: float
    evaluator_temperature: float
    prompt_version: str
    rubric_version: str
    spreadsheet_id: str
    service_account_json: str
    course_access_code: str
    admin_password: str
    require_sheets: bool
    max_history_chars: int
    max_user_input_chars: int
    email_sender: str
    email_password: str
    smtp_host: str
    smtp_port: int
    school_email_domains: tuple[str, ...]
    otp_test_emails: tuple[str, ...]
    otp_ttl_seconds: int
    otp_resend_seconds: int
    otp_max_attempts: int

    @property
    def sheets_configured(self) -> bool:
        return bool(self.spreadsheet_id and self.service_account_json)

    @property
    def gemini_configured(self) -> bool:
        """舊版相容屬性；新版學生端不使用教師端 Gemini Key。"""
        return False

    @property
    def otp_configured(self) -> bool:
        return bool(
            self.email_sender
            and self.email_password
            and (self.school_email_domains or self.otp_test_emails)
        )

    def service_account_info(self) -> dict[str, Any]:
        if not self.service_account_json:
            return {}
        value = json.loads(self.service_account_json)
        if not isinstance(value, dict):
            raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON 必須是 JSON 物件")
        return value


def load_settings(secrets: Mapping[str, Any]) -> Settings:
    """載入教師端設定。

    即使 Secrets 仍殘留舊版 GEMINI_API_KEY / GEMINI_API_KEYS，也刻意忽略，
    避免學生流量誤用教師的 Gemini 配額。

    Email OTP 同時相容新版 [email].sender/password 與舊版
    [email].sender_email/app_password，方便沿用既有 Streamlit Secrets。
    """
    service_json = str(_value(secrets, "GOOGLE_SERVICE_ACCOUNT_JSON", "") or "").strip()
    if not service_json:
        nested = _value(secrets, "gcp_service_account", None)
        if nested:
            service_json = json.dumps(dict(nested), ensure_ascii=False)

    email_cfg = _value(secrets, "email", {}) or {}
    try:
        email_cfg = dict(email_cfg)
    except Exception:
        email_cfg = {}

    email_sender = str(
        email_cfg.get("sender")
        or email_cfg.get("sender_email")
        or _value(secrets, "SENDER_EMAIL", "")
        or ""
    ).strip()
    email_password = str(
        email_cfg.get("password")
        or email_cfg.get("app_password")
        or _value(secrets, "SENDER_PASSWORD", "")
        or ""
    ).strip()
    smtp_host = str(
        email_cfg.get("smtp_host", _value(secrets, "SMTP_HOST", "smtp.gmail.com"))
        or "smtp.gmail.com"
    ).strip()
    smtp_port = int(
        email_cfg.get("smtp_port", _value(secrets, "SMTP_PORT", 465)) or 465
    )

    domains = _as_tuple(_value(secrets, "SCHOOL_EMAIL_DOMAINS", ()))
    if not domains:
        domains = _as_tuple(email_cfg.get("school_domains", ()))
    domains = tuple(item.lower().lstrip("@") for item in domains)

    test_emails = _as_tuple(_value(secrets, "OTP_TEST_EMAILS", ()))
    if not test_emails:
        test_emails = _as_tuple(email_cfg.get("test_emails", ()))
    test_emails = tuple(item.strip().lower() for item in test_emails if item.strip())

    return Settings(
        gemini_api_keys=(),
        model_name=str(_value(secrets, "MODEL_NAME", "gemini-3.8-flash")),
        evaluator_model_name=str(
            _value(
                secrets, "EVALUATOR_MODEL_NAME", _value(secrets, "MODEL_NAME", "gemini-3.8-flash")
            )
        ),
        dialogue_temperature=float(_value(secrets, "DIALOGUE_TEMPERATURE", 0.35)),
        evaluator_temperature=float(_value(secrets, "EVALUATOR_TEMPERATURE", 0.0)),
        prompt_version=str(_value(secrets, "PROMPT_VERSION", PROMPT_VERSION_DEFAULT)),
        rubric_version=str(_value(secrets, "RUBRIC_VERSION", RUBRIC_VERSION_DEFAULT)),
        spreadsheet_id=str(_value(secrets, "SPREADSHEET_ID", "") or "").strip(),
        service_account_json=service_json,
        course_access_code=str(_value(secrets, "COURSE_ACCESS_CODE", "") or ""),
        admin_password=str(_value(secrets, "ADMIN_PASSWORD", "") or ""),
        require_sheets=_as_bool(_value(secrets, "REQUIRE_SHEETS", True), True),
        max_history_chars=int(_value(secrets, "MAX_HISTORY_CHARS", 12000)),
        max_user_input_chars=int(_value(secrets, "MAX_USER_INPUT_CHARS", 800)),
        email_sender=email_sender,
        email_password=email_password,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        school_email_domains=domains,
        otp_test_emails=test_emails,
        otp_ttl_seconds=int(_value(secrets, "OTP_TTL_SECONDS", 600)),
        otp_resend_seconds=int(_value(secrets, "OTP_RESEND_SECONDS", 60)),
        otp_max_attempts=int(_value(secrets, "OTP_MAX_ATTEMPTS", 5)),
    )
