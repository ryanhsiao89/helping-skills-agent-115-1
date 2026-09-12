import json

from src.settings import load_settings


def test_loads_multiple_keys_and_service_json():
    service = {"type": "service_account", "client_email": "bot@example.test"}
    settings = load_settings(
        {
            "GEMINI_API_KEYS": ["key-1", "key-2"],
            "SPREADSHEET_ID": "sheet-id",
            "GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps(service),
        }
    )
    assert settings.gemini_api_keys == ("key-1", "key-2")
    assert settings.service_account_info()["client_email"] == "bot@example.test"
    assert settings.require_sheets is True
