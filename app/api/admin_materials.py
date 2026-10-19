from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from ..constants import VERSION_DRAFT
from ..models import InstructionVersion, QuestionnaireVersion
from ..schemas import (
    InstructionVersionCreate,
    InstructionVersionPatch,
    MapGroupCreate,
    MapGroupPatch,
    QuestionnaireVersionCreate,
    QuestionnaireVersionPatch,
    TroopProfileCopy,
    TroopProfileCreate,
    TroopProfilePatch,
)
from ..services.instructions import (
    create_instruction,
    publish_instruction,
    serialize_instruction,
    update_instruction,
)
from ..services.map_groups import (
    MapGroupValidationError,
    create_map_group,
    get_map_group_version,
    list_map_groups,
    publish_map_group,
    serialize_map_group_version,
    update_map_group,
)
from ..services.questionnaires import (
    QuestionnaireValidationError,
    create_questionnaire,
    publish_questionnaire,
    serialize_questionnaire,
    update_questionnaire,
)
from ..services.troop_profiles import (
    TroopProfileValidationError,
    copy_troop_profile,
    create_troop_profile,
    get_troop_profile_version,
    list_troop_profiles,
    publish_troop_profile,
    serialize_troop_profile_version,
    update_troop_profile,
)
from .admin_common import audit
from .deps import AdminDep, DbSession, require_csrf

router = APIRouter()


@router.get("/troop-profiles")
async def get_troop_profiles(admin: AdminDep, db: DbSession):
    return {"profiles": await list_troop_profiles(db)}


@router.post("/troop-profiles", dependencies=[Depends(require_csrf)])
async def post_troop_profile(payload: TroopProfileCreate, admin: AdminDep, db: DbSession):
    try:
        version = await create_troop_profile(db, payload.name, payload.rows)
    except TroopProfileValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit(db, admin, "troop_profile_created", "troop_profile_version", version.id)
    await db.commit()
    return {"troopProfile": serialize_troop_profile_version(version)}


@router.get("/troop-profiles/{version_id}")
async def get_troop_profile(version_id: str, admin: AdminDep, db: DbSession):
    version = await get_troop_profile_version(db, version_id)
    return {"troopProfile": serialize_troop_profile_version(version)}


@router.patch("/troop-profiles/{version_id}", dependencies=[Depends(require_csrf)])
async def patch_troop_profile(
    version_id: str, payload: TroopProfilePatch, admin: AdminDep, db: DbSession
):
    version = await get_troop_profile_version(db, version_id)
    if payload.rows is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "必须提供兵力配置行")
    try:
        version = await update_troop_profile(db, version, payload.rows)
    except TroopProfileValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit(db, admin, "troop_profile_updated", "troop_profile_version", version.id)
    await db.commit()
    return {"troopProfile": serialize_troop_profile_version(version)}


@router.post("/troop-profiles/{version_id}/publish", dependencies=[Depends(require_csrf)])
async def post_publish_troop_profile(version_id: str, admin: AdminDep, db: DbSession):
    version = await get_troop_profile_version(db, version_id)
    try:
        version = await publish_troop_profile(db, version)
    except TroopProfileValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit(db, admin, "troop_profile_published", "troop_profile_version", version.id)
    await db.commit()
    return {"troopProfile": serialize_troop_profile_version(version)}


@router.post("/troop-profiles/{version_id}/copy", dependencies=[Depends(require_csrf)])
async def post_copy_troop_profile(
    version_id: str, payload: TroopProfileCopy, admin: AdminDep, db: DbSession
):
    version = await get_troop_profile_version(db, version_id)
    try:
        copied = await copy_troop_profile(db, version, payload.name)
    except TroopProfileValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit(
        db,
        admin,
        "troop_profile_copied",
        "troop_profile_version",
        copied.id,
        {"sourceVersionId": version.id},
    )
    await db.commit()
    return {"troopProfile": serialize_troop_profile_version(copied)}


@router.get("/map-groups")
async def get_map_groups(admin: AdminDep, db: DbSession):
    return {"mapGroups": await list_map_groups(db)}


@router.get("/map-groups/{version_id}")
async def get_map_group(version_id: str, admin: AdminDep, db: DbSession):
    version = await get_map_group_version(db, version_id)
    return {"mapGroup": serialize_map_group_version(version)}


@router.post("/map-groups", dependencies=[Depends(require_csrf)])
async def post_map_group(payload: MapGroupCreate, admin: AdminDep, db: DbSession):
    try:
        version = await create_map_group(db, payload.model_dump())
    except MapGroupValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit(db, admin, "map_group_created", "map_group_version", version.id)
    await db.commit()
    return {"mapGroup": serialize_map_group_version(version)}


@router.patch("/map-groups/{version_id}", dependencies=[Depends(require_csrf)])
async def patch_map_group(
    version_id: str, payload: MapGroupPatch, admin: AdminDep, db: DbSession
):
    version = await get_map_group_version(db, version_id)
    try:
        version = await update_map_group(db, version, payload.model_dump(exclude_unset=True))
    except MapGroupValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit(db, admin, "map_group_updated", "map_group_version", version.id)
    await db.commit()
    return {"mapGroup": serialize_map_group_version(version)}


@router.post("/map-groups/{version_id}/publish", dependencies=[Depends(require_csrf)])
async def post_publish_map_group(version_id: str, admin: AdminDep, db: DbSession):
    version = await get_map_group_version(db, version_id)
    try:
        version = await publish_map_group(db, version)
    except MapGroupValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit(db, admin, "map_group_published", "map_group_version", version.id)
    await db.commit()
    return {"mapGroup": serialize_map_group_version(version)}


@router.get("/instructions")
async def list_instructions(admin: AdminDep, db: DbSession):
    rows = await db.execute(
        select(InstructionVersion).order_by(InstructionVersion.name, InstructionVersion.version.desc())
    )
    return {"instructions": [serialize_instruction(row) for row in rows.scalars().all()]}


async def _get_instruction(db, instruction_id: str) -> InstructionVersion:
    row = await db.get(InstructionVersion, instruction_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "指导语版本不存在")
    return row


@router.get("/instructions/{instruction_id}")
async def get_instruction(instruction_id: str, admin: AdminDep, db: DbSession):
    return {"instruction": serialize_instruction(await _get_instruction(db, instruction_id))}


@router.post("/instructions", dependencies=[Depends(require_csrf)])
async def post_instruction(payload: InstructionVersionCreate, admin: AdminDep, db: DbSession):
    try:
        instruction = await create_instruction(db, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit(db, admin, "instruction_created", "instruction_version", instruction.id)
    await db.commit()
    return {"instruction": serialize_instruction(instruction)}


@router.patch("/instructions/{instruction_id}", dependencies=[Depends(require_csrf)])
async def patch_instruction(
    instruction_id: str, payload: InstructionVersionPatch, admin: AdminDep, db: DbSession
):
    instruction = await _get_instruction(db, instruction_id)
    try:
        instruction = await update_instruction(db, instruction, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit(db, admin, "instruction_updated", "instruction_version", instruction.id)
    await db.commit()
    return {"instruction": serialize_instruction(instruction)}


@router.post("/instructions/{instruction_id}/publish", dependencies=[Depends(require_csrf)])
async def post_publish_instruction(instruction_id: str, admin: AdminDep, db: DbSession):
    instruction = await _get_instruction(db, instruction_id)
    if instruction.status != VERSION_DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, "只有草稿版本可以发布")
    try:
        instruction = await publish_instruction(db, instruction)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit(db, admin, "instruction_published", "instruction_version", instruction.id)
    await db.commit()
    return {"instruction": serialize_instruction(instruction)}


@router.get("/questionnaires")
async def list_questionnaires(admin: AdminDep, db: DbSession):
    rows = await db.execute(
        select(QuestionnaireVersion).order_by(QuestionnaireVersion.name, QuestionnaireVersion.version.desc())
    )
    return {"questionnaires": [serialize_questionnaire(row) for row in rows.scalars().all()]}


async def _get_questionnaire(db, questionnaire_id: str) -> QuestionnaireVersion:
    row = await db.get(QuestionnaireVersion, questionnaire_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "问卷版本不存在")
    return row


@router.get("/questionnaires/{questionnaire_id}")
async def get_questionnaire(questionnaire_id: str, admin: AdminDep, db: DbSession):
    return {"questionnaire": serialize_questionnaire(await _get_questionnaire(db, questionnaire_id))}


@router.post("/questionnaires", dependencies=[Depends(require_csrf)])
async def post_questionnaire(payload: QuestionnaireVersionCreate, admin: AdminDep, db: DbSession):
    try:
        questionnaire = await create_questionnaire(db, payload.name, payload.definition)
    except QuestionnaireValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit(db, admin, "questionnaire_created", "questionnaire_version", questionnaire.id)
    await db.commit()
    return {"questionnaire": serialize_questionnaire(questionnaire)}


@router.patch("/questionnaires/{questionnaire_id}", dependencies=[Depends(require_csrf)])
async def patch_questionnaire(
    questionnaire_id: str, payload: QuestionnaireVersionPatch, admin: AdminDep, db: DbSession
):
    questionnaire = await _get_questionnaire(db, questionnaire_id)
    patch = payload.model_dump(exclude_unset=True)
    if "definition" in patch:
        patch["schema_json"] = patch.pop("definition")
    try:
        questionnaire = await update_questionnaire(db, questionnaire, patch)
    except QuestionnaireValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit(db, admin, "questionnaire_updated", "questionnaire_version", questionnaire.id)
    await db.commit()
    return {"questionnaire": serialize_questionnaire(questionnaire)}


@router.post("/questionnaires/{questionnaire_id}/publish", dependencies=[Depends(require_csrf)])
async def post_publish_questionnaire(questionnaire_id: str, admin: AdminDep, db: DbSession):
    questionnaire = await _get_questionnaire(db, questionnaire_id)
    if questionnaire.status != VERSION_DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, "只有草稿版本可以发布")
    try:
        questionnaire = await publish_questionnaire(db, questionnaire)
    except QuestionnaireValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit(db, admin, "questionnaire_published", "questionnaire_version", questionnaire.id)
    await db.commit()
    return {"questionnaire": serialize_questionnaire(questionnaire)}
