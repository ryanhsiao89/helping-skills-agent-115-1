from src.email_otp import (
    email_allowed,
    mask_email,
    normalize_email,
    otp_digest,
    otp_matches,
    participant_id_for_email,
)


def test_school_email_domain_validation_and_masking():
    assert normalize_email(" Student@School.edu.tw ") == "student@school.edu.tw"
    assert email_allowed("student@school.edu.tw", ("school.edu.tw",)) is True
    assert email_allowed("student@dept.school.edu.tw", ("school.edu.tw",)) is True
    assert email_allowed("student@gmail.com", ("school.edu.tw",)) is False
    assert mask_email("student@school.edu.tw") == "st***@school.edu.tw"


def test_participant_id_is_stable_and_pseudonymous():
    first = participant_id_for_email("student@school.edu.tw")
    second = participant_id_for_email("STUDENT@SCHOOL.EDU.TW")
    assert first == second
    assert first.startswith("S")
    assert "student" not in first.lower()


def test_otp_digest_does_not_store_raw_code():
    digest = otp_digest("student@school.edu.tw", "123456", "nonce")
    assert digest != "123456"
    assert otp_matches("student@school.edu.tw", "123456", "nonce", digest) is True
    assert otp_matches("student@school.edu.tw", "654321", "nonce", digest) is False
