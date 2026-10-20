import hashlib
import json
import re
from datetime import date
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    PROTECTED_QUESTION_TYPES,
    QUESTION_TYPE_ALIPAY_PHONE,
    QUESTION_TYPE_IDENTITY_DOCUMENT,
    QUESTION_TYPE_REAL_NAME,
    QUESTION_TYPE_SHORT_TEXT,
    QUESTION_TYPES,
    VERSION_ARCHIVED,
    VERSION_DRAFT,
    VERSION_PUBLISHED,
)
from ..models import QuestionnaireVersion
from ..timeutil import isoformat_utc, utcnow


class QuestionnaireValidationError(ValueError):
    pass


def _require_nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QuestionnaireValidationError(f"{label} 必须是非空字符串")
    return value


_ALIPAY_PHONE_PATTERN = re.compile(r"^1[3-9]\d{9}$")
_ID_CARD_PATTERN = re.compile(r"^\d{17}[\dXx]$")
_PASSPORT_PATTERN = re.compile(r"^[A-Za-z0-9]{5,20}$")
_ID_CARD_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_CARD_CHECK_CODES = "10X98765432"
IDENTITY_DOCUMENT_TYPES = ("id_card", "passport")


def _validate_short_text(value: Any, question: dict) -> str:
    if not isinstance(value, str):
        raise QuestionnaireValidationError(f"题目 {question['id']} 必须是文本")
    max_length = question.get("maxLength")
    if max_length is not None and len(value) > max_length:
        raise QuestionnaireValidationError(f"题目 {question['id']} 超过最大长度 {max_length}")
    return value


def _validate_real_name(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise QuestionnaireValidationError(f"{label} 必须是文本")
    name = value.strip()
    if not name:
        raise QuestionnaireValidationError(f"{label} 必须是非空字符串")
    return name


def _validate_alipay_phone(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise QuestionnaireValidationError(f"{label} 必须是文本")
    phone = value.strip()
    if not _ALIPAY_PHONE_PATTERN.fullmatch(phone):
        raise QuestionnaireValidationError(f"{label} 必须是有效的大陆手机号")
    return phone


def _validate_identity_document(value: Any, label: str) -> dict:
    if not isinstance(value, dict):
        raise QuestionnaireValidationError(f"{label} 必须是对象")
    document_type = value.get("documentType")
    number = value.get("number")
    if not isinstance(document_type, str) or document_type not in IDENTITY_DOCUMENT_TYPES:
        raise QuestionnaireValidationError(f"{label} 的证件类型必须是 id_card 或 passport")
    if not isinstance(number, str) or not number.strip():
        raise QuestionnaireValidationError(f"{label} 的证件号码必须是非空字符串")
    number = number.strip()
    if document_type == "id_card":
        if not _ID_CARD_PATTERN.fullmatch(number):
            raise QuestionnaireValidationError(f"{label} 的身份证号必须为 18 位")
        birth_text = number[6:14]
        try:
            birth_date = date(int(birth_text[:4]), int(birth_text[4:6]), int(birth_text[6:8]))
        except ValueError as exc:
            raise QuestionnaireValidationError(f"{label} 的身份证出生日期无效") from exc
        if birth_date > date.today():
            raise QuestionnaireValidationError(f"{label} 的身份证出生日期不能晚于今天")
        if birth_date.year < 1900:
            raise QuestionnaireValidationError(f"{label} 的身份证出生日期年份无效")
        total = sum(int(number[index]) * _ID_CARD_WEIGHTS[index] for index in range(17))
        if number[17].upper() != _ID_CARD_CHECK_CODES[total % 11]:
            raise QuestionnaireValidationError(f"{label} 的身份证校验码无效")
        number = number[:17] + number[17].upper()
    elif not _PASSPORT_PATTERN.fullmatch(number):
        raise QuestionnaireValidationError(f"{label} 的护照号码格式无效")
    return {"documentType": document_type, "number": number}


def validate_identity_values(
    real_name: Any,
    alipay_phone: Any,
    document_type: Any,
    document_number: Any,
) -> dict:
    document = _validate_identity_document(
        {"documentType": document_type, "number": document_number},
        "身份证明",
    )
    return {
        "real_name": _validate_real_name(real_name, "真实姓名"),
        "alipay_phone": _validate_alipay_phone(alipay_phone, "支付宝手机号"),
        "document_type": document["documentType"],
        "document_number": document["number"],
    }


def protected_question_ids(schema: dict) -> list[str]:
    return [
        question["id"]
        for page in schema.get("pages", [])
        for question in page.get("questions", [])
        if question.get("type") in PROTECTED_QUESTION_TYPES
    ]


def validate_questionnaire_schema(schema: dict, *, require_protected: bool = False) -> None:
    if not isinstance(schema, dict):
        raise QuestionnaireValidationError("问卷 schema 必须是对象")
    _require_nonempty_string(schema.get("title"), "title")
    pages = schema.get("pages")
    if not isinstance(pages, list) or not pages:
        raise QuestionnaireValidationError("pages 必须是非空数组")
    seen_pages: set[str] = set()
    seen_questions: set[str] = set()
    seen_protected: set[str] = set()
    for page_index, page in enumerate(pages):
        if not isinstance(page, dict):
            raise QuestionnaireValidationError(f"pages[{page_index}] 必须是对象")
        page_id = _require_nonempty_string(page.get("id"), f"pages[{page_index}].id")
        if page_id in seen_pages:
            raise QuestionnaireValidationError(f"页面 id 重复: {page_id}")
        seen_pages.add(page_id)
        questions = page.get("questions")
        if not isinstance(questions, list) or not questions:
            raise QuestionnaireValidationError(f"pages[{page_index}].questions 必须是非空数组")
        for question_index, question in enumerate(questions):
            label_prefix = f"pages[{page_index}].questions[{question_index}]"
            if not isinstance(question, dict):
                raise QuestionnaireValidationError(f"{label_prefix} 必须是对象")
            question_id = _require_nonempty_string(question.get("id"), f"{label_prefix}.id")
            if question_id in seen_questions:
                raise QuestionnaireValidationError(f"题目 id 重复: {question_id}")
            seen_questions.add(question_id)
            question_type = question.get("type")
            if question_type not in QUESTION_TYPES:
                raise QuestionnaireValidationError(f"{label_prefix}.type 不受支持")
            _require_nonempty_string(question.get("label"), f"{label_prefix}.label")
            if not isinstance(question.get("required"), bool):
                raise QuestionnaireValidationError(f"{label_prefix}.required 必须是布尔值")
            if question_type in PROTECTED_QUESTION_TYPES:
                if question["required"] is not True:
                    raise QuestionnaireValidationError(f"{label_prefix} 受保护题型必须设置为必填")
                if question_type in seen_protected:
                    raise QuestionnaireValidationError(f"受保护题型重复: {question_type}")
                seen_protected.add(question_type)
            if question_type == QUESTION_TYPE_SHORT_TEXT:
                if question.get("options") is not None:
                    raise QuestionnaireValidationError(f"{label_prefix} 单行填空不能包含 options")
                max_length = question.get("maxLength")
                if max_length is not None and (
                    isinstance(max_length, bool) or not isinstance(max_length, int) or max_length <= 0
                ):
                    raise QuestionnaireValidationError(f"{label_prefix}.maxLength 必须是正整数")
            if question_type in ("single_choice", "multiple_choice"):
                options = question.get("options")
                if not isinstance(options, list) or len(options) < 2:
                    raise QuestionnaireValidationError(f"{label_prefix}.options 至少需要两个选项")
                seen_values: set[str] = set()
                for option in options:
                    if not isinstance(option, dict):
                        raise QuestionnaireValidationError(f"{label_prefix}.options 的条目必须是对象")
                    option_value = _require_nonempty_string(option.get("value"), f"{label_prefix}.options[].value")
                    _require_nonempty_string(option.get("label"), f"{label_prefix}.options[].label")
                    if option_value in seen_values:
                        raise QuestionnaireValidationError(f"{label_prefix}.options 的 value 重复: {option_value}")
                    seen_values.add(option_value)
            if question_type == "likert":
                minimum = question.get("min")
                maximum = question.get("max")
                if not isinstance(minimum, int) or not isinstance(maximum, int) or minimum >= maximum:
                    raise QuestionnaireValidationError(f"{label_prefix} 李克特量表需要整数 min < max")
                for label_key in ("minLabel", "maxLabel"):
                    if label_key in question:
                        _require_nonempty_string(question.get(label_key), f"{label_prefix}.{label_key}")
            if question_type == "number":
                minimum = question.get("min")
                maximum = question.get("max")
                if minimum is not None and not isinstance(minimum, (int, float)):
                    raise QuestionnaireValidationError(f"{label_prefix}.min 必须是数字")
                if maximum is not None and not isinstance(maximum, (int, float)):
                    raise QuestionnaireValidationError(f"{label_prefix}.max 必须是数字")
                if minimum is not None and maximum is not None and minimum > maximum:
                    raise QuestionnaireValidationError(f"{label_prefix}.min 不能大于 max")
            help_text = question.get("help")
            if help_text is not None:
                _require_nonempty_string(help_text, f"{label_prefix}.help")
    if require_protected:
        for protected_type in PROTECTED_QUESTION_TYPES:
            if protected_type not in seen_protected:
                raise QuestionnaireValidationError(f"问卷必须包含受保护题型: {protected_type}")


def validate_room_questionnaire_schema(schema: dict) -> None:
    validate_questionnaire_schema(schema, require_protected=True)


def validate_answers(schema: dict, answers: dict, *, enforce_required: bool = True) -> None:
    if not isinstance(answers, dict):
        raise QuestionnaireValidationError("答案必须是对象")
    for page in schema["pages"]:
        for question in page["questions"]:
            question_id = question["id"]
            value = answers.get(question_id)
            question_type = question["type"]
            if enforce_required and question["required"]:
                if value is None or value == "" or value == []:
                    raise QuestionnaireValidationError(f"必填题未作答: {question['label']}")
                if question_type == QUESTION_TYPE_IDENTITY_DOCUMENT and value == {}:
                    raise QuestionnaireValidationError(f"必填题未作答: {question['label']}")
            if value is None:
                continue
            if question_type == "single_choice":
                allowed = {option["value"] for option in question["options"]}
                if value not in allowed:
                    raise QuestionnaireValidationError(f"题目 {question_id} 的选项无效")
            elif question_type == "multiple_choice":
                allowed = {option["value"] for option in question["options"]}
                if not isinstance(value, list) or any(item not in allowed for item in value):
                    raise QuestionnaireValidationError(f"题目 {question_id} 的多选答案无效")
            elif question_type == "likert":
                if not isinstance(value, int) or not question["min"] <= value <= question["max"]:
                    raise QuestionnaireValidationError(f"题目 {question_id} 的评分超出范围")
            elif question_type == "text":
                if not isinstance(value, str):
                    raise QuestionnaireValidationError(f"题目 {question_id} 必须是文本")
            elif question_type == "number":
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise QuestionnaireValidationError(f"题目 {question_id} 必须是数字")
                if question.get("min") is not None and value < question["min"]:
                    raise QuestionnaireValidationError(f"题目 {question_id} 小于最小值")
                if question.get("max") is not None and value > question["max"]:
                    raise QuestionnaireValidationError(f"题目 {question_id} 大于最大值")
            elif question_type == QUESTION_TYPE_SHORT_TEXT:
                _validate_short_text(value, question)
            elif question_type == QUESTION_TYPE_REAL_NAME:
                _validate_real_name(value, f"题目 {question_id}")
            elif question_type == QUESTION_TYPE_ALIPAY_PHONE:
                _validate_alipay_phone(value, f"题目 {question_id}")
            elif question_type == QUESTION_TYPE_IDENTITY_DOCUMENT:
                _validate_identity_document(value, f"题目 {question_id}")
    known_ids = {question["id"] for page in schema["pages"] for question in page["questions"]}
    unknown = set(answers) - known_ids
    if unknown:
        raise QuestionnaireValidationError("答案包含未知题目: " + ", ".join(sorted(unknown)))


def split_protected_answers(
    schema: dict, answers: dict, *, enforce_required: bool
) -> tuple[dict, dict | None]:
    validate_answers(schema, answers, enforce_required=enforce_required)
    protected_by_type: dict[str, dict] = {}
    protected_ids: set[str] = set()
    for page in schema["pages"]:
        for question in page["questions"]:
            if question["type"] in PROTECTED_QUESTION_TYPES:
                protected_by_type[question["type"]] = question
                protected_ids.add(question["id"])
    sanitized = {key: value for key, value in answers.items() if key not in protected_ids}
    missing_types = [item for item in PROTECTED_QUESTION_TYPES if item not in protected_by_type]
    if missing_types:
        if enforce_required:
            raise QuestionnaireValidationError("问卷缺少受保护题型: " + ", ".join(missing_types))
        return sanitized, None
    protected_values: dict[str, Any] = {}
    for question_type in PROTECTED_QUESTION_TYPES:
        question = protected_by_type[question_type]
        value = answers.get(question["id"])
        if value is None or value == "":
            if enforce_required:
                raise QuestionnaireValidationError(f"必填题未作答: {question['label']}")
            return sanitized, None
        protected_values[question_type] = value
    real_name = _validate_real_name(protected_values[QUESTION_TYPE_REAL_NAME], "真实姓名")
    alipay_phone = _validate_alipay_phone(protected_values[QUESTION_TYPE_ALIPAY_PHONE], "支付宝手机号")
    document = _validate_identity_document(
        protected_values[QUESTION_TYPE_IDENTITY_DOCUMENT], "身份证明"
    )
    return sanitized, {
        "real_name": real_name,
        "alipay_phone": alipay_phone,
        "document_type": document["documentType"],
        "document_number": document["number"],
    }


def questionnaire_content_hash(name: str, schema: dict) -> str:
    canonical = {"name": name, "schema": schema}
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def serialize_questionnaire(questionnaire: QuestionnaireVersion) -> dict:
    return {
        "versionId": questionnaire.id,
        "id": questionnaire.id,
        "name": questionnaire.name,
        "version": questionnaire.version,
        "contentHash": questionnaire.content_hash,
        "status": questionnaire.status,
        "publishedAt": isoformat_utc(questionnaire.published_at),
        "createdAt": isoformat_utc(questionnaire.created_at),
        "schema": questionnaire.schema_json,
        "protectedQuestionIds": protected_question_ids(questionnaire.schema_json),
    }


async def next_questionnaire_version(db: AsyncSession, name: str) -> int:
    rows = await db.execute(select(QuestionnaireVersion.version).where(QuestionnaireVersion.name == name))
    versions = rows.scalars().all()
    return max(versions) + 1 if versions else 1


async def create_questionnaire(db: AsyncSession, name: str, schema: dict) -> QuestionnaireVersion:
    validate_questionnaire_schema(schema)
    version = await next_questionnaire_version(db, name)
    questionnaire = QuestionnaireVersion(
        name=name,
        version=version,
        schema_json=schema,
        status=VERSION_DRAFT,
        content_hash=questionnaire_content_hash(name, schema),
    )
    db.add(questionnaire)
    await db.flush()
    return questionnaire


async def update_questionnaire(
    db: AsyncSession, questionnaire: QuestionnaireVersion, patch: dict
) -> QuestionnaireVersion:
    if questionnaire.status != VERSION_DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, "已发布的问卷版本不可修改，请创建新版本")
    name = patch.get("name", questionnaire.name)
    schema = patch.get("schema_json", questionnaire.schema_json)
    validate_questionnaire_schema(schema)
    questionnaire.name = name
    questionnaire.schema_json = schema
    questionnaire.content_hash = questionnaire_content_hash(name, schema)
    await db.flush()
    return questionnaire


async def publish_questionnaire(db: AsyncSession, questionnaire: QuestionnaireVersion) -> QuestionnaireVersion:
    validate_questionnaire_schema(questionnaire.schema_json, require_protected=True)
    rows = await db.execute(
        select(QuestionnaireVersion).where(
            QuestionnaireVersion.name == questionnaire.name,
            QuestionnaireVersion.status == VERSION_PUBLISHED,
            QuestionnaireVersion.id != questionnaire.id,
        )
    )
    for previous in rows.scalars().all():
        previous.status = VERSION_ARCHIVED
    questionnaire.status = VERSION_PUBLISHED
    questionnaire.published_at = utcnow()
    questionnaire.content_hash = questionnaire_content_hash(questionnaire.name, questionnaire.schema_json)
    await db.flush()
    return questionnaire
