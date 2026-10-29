from app.services.runtime import _submission_msg_ids, _timeout_cell_index


def test_submission_msg_ids_reads_legacy_entry():
    assert _submission_msg_ids(None) == []
    assert _submission_msg_ids({}) == []
    assert _submission_msg_ids({"clientMsgId": "legacy"}) == ["legacy"]


def test_submission_msg_ids_keeps_all_revisions_without_duplicates():
    entry = {
        "clientMsgId": "second",
        "clientMsgIds": ["first", "second", "second"],
    }
    assert _submission_msg_ids(entry) == ["first", "second"]


def test_submission_msg_ids_appends_latest_when_missing_from_list():
    entry = {
        "clientMsgId": "second",
        "clientMsgIds": ["first"],
    }
    assert _submission_msg_ids(entry) == ["first", "second"]


def test_timeout_cell_index_is_deterministic_and_bounded():
    for total in (1, 4, 9):
        for seed in (0, 1, 7919, 2**63 - 1):
            index = _timeout_cell_index(seed, total)
            assert index == _timeout_cell_index(seed, total)
            assert 0 <= index < total


def test_timeout_cell_index_covers_the_whole_board():
    assert {_timeout_cell_index(seed, 4) for seed in range(256)} == {0, 1, 2, 3}
