"""從 Streamlit Secrets 載入設定，並維持可測試性。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from .constants import PROMPT_VERSION_DEFAULT, RUBRIC_VERSION_DEFAULT


def _value(source: Mapping[str, Any], key: str, default: Any = None) -> Any:
    try:
        return source[key]
    except Exception:
        # Streamlit 在完全沒有 secrets.toml 時拋出的不是 KeyError；
        # 讓未設定的本機預覽仍能啟動並顯示設定提示。
        return default


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
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

    @property
    def sheets_configured(self) -> bool:
        return bool(self.spreadsheet_id and self.service_account_json)

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_keys)

    def service_account_info(self) -> dict[str, Any]:
        if not self.service_account_json:
            return {}
        value = json.loads(self.service_account_json)
        if not isinstance(value, dict):
            raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON 必須是 JSON 物件")
        return value


def load_settings(secrets: Mapping[str, Any]) -> Settings:
    multi_keys = _value(secrets, "GEMINI_API_KEYS", []) or []
    if isinstance(multi_keys, str):
        multi_keys = [multi_keys]
    single_key = str(_value(secrets, "GEMINI_API_KEY", "") or "").strip()
    keys = [str(item).strip() for item in multi_keys if str(item).strip()]
    if single_key and single_key not in keys:
        keys.insert(0, single_key)

    service_json = str(_value(secrets, "GOOGLE_SERVICE_ACCOUNT_JSON", "") or "").strip()
    if not service_json:
        nested = _value(secrets, "gcp_service_account", None)
        if nested:
            service_json = json.dumps(dict(nested), ensure_ascii=False)

    return Settings(
        gemini_api_keys=tuple(keys),
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
    )
