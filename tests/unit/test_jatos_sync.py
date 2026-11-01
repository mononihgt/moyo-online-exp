from datetime import datetime, timezone

import pytest

from app.services.jatos import (
    iter_study_results,
    parse_jatos_datetime,
    parse_jatos_query_parameters,
    result_completion_time,
)
from app.services.jatos_sync import (
    SyncCandidate,
    SyncSkip,
    _resolve_target,
    build_candidates,
)


def _utc_from_epoch_millis(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).replace(tzinfo=None)


def test_parse_jatos_query_parameters_supports_dict_json_and_query_string():
    expected = {"rt": "token-value", "pid": "P-abc123"}
    assert parse_jatos_query_parameters(expected) == expected
    assert parse_jatos_query_parameters('{"rt":"token-value","pid":"P-abc123"}') == expected
    assert parse_jatos_query_parameters("rt=token-value&pid=P-abc123") == expected
    assert parse_jatos_query_parameters(None) == {}
    assert parse_jatos_query_parameters({}) == {}
    assert parse_jatos_query_parameters("{bad") == {}


def test_parse_jatos_datetime_supports_epoch_millis_and_iso_strings():
    epoch_millis = 1793502731000
    assert parse_jatos_datetime(epoch_millis) == _utc_from_epoch_millis(epoch_millis)
    assert parse_jatos_datetime(str(epoch_millis)) == _utc_from_epoch_millis(epoch_millis)
    assert parse_jatos_datetime(epoch_millis / 1000) == _utc_from_epoch_millis(epoch_millis)
    assert parse_jatos_datetime("2026-10-30T01:27:11.000+00:00") == datetime(
        2026, 10, 30, 1, 27, 11
    )
    assert parse_jatos_datetime("2026-10-30T09:27:11+08:00") == datetime(
        2026, 10, 30, 1, 27, 11
    )
    assert parse_jatos_datetime("2026-10-30T01:27:11Z") == datetime(2026, 10, 30, 1, 27, 11)
    assert parse_jatos_datetime("not-a-date") is None
    assert parse_jatos_datetime(None) is None


def test_result_completion_time_priority():
    fallback = datetime(2026, 11, 1, 12, 0, 0)
    component_end = 1793502731000
    study_end = 1793502732000
    last_seen = 1793502733000
    study_result = {
        "endDate": study_end,
        "lastSeenDate": last_seen,
    }
    component_result = {"endDate": component_end}
    assert result_completion_time(
        study_result, component_result, fallback=fallback
    ) == _utc_from_epoch_millis(component_end)

    component_result = {"endDate": None}
    assert result_completion_time(
        study_result, component_result, fallback=fallback
    ) == _utc_from_epoch_millis(study_end)

    study_result = {"endDate": None, "lastSeenDate": last_seen}
    assert result_completion_time(
        study_result, component_result, fallback=fallback
    ) == _utc_from_epoch_millis(last_seen)

    assert (
        result_completion_time(
            {"endDate": None, "lastSeenDate": None},
            {"endDate": None},
            fallback=fallback,
        )
        == fallback
    )


def test_iter_study_results_flattens_metadata_groups():
    payload = {
        "data": [
            {"studyResults": [{"id": 1}, {"id": 2}]},
            {"studyResults": []},
        ]
    }
    assert list(iter_study_results(payload)) == [{"id": 1}, {"id": 2}]


async def test_resolve_target_requires_rt_token():
    candidate = SyncCandidate(
        study_result_id="1",
        component_result_id="2",
        worker_id=None,
        query_parameters={},
        completion_time=datetime(2026, 1, 1),
    )
    with pytest.raises(SyncSkip, match="缺少问卷 token"):
        await _resolve_target(candidate)


def test_build_candidates_filters_empty_data_and_imported_pairs_and_sorts():
    last_seen = 1793502731000
    payload = {
        "data": [
            {
                "studyResults": [
                    {
                        "id": 10,
                        "workerId": 7,
                        "urlQueryParameters": {"rt": "token-a", "pid": "P-a"},
                        "endDate": None,
                        "lastSeenDate": last_seen,
                        "componentResults": [
                            {"id": 11, "data": {"size": 10}, "endDate": None},
                            {"id": 12, "data": {"size": 0}, "endDate": None},
                        ],
                    },
                    {
                        "id": 9,
                        "workerId": 7,
                        "urlQueryParameters": {"rt": "token-b", "pid": "P-b"},
                        "componentResults": [
                            {"id": 9, "data": {"size": 10}, "endDate": None}
                        ],
                    },
                    {
                        "id": 11,
                        "workerId": 8,
                        "urlQueryParameters": {"rt": "token-c", "pid": "P-c"},
                        "componentResults": [
                            {
                                "id": 13,
                                "data": {"size": 5},
                                "endDate": 1793502732000,
                            }
                        ],
                    },
                ]
            }
        ]
    }
    sync_time = datetime(2026, 11, 1, 12, 0, 0)
    candidates = build_candidates(
        payload, {("9", "9")}, sync_time=sync_time
    )
    assert [
        (candidate.study_result_id, candidate.component_result_id)
        for candidate in candidates
    ] == [("10", "11"), ("11", "13")]
    assert candidates[0].worker_id == "7"
    assert candidates[0].query_parameters == {"rt": "token-a", "pid": "P-a"}
    assert candidates[0].completion_time == _utc_from_epoch_millis(last_seen)
    assert candidates[1].completion_time == _utc_from_epoch_millis(1793502732000)
