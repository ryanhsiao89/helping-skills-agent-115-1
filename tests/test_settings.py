import json

from src.settings import load_settings


def test_loads_teacher_settings_without_server_gemini_key():
    service = {"type": "service_account", "client_email": "bot@example.test"}
    settings = load_settings(
        {
            "SPREADSHEET_ID": "sheet-id",
            "GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps(service),
            "SCHOOL_EMAIL_DOMAINS": ["school.edu.tw"],
            "email": {
                "sender": "teacher@gmail.com",
                "password": "app-password",
            },
        }
    )

    assert settings.gemini_api_keys == ()
    assert settings.gemini_configured is False
    assert settings.service_account_info()["client_email"] == "bot@example.test"
    assert settings.require_sheets is True
    assert settings.email_sender == "teacher@gmail.com"
    assert settings.email_password == "app-password"
    assert settings.school_email_domains == ("school.edu.tw",)
    assert settings.otp_configured is True
    assert settings.otp_ttl_seconds == 600
    assert settings.otp_resend_seconds == 60
    assert settings.otp_max_attempts == 5


def test_legacy_email_secret_names_are_supported():
    settings = load_settings(
        {
            "SCHOOL_EMAIL_DOMAINS": ["hcu.edu.tw"],
            "email": {
                "sender_email": "legacy@gmail.com",
                "app_password": "legacy-app-password",
            },
        }
    )

    assert settings.email_sender == "legacy@gmail.com"
    assert settings.email_password == "legacy-app-password"
    assert settings.school_email_domains == ("hcu.edu.tw",)
    assert settings.otp_configured is True


def test_legacy_server_gemini_keys_are_ignored():
    settings = load_settings(
        {
            "GEMINI_API_KEY": "teacher-key-legacy",
            "GEMINI_API_KEYS": ["teacher-key-1", "teacher-key-2"],
        }
    )

    assert settings.gemini_api_keys == ()
    assert settings.gemini_configured is False
    assert settings.otp_configured is False
