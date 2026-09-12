import json

from src.settings import load_settings


def test_loads_teacher_settings_without_server_gemini_key():
    service = {"type": "service_account", "client_email": "bot@example.test"}
    settings = load_settings(
        {
            "SPREADSHEET_ID": "sheet-id",
            "GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps(service),
        }
    )

    assert settings.gemini_api_keys == ()
    assert settings.gemini_configured is False
    assert settings.service_account_info()["client_email"] == "bot@example.test"
    assert settings.require_sheets is True


def test_legacy_server_gemini_keys_are_ignored():
    settings = load_settings(
        {
            "GEMINI_API_KEY": "teacher-key-legacy",
            "GEMINI_API_KEYS": ["teacher-key-1", "teacher-key-2"],
        }
    )

    assert settings.gemini_api_keys == ()
    assert settings.gemini_configured is False
