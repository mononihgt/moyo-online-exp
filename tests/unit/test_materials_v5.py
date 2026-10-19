import pytest
from fastapi import HTTPException

from app.models import TroopProfile, TroopProfileVersion
from app.services.instructions import instruction_name
from app.services.map_groups import (
    MapGroupValidationError,
    build_map_name,
    parse_map_name,
    validate_map_group_payload,
)
from app.services.questionnaires import (
    QuestionnaireValidationError,
    validate_questionnaire_schema,
)
from app.services.troop_profiles import (
    TroopProfileValidationError,
    ensure_troop_profile_editable,
    validate_troop_profile_rows,
)


def _payment(**overrides) -> dict:
    data = {
        "base_pay_cents": 4500,
        "performance_rate_cents": 1,
        "performance_cap_cents": 2000,
        "showup_pay_cents": 1000,
    }
    data.update(overrides)
    return data


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
        "payment": _payment(),
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


def test_build_map_name_has_four_segments():
    built = build_map_name("中心争夺", 7, 7, "高收益", "A")
    assert built["name"] == "中心争夺-7*7-高收益-A"
    assert built["prefix"] == "中心争夺-7*7-高收益"
    assert built["sizeToken"] == "7*7"
    assert built["playerSuffix"] == "A"


def test_build_map_name_rejects_hyphen_in_description():
    with pytest.raises(MapGroupValidationError, match="地图名称必须是四段"):
        build_map_name("中心-争夺", 7, 7, "高收益", "A")


def test_parse_map_name_checks_size_token():
    with pytest.raises(MapGroupValidationError, match="地图尺寸标识必须为 7\\*7"):
        parse_map_name("中心争夺-6*7-高收益-A", 7, 7)


def test_parse_map_name_rejects_three_segments():
    with pytest.raises(MapGroupValidationError, match="地图名称必须是四段"):
        parse_map_name("中心争夺-7*7-A", 7, 7)


def test_validate_both_mode_requires_single_both_map():
    payload = _both_payload(maps=[_ab_payload()["maps"][0]])
    with pytest.raises(MapGroupValidationError, match="both 模式必须恰好包含一张 Both 地图"):
        validate_map_group_payload(payload, {}, 1)


def test_validate_ab_mode_requires_a_and_b_maps():
    payload = _ab_payload(maps=[_ab_payload()["maps"][0]])
    with pytest.raises(MapGroupValidationError, match="ab 模式必须恰好包含 A、B 各一张地图"):
        validate_map_group_payload(payload, {}, 1)


def test_validate_ab_mode_requires_matching_prefix():
    payload = _ab_payload()
    payload["maps"][1]["description"] = "边缘争夺"
    with pytest.raises(MapGroupValidationError, match="A/B 地图的前三段必须一致"):
        validate_map_group_payload(payload, {}, 1)


def test_validate_ab_mode_accepts_matching_prefix():
    result = validate_map_group_payload(_ab_payload(), {}, 1)
    assert result["name"] == "中心争夺-2*2-高收益"
    assert [item["name"] for item in result["maps"]] == [
        "中心争夺-2*2-高收益-A",
        "中心争夺-2*2-高收益-B",
    ]


def test_validate_cells_count_must_match_size():
    payload = _both_payload()
    payload["maps"][0]["cells"] = [None, None, None]
    with pytest.raises(MapGroupValidationError, match="地图单元格数量必须为 4"):
        validate_map_group_payload(payload, {}, 1)


def test_validate_rejects_webp_assets():
    payload = _both_payload()
    payload["maps"][0]["cells"] = ["asset-1", None, None, None]
    with pytest.raises(MapGroupValidationError, match="地图单元格仅支持 PNG/JPG 图片"):
        validate_map_group_payload(payload, {"asset-1": "image/webp"}, 1)


def test_validate_accepts_png_assets():
    payload = _both_payload()
    payload["maps"][0]["cells"] = ["asset-1", None, None, None]
    result = validate_map_group_payload(payload, {"asset-1": "image/png"}, 1)
    assert result["maps"][0]["cells"] == ["asset-1", None, None, None]


def test_validate_rejects_missing_assets():
    payload = _both_payload()
    payload["maps"][0]["cells"] = ["missing", None, None, None]
    with pytest.raises(MapGroupValidationError, match="地图单元格引用的图片资源不存在"):
        validate_map_group_payload(payload, {}, 1)


def test_validate_rejects_spawn_overlap():
    payload = _both_payload(spawns={"A": 2, "B": 2})
    with pytest.raises(MapGroupValidationError, match="出生格 A 和 B 必须在范围内且不能重合"):
        validate_map_group_payload(payload, {}, 1)


def test_validate_rejects_formal_trials_mismatch():
    with pytest.raises(MapGroupValidationError, match="地图组正式对局数与兵力配置不一致"):
        validate_map_group_payload(_both_payload(), {}, 6)


def test_validate_requires_non_positive_payment_rejected():
    payload = _both_payload(payment=_payment(showup_pay_cents=0))
    with pytest.raises(MapGroupValidationError, match="回合上限、倒计时、休息和费用必须为正数"):
        validate_map_group_payload(payload, {}, 1)


def test_troop_profile_rows_require_practice_and_formal():
    with pytest.raises(TroopProfileValidationError, match="1 行练习和至少 1 行正式"):
        validate_troop_profile_rows([{"soldiersA": 7, "soldiersB": 7}])


def test_troop_profile_rows_require_positive_integers():
    rows = [{"soldiersA": 7, "soldiersB": 7}, {"soldiersA": 0, "soldiersB": 8}]
    with pytest.raises(TroopProfileValidationError, match="玩家 A 兵力必须是正整数"):
        validate_troop_profile_rows(rows)
    rows[1]["soldiersA"] = True
    with pytest.raises(TroopProfileValidationError, match="玩家 A 兵力必须是正整数"):
        validate_troop_profile_rows(rows)


def test_troop_profile_rows_return_formal_count():
    rows = [
        {"soldiersA": 7, "soldiersB": 7},
        {"soldiersA": 8, "soldiersB": 8},
        {"soldiersA": 7, "soldiersB": 9},
    ]
    assert validate_troop_profile_rows(rows) == 2


def _profile_version(built_in: bool, status_value: str) -> TroopProfileVersion:
    profile = TroopProfile(name="方案", built_in=built_in)
    return TroopProfileVersion(
        troop_profile=profile,
        version=1,
        rows_json=[{"soldiersA": 7, "soldiersB": 7}, {"soldiersA": 8, "soldiersB": 8}],
        formal_trials=1,
        status=status_value,
    )


def test_builtin_troop_profile_is_read_only():
    with pytest.raises(HTTPException) as excinfo:
        ensure_troop_profile_editable(_profile_version(True, "draft"))
    assert excinfo.value.status_code == 409
    assert excinfo.value.detail == "内置方案只读，请复制后修改"


def test_published_troop_profile_is_read_only():
    with pytest.raises(HTTPException) as excinfo:
        ensure_troop_profile_editable(_profile_version(False, "published"))
    assert excinfo.value.status_code == 409
    assert excinfo.value.detail == "已发布的版本不可修改，请创建新版本"


def test_instruction_name_uses_prefix_and_role():
    assert instruction_name("中心争夺-7*7-高收益", 1) == "中心争夺-7*7-高收益-A"
    assert instruction_name("中心争夺-7*7-高收益", 2) == "中心争夺-7*7-高收益-B"


def test_instruction_name_rejects_unknown_role():
    with pytest.raises(ValueError):
        instruction_name("前缀", 3)


def _question(question_id: str, question_type: str, **extra) -> dict:
    data = {
        "id": question_id,
        "type": question_type,
        "label": question_id,
        "required": True,
    }
    data.update(extra)
    return data


def _questionnaire(questions: list[dict]) -> dict:
    return {"title": "问卷", "pages": [{"id": "page-1", "questions": questions}]}


def test_questionnaire_protected_types_are_unique():
    schema = _questionnaire(
        [
            _question("name-1", "real_name"),
            _question("name-2", "real_name"),
            _question("phone", "alipay_phone"),
            _question("document", "identity_document"),
        ]
    )
    with pytest.raises(QuestionnaireValidationError, match="受保护题型重复: real_name"):
        validate_questionnaire_schema(schema)


def test_questionnaire_protected_types_must_be_required():
    schema = _questionnaire(
        [
            _question("name", "real_name", required=False),
            _question("phone", "alipay_phone"),
            _question("document", "identity_document"),
        ]
    )
    with pytest.raises(QuestionnaireValidationError, match="受保护题型必须设置为必填"):
        validate_questionnaire_schema(schema)


def test_questionnaire_publish_requires_all_protected_types():
    schema = _questionnaire(
        [_question("name", "real_name"), _question("phone", "alipay_phone")]
    )
    with pytest.raises(QuestionnaireValidationError, match="问卷必须包含受保护题型: identity_document"):
        validate_questionnaire_schema(schema, require_protected=True)


def test_questionnaire_publish_accepts_complete_protected_types():
    schema = _questionnaire(
        [
            _question("name", "real_name"),
            _question("phone", "alipay_phone"),
            _question("document", "identity_document"),
            _question("comment", "short_text", required=False, maxLength=200),
        ]
    )
    validate_questionnaire_schema(schema, require_protected=True)


def test_short_text_rejects_options():
    schema = _questionnaire(
        [_question("comment", "short_text", options=[{"value": "a", "label": "a"}])]
    )
    with pytest.raises(QuestionnaireValidationError, match="单行填空不能包含 options"):
        validate_questionnaire_schema(schema)


def test_short_text_rejects_invalid_max_length():
    schema = _questionnaire([_question("comment", "short_text", maxLength=0)])
    with pytest.raises(QuestionnaireValidationError, match="maxLength 必须是正整数"):
        validate_questionnaire_schema(schema)
