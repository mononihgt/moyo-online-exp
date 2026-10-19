import pytest

from app.security import decrypt_identity, decrypt_phone, encrypt_identity
from app.services.questionnaires import (
    QuestionnaireValidationError,
    split_protected_answers,
    validate_answers,
)

VALID_ID_CARD = "11010519491231002X"
VALID_MODERN_ID_CARD = "110105199003074472"


def _schema() -> dict:
    return {
        "title": "身份问卷",
        "pages": [
            {
                "id": "page-1",
                "questions": [
                    {
                        "id": "comment",
                        "type": "short_text",
                        "label": "备注",
                        "required": False,
                        "maxLength": 5,
                    },
                    {"id": "name", "type": "real_name", "label": "真实姓名", "required": True},
                    {"id": "phone", "type": "alipay_phone", "label": "支付宝手机号", "required": True},
                    {
                        "id": "document",
                        "type": "identity_document",
                        "label": "身份证明",
                        "required": True,
                    },
                ],
            }
        ],
    }


def _answers(**overrides) -> dict:
    answers = {
        "comment": "abc",
        "name": "  张三  ",
        "phone": "13800000001",
        "document": {"documentType": "id_card", "number": VALID_ID_CARD},
    }
    answers.update(overrides)
    return answers


def test_identity_encryption_round_trip():
    encrypted = encrypt_identity("张三")
    assert encrypted != "张三"
    assert decrypt_identity(encrypted) == "张三"
    assert encrypt_identity("张三") != encrypted
    with pytest.raises(ValueError):
        decrypt_identity("not-a-valid-token")
    with pytest.raises(ValueError):
        decrypt_phone(encrypted)


def test_real_name_is_trimmed_in_payload():
    sanitized, payload = split_protected_answers(_schema(), _answers(), enforce_required=True)
    assert payload is not None
    assert payload["real_name"] == "张三"
    assert "name" not in sanitized
    with pytest.raises(QuestionnaireValidationError):
        validate_answers(_schema(), _answers(name="   "))


def test_alipay_phone_validation():
    validate_answers(_schema(), _answers(phone=" 13800000001 "))
    _, payload = split_protected_answers(
        _schema(), _answers(phone=" 13800000001 "), enforce_required=True
    )
    assert payload is not None
    assert payload["alipay_phone"] == "13800000001"
    for invalid in ("12800000001", "1380000000", "138-0000-0001", 13800000001, ["13800000001"]):
        with pytest.raises(QuestionnaireValidationError):
            validate_answers(_schema(), _answers(phone=invalid))


def test_id_card_checksum_and_date_validation():
    for valid in (VALID_ID_CARD, VALID_MODERN_ID_CARD):
        validate_answers(_schema(), _answers(document={"documentType": "id_card", "number": valid}))
    _, payload = split_protected_answers(
        _schema(),
        _answers(document={"documentType": "id_card", "number": VALID_ID_CARD.lower()}),
        enforce_required=True,
    )
    assert payload is not None
    assert payload["document_number"] == VALID_ID_CARD
    with pytest.raises(QuestionnaireValidationError, match="校验码"):
        validate_answers(
            _schema(), _answers(document={"documentType": "id_card", "number": "110105194912310021"})
        )
    with pytest.raises(QuestionnaireValidationError, match="出生日期无效"):
        validate_answers(
            _schema(), _answers(document={"documentType": "id_card", "number": "11010519490231002X"})
        )
    with pytest.raises(QuestionnaireValidationError, match="不能晚于今天"):
        validate_answers(
            _schema(), _answers(document={"documentType": "id_card", "number": "11010529990101002X"})
        )
    with pytest.raises(QuestionnaireValidationError, match="年份"):
        validate_answers(
            _schema(), _answers(document={"documentType": "id_card", "number": "440524188001010014"})
        )
    with pytest.raises(QuestionnaireValidationError, match="18 位"):
        validate_answers(
            _schema(), _answers(document={"documentType": "id_card", "number": "11010519491231002"})
        )


def test_passport_validation():
    for valid in ("E12345678", "AB1234567", "A1234"):
        validate_answers(
            _schema(), _answers(document={"documentType": "passport", "number": valid})
        )
    _, payload = split_protected_answers(
        _schema(),
        _answers(document={"documentType": "passport", "number": " E12345678 "}),
        enforce_required=True,
    )
    assert payload is not None
    assert payload["document_type"] == "passport"
    assert payload["document_number"] == "E12345678"
    for invalid in ("E123", "E123456789012345678901", "E123-4567", "护照12345"):
        with pytest.raises(QuestionnaireValidationError):
            validate_answers(
                _schema(), _answers(document={"documentType": "passport", "number": invalid})
            )
    with pytest.raises(QuestionnaireValidationError):
        validate_answers(
            _schema(), _answers(document={"documentType": "visa", "number": "E12345678"})
        )
    with pytest.raises(QuestionnaireValidationError):
        validate_answers(_schema(), _answers(document=["id_card", VALID_ID_CARD]))


def test_short_text_validation():
    validate_answers(_schema(), _answers(comment="abcde"))
    with pytest.raises(QuestionnaireValidationError, match="最大长度"):
        validate_answers(_schema(), _answers(comment="abcdef"))
    with pytest.raises(QuestionnaireValidationError):
        validate_answers(_schema(), _answers(comment=123))


def test_split_protected_answers_removes_fields():
    sanitized, payload = split_protected_answers(_schema(), _answers(), enforce_required=True)
    assert sanitized == {"comment": "abc"}
    assert payload == {
        "real_name": "张三",
        "alipay_phone": "13800000001",
        "document_type": "id_card",
        "document_number": VALID_ID_CARD,
    }


def test_split_missing_or_invalid_protected_answers():
    schema = _schema()
    draft_answers = {"comment": "abc"}
    sanitized, payload = split_protected_answers(schema, draft_answers, enforce_required=False)
    assert sanitized == {"comment": "abc"}
    assert payload is None
    with pytest.raises(QuestionnaireValidationError):
        split_protected_answers(schema, draft_answers, enforce_required=True)
    draft_with_invalid_phone = {"comment": "abc", "phone": "12345"}
    with pytest.raises(QuestionnaireValidationError):
        split_protected_answers(schema, draft_with_invalid_phone, enforce_required=False)
    incomplete_document = {"comment": "abc", "document": {"documentType": "id_card"}}
    with pytest.raises(QuestionnaireValidationError):
        split_protected_answers(schema, incomplete_document, enforce_required=False)
    partial_schema = {
        "title": "缺少证件题",
        "pages": [
            {
                "id": "page-1",
                "questions": [
                    {"id": "name", "type": "real_name", "label": "真实姓名", "required": True},
                    {"id": "phone", "type": "alipay_phone", "label": "支付宝手机号", "required": True},
                ],
            }
        ],
    }
    with pytest.raises(QuestionnaireValidationError, match="缺少受保护题型"):
        split_protected_answers(partial_schema, {"name": "张三", "phone": "13800000001"}, enforce_required=True)
    sanitized, payload = split_protected_answers(
        partial_schema, {"name": "张三", "phone": "13800000001"}, enforce_required=False
    )
    assert sanitized == {}
    assert payload is None
