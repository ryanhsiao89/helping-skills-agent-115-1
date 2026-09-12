from src.safety import detect_immediate_crisis


def test_detects_explicit_immediate_first_person_risk():
    assert detect_immediate_crisis("我今晚打算自殺").is_crisis
    assert detect_immediate_crisis("我正在準備傷害自己").is_crisis


def test_does_not_flag_generic_or_third_person_discussion():
    assert not detect_immediate_crisis("課堂上正在討論自殺防治").is_crisis
    assert not detect_immediate_crisis("我的朋友以前曾經說過想死").is_crisis
    assert not detect_immediate_crisis("我沒有想自殺").is_crisis
