from src.cases import PRACTICE_CASES, get_case


def test_all_cases_have_progressive_disclosure_layers():
    assert PRACTICE_CASES
    for case_id, case in PRACTICE_CASES.items():
        assert case["opening"]
        assert set(case["disclosure"]) == {"level_1", "level_2", "level_3", "level_4"}
        assert get_case(case_id)["case_id"] == case_id


def test_get_case_returns_copy():
    first = get_case("college_peer_01")
    first["persona"]["name"] = "changed"
    second = get_case("college_peer_01")
    assert second["persona"]["name"] != "changed"
