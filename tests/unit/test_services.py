from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models import Room
from app.services.instructions import instruction_name, validate_instruction
from app.services.map_groups import (
    MapGroupValidationError,
    build_map_name,
    build_role_visuals,
    map_group_content_hash,
    parse_map_name,
    validate_map_group_payload,
    validate_size_token,
)
from app.services.questionnaires import (
    QuestionnaireValidationError,
    protected_question_ids,
    split_protected_answers,
    validate_answers,
    validate_questionnaire_schema,
    validate_room_questionnaire_schema,
)
from app.services.troop_profiles import (
    TroopProfileValidationError,
    ensure_troop_profile_editable,
    validate_troop_profile_rows,
)

VALID_ID_CARD = "11010519491231002X"


def test_update_archive_snapshot_reason_preserves_other_fields():
    from app.services.rooms import _update_archive_snapshot_reason

    room = Room()
    room.archive_snapshot_json = {
        "schemaVersion": 6,
        "createdAt": "2026-10-21T00:00:00Z",
        "room": {
            "archiveReason": "abandoned",
            "internalLabel": "保留字段",
        },
    }
    _update_archive_snapshot_reason(room, "technical_abort")
    assert room.archive_snapshot_json["schemaVersion"] == 6
    assert room.archive_snapshot_json["createdAt"] == "2026-10-21T00:00:00Z"
    assert room.archive_snapshot_json["room"]["archiveReason"] == "technical_abort"
    assert room.archive_snapshot_json["room"]["internalLabel"] == "保留字段"
VALID_MODERN_ID_CARD = "110105199003074472"


def _payment_parameters() -> dict:
    return {
        "base_pay_cents": 4500,
        "performance_rate_cents": 1,
        "performance_floor_cents": 0,
        "performance_cap_cents": 2000,
        "showup_pay_cents": 1000,
    }


def _both_payload(**overrides) -> dict:
    data = {
        "mode": "both",
        "rows": 2,
        "cols": 2,
        "spawns": {"A": 0, "B": 3},
        "practice_trials": 1,
        "formal_trials": 1,
        "practice_turn_cap": 20,
        "practice_turn_seconds": 60,
        "formal_turn_cap": 20,
        "formal_turn_seconds": 30,
        "rest_seconds": 60,
        "randomize_formal": True,
        "payment": _payment_parameters(),
        "maps": [
            {
                "slot": "Both",
                "description": "中心争夺",
                "factor_level": "高收益",
                "cells": [None, None, None, None],
            }
        ],
    }
    data.update(overrides)
    return data


def _ab_payload(**overrides) -> dict:
    data = _both_payload()
    data["mode"] = "ab"
    data["maps"] = [
        {
            "slot": "A",
            "description": "中心争夺",
            "factor_level": "高收益",
            "cells": [None, None, None, None],
        },
        {
            "slot": "B",
            "description": "中心争夺",
            "factor_level": "高收益",
            "cells": [None, None, None, None],
        },
    ]
    data.update(overrides)
    return data


def test_build_map_name_produces_four_segments():
    built = build_map_name("中心争夺", 7, 7, "高收益", "A")
    assert built == {
        "name": "中心争夺-7*7-高收益-A",
        "prefix": "中心争夺-7*7-高收益",
        "description": "中心争夺",
        "sizeToken": "7*7",
        "factorLevel": "高收益",
        "playerSuffix": "A",
    }


def test_build_map_name_trims_segments():
    built = build_map_name(" 中心争夺 ", 3, 4, " 高收益 ", "Both")
    assert built["name"] == "中心争夺-3*4-高收益-Both"
    assert built["prefix"] == "中心争夺-3*4-高收益"


@pytest.mark.parametrize(
    ("description", "factor_level", "suffix"),
    [
        ("", "高收益", "A"),
        ("   ", "高收益", "A"),
        ("中心-争夺", "高收益", "A"),
        ("中心争夺", "高-收益", "A"),
        ("中心争夺", "", "A"),
        ("中心争夺", "高收益", "C"),
        ("中心争夺", "高收益", "both"),
    ],
)
def test_build_map_name_rejects_invalid_segments(description, factor_level, suffix):
    with pytest.raises(MapGroupValidationError):
        build_map_name(description, 2, 2, factor_level, suffix)


def test_build_map_name_rejects_non_string_segment():
    with pytest.raises(MapGroupValidationError, match="地图名称必须是四段"):
        build_map_name(None, 2, 2, "高收益", "A")


def test_build_map_name_rejects_overlong_segments():
    with pytest.raises(MapGroupValidationError, match="每段不能超过 200 个字符"):
        build_map_name("描" * 201, 2, 2, "高收益", "A")


def test_parse_map_name_requires_four_nonempty_stripped_segments():
    for name in (
        "中心争夺-2*2-高收益",
        "中心争夺--高收益-A",
        "中心争夺-2*2-高收益-A-额外",
        "中心争夺-2*2-高收益- A",
        " 中心争夺-2*2-高收益-A",
    ):
        with pytest.raises(MapGroupValidationError, match="地图名称必须是四段"):
            parse_map_name(name, 2, 2)
    with pytest.raises(MapGroupValidationError, match="地图名称必须是四段"):
        parse_map_name(None, 2, 2)


def test_parse_map_name_size_segment_must_match_board():
    with pytest.raises(MapGroupValidationError, match="地图尺寸标识必须为 2\\*2"):
        parse_map_name("中心争夺-3*3-高收益-A", 2, 2)
    with pytest.raises(MapGroupValidationError, match="地图尺寸标识必须为 10\\*10"):
        validate_size_token("9*10", 10, 10)
    assert parse_map_name("中心争夺-2*2-高收益-B", 2, 2)["name"] == "中心争夺-2*2-高收益-B"


def test_validate_both_mode_requires_exactly_one_both_map():
    payload = _both_payload()
    payload["maps"] = [
        {
            "slot": "A",
            "description": "中心争夺",
            "factor_level": "高收益",
            "cells": [None, None, None, None],
        }
    ]
    with pytest.raises(MapGroupValidationError, match="both 模式必须恰好包含一张 Both 地图"):
        validate_map_group_payload(payload, {}, 1)

    payload = _both_payload()
    payload["maps"] = payload["maps"] * 2
    with pytest.raises(MapGroupValidationError, match="both 模式必须恰好包含一张 Both 地图"):
        validate_map_group_payload(payload, {}, 1)

    with pytest.raises(MapGroupValidationError, match="both 模式必须恰好包含一张 Both 地图"):
        validate_map_group_payload(_both_payload(maps=[]), {}, 1)


def test_validate_ab_mode_requires_one_a_and_one_b_map():
    payload = _ab_payload()
    payload["maps"] = payload["maps"][:1]
    with pytest.raises(MapGroupValidationError, match="ab 模式必须恰好包含 A、B 各一张地图"):
        validate_map_group_payload(payload, {}, 1)

    duplicated = _ab_payload()
    duplicated["maps"] = [duplicated["maps"][0], dict(duplicated["maps"][0])]
    duplicated["maps"][1]["description"] = "中心争夺"
    with pytest.raises(MapGroupValidationError, match="ab 模式必须恰好包含 A、B 各一张地图"):
        validate_map_group_payload(duplicated, {}, 1)

    extra = _ab_payload()
    extra["maps"].append(dict(extra["maps"][0], slot="Both"))
    with pytest.raises(MapGroupValidationError, match="ab 模式必须恰好包含 A、B 各一张地图"):
        validate_map_group_payload(extra, {}, 1)


def test_validate_ab_mode_rejects_mismatched_prefix():
    for field, value in (
        ("description", "边缘争夺"),
        ("factor_level", "低收益"),
    ):
        payload = _ab_payload()
        payload["maps"][1][field] = value
        with pytest.raises(MapGroupValidationError, match="A/B 地图的前三段必须一致"):
            validate_map_group_payload(payload, {}, 1)


def test_validate_ab_mode_accepts_matching_prefix():
    data = validate_map_group_payload(_ab_payload(), {}, 1)
    assert data["name"] == "中心争夺-2*2-高收益"
    assert [item["name"] for item in data["maps"]] == [
        "中心争夺-2*2-高收益-A",
        "中心争夺-2*2-高收益-B",
    ]
    assert [item["slot"] for item in data["maps"]] == ["A", "B"]


def test_validate_map_group_accepts_factors_and_landmark_cells():
    payload = _both_payload(
        factors={"landmark": "present", "orientation": "horizontal"}
    )
    payload["maps"][0]["landmark_cells"] = [3, 0]
    data = validate_map_group_payload(payload, {}, 1)
    assert data["factors"] == {
        "landmark": "present",
        "orientation": "horizontal",
    }
    assert data["maps"][0]["landmarkCells"] == [0, 3]


def test_validate_map_group_rejects_invalid_factors_and_landmarks():
    payload = _both_payload(factors={" ": "present"})
    with pytest.raises(MapGroupValidationError, match="分析因素的名称"):
        validate_map_group_payload(payload, {}, 1)

    payload = _both_payload(factors={"landmark": ""})
    with pytest.raises(MapGroupValidationError, match="分析因素的取值"):
        validate_map_group_payload(payload, {}, 1)

    payload = _both_payload()
    payload["maps"][0]["landmark_cells"] = [0, 0]
    with pytest.raises(MapGroupValidationError, match="地标格不能重复"):
        validate_map_group_payload(payload, {}, 1)

    payload = _both_payload()
    payload["maps"][0]["landmark_cells"] = [4]
    with pytest.raises(MapGroupValidationError, match="地标格索引越界"):
        validate_map_group_payload(payload, {}, 1)


def test_map_group_content_hash_includes_factors_and_landmarks():
    payload = _both_payload(factors={"landmark": "present"})
    payload["maps"][0]["landmark_cells"] = [0, 3]
    data = validate_map_group_payload(payload, {}, 1)
    data["troop_profile_version_id"] = "profile-version"
    base = map_group_content_hash(data)

    changed_factors = dict(data, factors={"landmark": "absent"})
    assert map_group_content_hash(changed_factors) != base

    changed_landmarks = dict(data)
    changed_landmarks["maps"] = [dict(data["maps"][0], landmarkCells=[1])]
    assert map_group_content_hash(changed_landmarks) != base


def test_validate_rejects_unknown_mode():
    with pytest.raises(MapGroupValidationError, match="地图组模式必须为 both 或 ab"):
        validate_map_group_payload(_both_payload(mode="shared"), {}, 1)


def test_validate_map_cells_count_matches_total():
    payload = _both_payload()
    payload["maps"][0]["cells"] = [None, None, None]
    with pytest.raises(MapGroupValidationError, match="地图单元格数量必须为 4"):
        validate_map_group_payload(payload, {}, 1)
    payload["maps"][0]["cells"] = None
    with pytest.raises(MapGroupValidationError, match="地图单元格数量必须为 4"):
        validate_map_group_payload(payload, {}, 1)


def test_validate_map_cells_accept_null_cells():
    data = validate_map_group_payload(_both_payload(), {}, 1)
    assert data["maps"][0]["cells"] == [None, None, None, None]


def test_validate_map_cells_reject_missing_asset():
    payload = _both_payload()
    payload["maps"][0]["cells"] = ["asset-1", None, None, None]
    with pytest.raises(MapGroupValidationError, match="地图单元格引用的图片资源不存在"):
        validate_map_group_payload(payload, {}, 1)


def test_validate_map_cells_reject_webp():
    payload = _both_payload()
    payload["maps"][0]["cells"] = ["asset-1", None, None, None]
    with pytest.raises(MapGroupValidationError, match="地图单元格仅支持 PNG/JPG 图片"):
        validate_map_group_payload(payload, {"asset-1": "image/webp"}, 1)


@pytest.mark.parametrize("content_type", ["image/png", "image/jpeg"])
def test_validate_map_cells_accept_png_and_jpeg(content_type):
    payload = _both_payload()
    payload["maps"][0]["cells"] = ["asset-1", None, None, None]
    data = validate_map_group_payload(payload, {"asset-1": content_type}, 1)
    assert data["maps"][0]["cells"] == ["asset-1", None, None, None]


def test_validate_dimensions_require_at_least_two_rows_and_cols():
    for rows, cols in ((1, 4), (4, 1), (0, 0)):
        with pytest.raises(MapGroupValidationError, match="地图行数和列数必须至少为 2"):
            validate_map_group_payload(_both_payload(rows=rows, cols=cols), {}, 1)


def test_validate_dimensions_reject_more_than_one_hundred_cells():
    with pytest.raises(MapGroupValidationError, match="地图总格数不能超过 100"):
        validate_map_group_payload(_both_payload(rows=11, cols=10), {}, 1)
    data = validate_map_group_payload(
        _both_payload(rows=10, cols=10, maps=[{**_both_payload()["maps"][0], "cells": [None] * 100}]),
        {},
        1,
    )
    assert data["rows"] * data["cols"] == 100


def test_validate_dimensions_require_integers():
    with pytest.raises(MapGroupValidationError, match="rows 必须是整数"):
        validate_map_group_payload(_both_payload(rows=True), {}, 1)
    with pytest.raises(MapGroupValidationError, match="cols 必须是整数"):
        validate_map_group_payload(_both_payload(cols="2"), {}, 1)


def test_validate_rejects_spawn_out_of_range():
    for spawns in ({"A": -1, "B": 3}, {"A": 0, "B": 4}):
        with pytest.raises(MapGroupValidationError, match="出生格 A 和 B 必须在范围内且不能重合"):
            validate_map_group_payload(_both_payload(spawns=spawns), {}, 1)


def test_validate_rejects_spawn_overlap():
    with pytest.raises(MapGroupValidationError, match="出生格 A 和 B 必须在范围内且不能重合"):
        validate_map_group_payload(_both_payload(spawns={"A": 2, "B": 2}), {}, 1)


def test_validate_requires_spawn_object():
    with pytest.raises(MapGroupValidationError, match="出生格 A 和 B 必须在范围内且不能重合"):
        validate_map_group_payload(_both_payload(spawns=None), {}, 1)


def test_validate_practice_trials_are_fixed_to_one():
    with pytest.raises(MapGroupValidationError, match="练习对局数固定为 1"):
        validate_map_group_payload(_both_payload(practice_trials=2), {}, 1)


def test_validate_formal_trials_must_match_profile_rows():
    with pytest.raises(MapGroupValidationError, match="地图组正式对局数与兵力配置不一致"):
        validate_map_group_payload(_both_payload(formal_trials=2), {}, 6)
    with pytest.raises(MapGroupValidationError, match="正式对局数至少为 1"):
        validate_map_group_payload(_both_payload(formal_trials=0), {}, 1)


def test_validate_requires_positive_payment_and_timing():
    with pytest.raises(MapGroupValidationError, match="回合上限、倒计时、休息和费用必须为正数"):
        validate_map_group_payload(
            _both_payload(payment=_payment_parameters() | {"showup_pay_cents": 0}), {}, 1
        )
    with pytest.raises(MapGroupValidationError, match="回合上限、倒计时、休息和费用必须为正数"):
        validate_map_group_payload(_both_payload(rest_seconds=0), {}, 1)


def test_validate_requires_boolean_randomize_formal():
    with pytest.raises(MapGroupValidationError, match="randomize_formal 必须是布尔值"):
        validate_map_group_payload(_both_payload(randomize_formal=1), {}, 1)


def _profile_version(*, built_in: bool, status: str):
    return SimpleNamespace(
        troop_profile=SimpleNamespace(built_in=built_in),
        status=status,
    )


def test_troop_profile_rows_derive_formal_trial_count():
    rows = [
        {"soldiersA": 7, "soldiersB": 7},
        {"soldiersA": 8, "soldiersB": 8},
        {"soldiersA": 7, "soldiersB": 9},
    ]
    assert validate_troop_profile_rows(rows) == 2
    assert validate_troop_profile_rows(rows[:2]) == 1


def test_troop_profile_requires_practice_and_formal_rows():
    with pytest.raises(TroopProfileValidationError, match="1 行练习和至少 1 行正式"):
        validate_troop_profile_rows([{"soldiersA": 7, "soldiersB": 7}])
    with pytest.raises(TroopProfileValidationError, match="1 行练习和至少 1 行正式"):
        validate_troop_profile_rows(None)


def test_troop_profile_rejects_non_object_rows():
    with pytest.raises(TroopProfileValidationError, match="第 1 行配置必须是对象"):
        validate_troop_profile_rows([{"soldiersA": 7, "soldiersB": 7}, ["7", "7"]])


@pytest.mark.parametrize("value", [0, -1, True, 7.0, "7", None])
def test_troop_profile_requires_positive_integer_soldiers(value):
    rows = [
        {"soldiersA": 7, "soldiersB": 7},
        {"soldiersA": value, "soldiersB": 8},
    ]
    with pytest.raises(TroopProfileValidationError, match="第 1 行玩家 A 兵力必须是正整数"):
        validate_troop_profile_rows(rows)
    rows[1]["soldiersA"] = 8
    rows[1]["soldiersB"] = value
    with pytest.raises(TroopProfileValidationError, match="第 1 行玩家 B 兵力必须是正整数"):
        validate_troop_profile_rows(rows)


def test_built_in_troop_profile_is_read_only():
    with pytest.raises(HTTPException) as excinfo:
        ensure_troop_profile_editable(_profile_version(built_in=True, status="draft"))
    assert excinfo.value.status_code == 409
    assert excinfo.value.detail == "内置方案只读，请复制后修改"


def test_published_troop_profile_is_read_only():
    with pytest.raises(HTTPException) as excinfo:
        ensure_troop_profile_editable(_profile_version(built_in=False, status="published"))
    assert excinfo.value.status_code == 409
    assert excinfo.value.detail == "已发布的版本不可修改，请创建新版本"


def test_draft_troop_profile_is_editable():
    ensure_troop_profile_editable(_profile_version(built_in=False, status="draft"))


def test_instruction_name_derives_from_prefix_and_role():
    assert instruction_name("中心争夺-2*2-高收益", 1) == "中心争夺-2*2-高收益-A"
    assert instruction_name("中心争夺-2*2-高收益", 2) == "中心争夺-2*2-高收益-B"


@pytest.mark.parametrize("role", [0, 3, "1", None])
def test_instruction_name_rejects_invalid_role(role):
    with pytest.raises(ValueError, match="role 必须是 1 或 2"):
        instruction_name("中心争夺-2*2-高收益", role)


def test_validate_instruction_requires_text_and_non_negative_seconds():
    validate_instruction("阅读说明", 1, 0)
    with pytest.raises(ValueError, match="指导语正文不能为空"):
        validate_instruction("   ", 1, 30)
    with pytest.raises(ValueError, match="最短阅读时间不能为负"):
        validate_instruction("阅读说明", 1, -1)
    with pytest.raises(ValueError, match="role 必须是 1 或 2"):
        validate_instruction("阅读说明", 3, 30)


def _question(question_id: str, question_type: str, **extra) -> dict:
    data = {
        "id": question_id,
        "type": question_type,
        "label": question_id,
        "required": True,
    }
    data.update(extra)
    return data


def _protected_schema(**overrides) -> dict:
    questions = [
        _question("name", "real_name", label="真实姓名"),
        _question("phone", "alipay_phone", label="支付宝手机号"),
        _question("document", "identity_document", label="身份证明"),
        _question("comment", "short_text", required=False, maxLength=10),
    ]
    schema = {"title": "身份问卷", "pages": [{"id": "page-1", "questions": questions}]}
    schema.update(overrides)
    return schema


def _answers(**overrides) -> dict:
    answers = {
        "name": "  张三  ",
        "phone": "13800000001",
        "document": {"documentType": "id_card", "number": VALID_ID_CARD},
        "comment": "abc",
    }
    answers.update(overrides)
    return answers


def test_questionnaire_accepts_one_of_each_protected_type():
    schema = _protected_schema()
    validate_questionnaire_schema(schema)
    validate_room_questionnaire_schema(schema)
    assert protected_question_ids(schema) == ["name", "phone", "document"]


def test_questionnaire_requires_each_protected_type_once():
    incomplete = _protected_schema()
    incomplete["pages"][0]["questions"] = [
        item for item in incomplete["pages"][0]["questions"] if item["id"] != "document"
    ]
    with pytest.raises(QuestionnaireValidationError, match="问卷必须包含受保护题型: identity_document"):
        validate_room_questionnaire_schema(incomplete)

    duplicates = _protected_schema()
    duplicates["pages"][0]["questions"].insert(
        1, _question("name-2", "real_name", label="真实姓名二")
    )
    with pytest.raises(QuestionnaireValidationError, match="受保护题型重复: real_name"):
        validate_questionnaire_schema(duplicates)


def test_questionnaire_protected_questions_must_be_required():
    for question_id in ("name", "phone", "document"):
        schema = _protected_schema()
        for item in schema["pages"][0]["questions"]:
            if item["id"] == question_id:
                item["required"] = False
        with pytest.raises(QuestionnaireValidationError, match="受保护题型必须设置为必填"):
            validate_questionnaire_schema(schema)


def test_questionnaire_short_text_max_length_must_be_positive_integer():
    for value in (0, -1, True, "10", 1.5):
        schema = _protected_schema()
        for item in schema["pages"][0]["questions"]:
            if item["id"] == "comment":
                item["maxLength"] = value
        with pytest.raises(QuestionnaireValidationError, match="maxLength 必须是正整数"):
            validate_questionnaire_schema(schema)
    schema = _protected_schema()
    for item in schema["pages"][0]["questions"]:
        if item["id"] == "comment":
            item.pop("maxLength")
    validate_questionnaire_schema(schema)


def test_questionnaire_short_text_rejects_options():
    schema = _protected_schema()
    for item in schema["pages"][0]["questions"]:
        if item["id"] == "comment":
            item["options"] = [{"value": "a", "label": "a"}]
    with pytest.raises(QuestionnaireValidationError, match="单行填空不能包含 options"):
        validate_questionnaire_schema(schema)


def test_questionnaire_rejects_duplicate_question_ids():
    schema = _protected_schema()
    schema["pages"][0]["questions"].append(_question("comment", "text", required=False))
    with pytest.raises(QuestionnaireValidationError, match="题目 id 重复: comment"):
        validate_questionnaire_schema(schema)


def test_validate_answers_trims_real_name():
    validate_answers(_protected_schema(), _answers())
    for invalid in ("   ", 123, None):
        with pytest.raises(QuestionnaireValidationError):
            validate_answers(_protected_schema(), _answers(name=invalid))


def test_validate_answers_alipay_phone():
    validate_answers(_protected_schema(), _answers(phone=" 13800000001 "))
    for invalid in ("12800000001", "1380000000", "138-0000-0001", "138000000011", 13800000001):
        with pytest.raises(QuestionnaireValidationError, match="有效的大陆手机号|必须是文本"):
            validate_answers(_protected_schema(), _answers(phone=invalid))


def test_validate_answers_accepts_known_valid_id_cards():
    for number in (VALID_ID_CARD, VALID_MODERN_ID_CARD):
        validate_answers(
            _protected_schema(),
            _answers(document={"documentType": "id_card", "number": number}),
        )


def test_validate_answers_rejects_invalid_id_card_checksum():
    with pytest.raises(QuestionnaireValidationError, match="校验码"):
        validate_answers(
            _protected_schema(),
            _answers(document={"documentType": "id_card", "number": "110105194912310021"}),
        )


def test_validate_answers_rejects_invalid_id_card_birth_date():
    with pytest.raises(QuestionnaireValidationError, match="出生日期无效"):
        validate_answers(
            _protected_schema(),
            _answers(document={"documentType": "id_card", "number": "11010519490231002X"}),
        )
    with pytest.raises(QuestionnaireValidationError, match="不能晚于今天"):
        validate_answers(
            _protected_schema(),
            _answers(document={"documentType": "id_card", "number": "11010529990101002X"}),
        )
    with pytest.raises(QuestionnaireValidationError, match="年份"):
        validate_answers(
            _protected_schema(),
            _answers(document={"documentType": "id_card", "number": "440524188001010014"}),
        )


def test_validate_answers_rejects_id_card_wrong_length():
    with pytest.raises(QuestionnaireValidationError, match="18 位"):
        validate_answers(
            _protected_schema(),
            _answers(document={"documentType": "id_card", "number": "11010519491231002"}),
        )


def test_validate_answers_passport_length_between_five_and_twenty():
    for number in ("A1234", "E12345678", "A" * 20):
        validate_answers(
            _protected_schema(),
            _answers(document={"documentType": "passport", "number": number}),
        )
    for number in ("A123", "A" * 21, "E123-4567", "护照12345"):
        with pytest.raises(QuestionnaireValidationError, match="护照号码格式无效"):
            validate_answers(
                _protected_schema(),
                _answers(document={"documentType": "passport", "number": number}),
            )


def test_validate_answers_rejects_unknown_document_type_and_shape():
    with pytest.raises(QuestionnaireValidationError, match="证件类型必须是 id_card 或 passport"):
        validate_answers(
            _protected_schema(),
            _answers(document={"documentType": "visa", "number": "E12345678"}),
        )
    with pytest.raises(QuestionnaireValidationError, match="必须是对象"):
        validate_answers(_protected_schema(), _answers(document=["id_card", VALID_ID_CARD]))


def test_validate_answers_enforces_required_protected_fields():
    for field in ("name", "phone", "document"):
        with pytest.raises(QuestionnaireValidationError, match="必填题未作答"):
            validate_answers(_protected_schema(), _answers(**{field: None}))
    with pytest.raises(QuestionnaireValidationError, match="必填题未作答"):
        validate_answers(_protected_schema(), _answers(document={}))


def test_validate_answers_short_text_max_length():
    validate_answers(_protected_schema(), _answers(comment="abcdefghij"))
    with pytest.raises(QuestionnaireValidationError, match="超过最大长度 10"):
        validate_answers(_protected_schema(), _answers(comment="abcdefghijk"))
    with pytest.raises(QuestionnaireValidationError, match="必须是文本"):
        validate_answers(_protected_schema(), _answers(comment=123))


def test_validate_answers_rejects_unknown_question():
    with pytest.raises(QuestionnaireValidationError, match="答案包含未知题目: extra"):
        validate_answers(_protected_schema(), _answers(extra="x"))


def test_split_protected_answers_extracts_and_removes_fields():
    sanitized, payload = split_protected_answers(
        _protected_schema(),
        _answers(document={"documentType": "id_card", "number": VALID_ID_CARD.lower()}),
        enforce_required=True,
    )
    assert sanitized == {"comment": "abc"}
    assert payload == {
        "real_name": "张三",
        "alipay_phone": "13800000001",
        "document_type": "id_card",
        "document_number": VALID_ID_CARD,
    }
    assert "name" not in sanitized
    assert "phone" not in sanitized
    assert "document" not in sanitized


def test_split_protected_answers_keeps_passport_payload():
    sanitized, payload = split_protected_answers(
        _protected_schema(),
        _answers(document={"documentType": "passport", "number": " E12345678 "}),
        enforce_required=True,
    )
    assert sanitized == {"comment": "abc"}
    assert payload is not None
    assert payload["document_type"] == "passport"
    assert payload["document_number"] == "E12345678"


def test_split_protected_answers_draft_without_protected_values():
    sanitized, payload = split_protected_answers(
        _protected_schema(), {"comment": "草稿"}, enforce_required=False
    )
    assert sanitized == {"comment": "草稿"}
    assert payload is None


def test_split_protected_answers_requires_complete_types_for_submission():
    schema = _protected_schema()
    schema["pages"][0]["questions"] = [
        item for item in schema["pages"][0]["questions"] if item["id"] != "document"
    ]
    answers = {key: value for key, value in _answers().items() if key != "document"}
    with pytest.raises(QuestionnaireValidationError, match="缺少受保护题型: identity_document"):
        split_protected_answers(schema, answers, enforce_required=True)
    sanitized, payload = split_protected_answers(schema, {"comment": "abc"}, enforce_required=False)
    assert sanitized == {"comment": "abc"}
    assert payload is None


def test_map_colors_are_normalized_and_optional():
    payload = _both_payload()
    payload["maps"][0]["colors"] = ["#aabbcc", None, None, None]
    data = validate_map_group_payload(payload, {}, 1)
    assert data["maps"][0]["colors"] == ["#AABBCC", None, None, None]

    payload["maps"][0].pop("colors")
    data = validate_map_group_payload(payload, {}, 1)
    assert data["maps"][0]["colors"] == [None, None, None, None]


def test_map_colors_require_valid_length_and_format():
    payload = _both_payload()
    payload["maps"][0]["colors"] = ["#AABBCC", None, None]
    with pytest.raises(MapGroupValidationError, match="地图单元格颜色数量必须为 4"):
        validate_map_group_payload(payload, {}, 1)

    payload["maps"][0]["colors"] = ["red", None, None, None]
    with pytest.raises(MapGroupValidationError, match="地图单元格背景颜色必须为 #RRGGBB"):
        validate_map_group_payload(payload, {}, 1)


def test_map_colors_change_content_hash():
    data = validate_map_group_payload(_both_payload(), {}, 1)
    data["troop_profile_version_id"] = "profile-version"
    first = map_group_content_hash(data)
    data["maps"][0]["colors"] = ["#112233", None, None, None]
    assert map_group_content_hash(data) != first


def test_build_role_visuals_both_mode_uses_shared_map():
    version = SimpleNamespace(
        mode="both",
        maps=[
            SimpleNamespace(
                slot="Both",
                cells_json=["asset-1", None],
                colors_json=["#112233", None],
            )
        ],
    )
    expected = [
        {"color": "#112233", "backgroundAssetId": "asset-1"},
        {"color": None, "backgroundAssetId": None},
    ]
    assert build_role_visuals(version, 1) == expected
    assert build_role_visuals(version, 2) == expected


def test_build_role_visuals_ab_mode_uses_role_map():
    version = SimpleNamespace(
        mode="ab",
        maps=[
            SimpleNamespace(slot="A", cells_json=["a", None]),
            SimpleNamespace(slot="B", cells_json=[None, "b"]),
        ],
    )
    assert build_role_visuals(version, 1) == [
        {"color": None, "backgroundAssetId": "a"},
        {"color": None, "backgroundAssetId": None},
    ]
    assert build_role_visuals(version, 2) == [
        {"color": None, "backgroundAssetId": None},
        {"color": None, "backgroundAssetId": "b"},
    ]


def test_build_role_visuals_rejects_invalid_role_and_missing_map():
    version = SimpleNamespace(
        mode="ab",
        maps=[SimpleNamespace(slot="A", cells_json=[None])],
    )
    for role in (0, 3, None):
        with pytest.raises(ValueError, match="role 必须是 1 或 2"):
            build_role_visuals(version, role)
    with pytest.raises(ValueError, match="地图组缺少角色对应的地图"):
        build_role_visuals(version, 2)
