from datetime import datetime

import pytest

from app.config import get_settings
from app.constants import (
    ARCHIVE_NO_SHOW,
    ARCHIVE_NO_START,
    ARCHIVE_NOT_FULL,
    ARCHIVE_TECHNICAL_ABORT,
    BOOKING_ATTENDED,
    BOOKING_BOOKED,
    BOOKING_CANCELED,
    QUESTIONNAIRE_COMPLETED,
    QUESTIONNAIRE_NOT_STARTED,
    ROOM_ARCHIVED,
)
from app.models import Booking, GameTrial, Room, RoomParticipant
from app.presets import preset_payload
from app.security import (
    decrypt_phone,
    encrypt_phone,
    mask_phone,
    normalize_phone,
    phone_hash,
)
from app.services.conditions import (
    ConditionValidationError,
    condition_content_hash,
    validate_condition_payload,
)
from app.services.instructions import render_markdown
from app.services.payments import compute_performance_cents, payment_deadline
from app.services.questionnaires import (
    QuestionnaireValidationError,
    validate_answers,
    validate_questionnaire_schema,
)
from app.services.rooms import (
    archive_reason_for_wait_expiry,
    booking_lock_message,
    participant_reward_kind,
)
from app.timeutil import week_deadline_utc


def test_phone_normalization_and_crypto():
    assert normalize_phone("138-0000-0001") == "13800000001"
    assert normalize_phone("+86 13800000001") == "13800000001"
    assert normalize_phone("008613800000001") == "13800000001"
    with pytest.raises(ValueError):
        normalize_phone("12345")
    digest = phone_hash("13800000001")
    assert digest == phone_hash("13800000001")
    assert digest != phone_hash("13800000002")
    encrypted = encrypt_phone("13800000001")
    assert encrypted != "13800000001"
    assert decrypt_phone(encrypted) == "13800000001"
    assert mask_phone("13800000001") == "138****0001"


def test_condition_presets_are_valid():
    for name in ("ref0", "ref1", "ref2", "ref3", "ref4", "ref5", "asym"):
        payload = preset_payload(name)
        validate_condition_payload(payload, set())
        assert payload["rows"] * payload["cols"] == 36
        assert payload["base_a_index"] == 7
        assert payload["base_b_index"] == 28
        assert len(payload["trial_params"]) == 7
        assert payload["trial_params"][0]["isPractice"] is True
        assert payload["metadata"]["conditionId"] == name
        assert condition_content_hash(payload).startswith("sha256:")


def test_condition_validation_rejects_bad_shapes():
    payload = preset_payload("ref0")
    payload["rows"] = 11
    payload["cols"] = 10
    with pytest.raises(ConditionValidationError):
        validate_condition_payload(payload, set())

    payload = preset_payload("ref0")
    payload["base_b_index"] = payload["base_a_index"]
    with pytest.raises(ConditionValidationError):
        validate_condition_payload(payload, set())

    payload = preset_payload("ref0")
    payload["trial_params"] = payload["trial_params"][:-1]
    with pytest.raises(ConditionValidationError):
        validate_condition_payload(payload, set())


def test_condition_validation_supports_non_square_boards():
    payload = preset_payload("ref0")
    rows, cols = 3, 4
    payload["rows"] = rows
    payload["cols"] = cols
    cells = []
    for index in range(rows * cols):
        cells.append(
            {
                "row": index // cols,
                "col": index % cols,
                "initialOwner": 1 if index == 0 else (2 if index == 11 else 0),
                "initialSoldiers": 0,
                "reinforcementA": 0,
                "reinforcementB": 0,
            }
        )
    layer = [{"color": "#FFFFFF", "backgroundAssetId": None} for _ in range(rows * cols)]
    payload["cells"] = cells
    payload["visuals"] = {"player1": layer, "player2": [dict(item) for item in layer]}
    payload["base_a_index"] = 0
    payload["base_b_index"] = 11
    payload["trial_params"] = [
        {
            "sourceIndex": 0,
            "isPractice": False,
            "formalTrial": 1,
            "baseSoldiersA": 5,
            "baseSoldiersB": 6,
            "reinforcementOverrides": {"player1": [{"cellIndex": 0, "value": 2}], "player2": None},
        }
    ]
    payload["practice_trials"] = 0
    payload["formal_trials"] = 1
    validate_condition_payload(payload, set())


def test_markdown_render_sanitizes_html_and_rewrites_assets():
    html = render_markdown(
        "# 标题\n\n<script>alert(1)</script>\n\n![图](asset://11111111-1111-1111-1111-111111111111)"
    )
    assert "<script" not in html
    assert "/media/11111111-1111-1111-1111-111111111111" in html
    assert "<h1>标题</h1>" in html


def test_questionnaire_schema_and_answers_validation():
    schema = {
        "title": "后测",
        "pages": [
            {
                "id": "p1",
                "questions": [
                    {
                        "id": "q1",
                        "type": "single_choice",
                        "label": "性别",
                        "required": True,
                        "options": [{"value": "f", "label": "女"}, {"value": "m", "label": "男"}],
                    },
                    {
                        "id": "q2",
                        "type": "likert",
                        "label": "评分",
                        "required": False,
                        "min": 1,
                        "max": 5,
                    },
                ],
            }
        ],
    }
    validate_questionnaire_schema(schema)
    validate_answers(schema, {"q1": "f", "q2": 3})
    validate_answers(schema, {}, enforce_required=False)
    with pytest.raises(QuestionnaireValidationError):
        validate_answers(schema, {"q2": 3})
    with pytest.raises(QuestionnaireValidationError):
        validate_answers(schema, {"q1": "x"})
    with pytest.raises(QuestionnaireValidationError):
        validate_answers(schema, {"q1": "f", "q2": 9})
    bad_schema = {"title": "x", "pages": [{"id": "p", "questions": []}]}
    with pytest.raises(QuestionnaireValidationError):
        validate_questionnaire_schema(bad_schema)


def test_performance_payment_uses_formal_trials_only():
    room = Room(performance_rate_cents=3)
    trials = [
        GameTrial(
            is_practice=True,
            ended_at=datetime(2026, 1, 1),
            summary_json={"finalSoldiers": {"player1": 1000, "player2": 0}},
        ),
        GameTrial(
            is_practice=False,
            ended_at=datetime(2026, 1, 1),
            summary_json={"finalSoldiers": {"player1": 10, "player2": 1}},
        ),
        GameTrial(
            is_practice=False,
            ended_at=datetime(2026, 1, 1),
            summary_json={"finalSoldiers": {"player1": 21, "player2": 1}},
        ),
    ]
    assert compute_performance_cents(room, trials, 1) == 47
    assert compute_performance_cents(room, trials, 2) == 3
    room.performance_rate_cents = 1
    assert compute_performance_cents(room, trials, 1) == 16
    assert compute_performance_cents(room, [], 1) == 0


def test_payment_deadline_is_sunday_midnight_shanghai():
    # 2026-10-21 10:00 上海时间（周三） -> 2026-10-25 24:00 上海 = 2026-10-25 16:00 UTC
    value = datetime(2026, 10, 21, 2, 0, 0)
    assert week_deadline_utc(value, "Asia/Shanghai") == datetime(2026, 10, 25, 16, 0, 0)


def test_payment_deadline_uses_later_of_start_week_and_completion_week():
    timezone = get_settings().timezone
    room = Room(starts_at=datetime(2026, 10, 21, 2, 0, 0))
    base = week_deadline_utc(room.starts_at, timezone)
    assert payment_deadline(room, None) == base
    assert payment_deadline(room, datetime(2026, 10, 20, 2, 0, 0)) == base
    completion = datetime(2026, 10, 28, 2, 0, 0)
    completion_deadline = week_deadline_utc(completion, timezone)
    assert completion_deadline > base
    assert payment_deadline(room, completion) == completion_deadline


def test_wait_expiry_reason_depends_on_bookings():
    assert archive_reason_for_wait_expiry([]) == ARCHIVE_NOT_FULL
    assert (
        archive_reason_for_wait_expiry([Booking(status=BOOKING_CANCELED)])
        == ARCHIVE_NOT_FULL
    )
    assert (
        archive_reason_for_wait_expiry([Booking(status=BOOKING_BOOKED)])
        == ARCHIVE_NOT_FULL
    )
    assert (
        archive_reason_for_wait_expiry(
            [Booking(status=BOOKING_ATTENDED), Booking(status=BOOKING_BOOKED)]
        )
        == ARCHIVE_NO_SHOW
    )
    assert (
        archive_reason_for_wait_expiry(
            [
                Booking(status=BOOKING_ATTENDED),
                Booking(status=BOOKING_CANCELED),
                Booking(status=BOOKING_ATTENDED),
            ]
        )
        == ARCHIVE_NO_START
    )


def test_booking_lock_messages_are_exact():
    assert booking_lock_message(True) == (
        "你已完成本次正式实验，但后测问卷尚未提交。请先继续填写并提交问卷，目前无法预约新的场次。"
    )
    assert booking_lock_message(False) == "你已完成全部实验，无法再预约新的场次。"


def test_participant_reward_kind_matrix():
    completed = RoomParticipant(questionnaire_status=QUESTIONNAIRE_COMPLETED)
    pending = RoomParticipant(questionnaire_status=QUESTIONNAIRE_NOT_STARTED)
    attended = Booking(status=BOOKING_ATTENDED)
    booked = Booking(status=BOOKING_BOOKED)
    questionnaire_room = Room(archive_reason=None, showup_pay_cents=500)
    assert participant_reward_kind(questionnaire_room, completed, attended) == "completion"
    aborted_room = Room(
        status=ROOM_ARCHIVED,
        archive_reason=ARCHIVE_TECHNICAL_ABORT,
        showup_pay_cents=500,
    )
    assert participant_reward_kind(aborted_room, pending, attended) == "showup"
    assert participant_reward_kind(aborted_room, pending, booked) == "none"
    aborted_room.showup_pay_cents = 0
    assert participant_reward_kind(aborted_room, pending, attended) == "none"
    not_full_room = Room(
        status=ROOM_ARCHIVED,
        archive_reason=ARCHIVE_NOT_FULL,
        showup_pay_cents=500,
    )
    assert participant_reward_kind(not_full_room, pending, attended) == "none"
