from app.services.runtime import _submission_msg_ids


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
