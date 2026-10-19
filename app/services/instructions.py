import hashlib
import json
import re

import nh3
from fastapi import HTTPException, status
from markdown_it import MarkdownIt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import VERSION_ARCHIVED, VERSION_DRAFT, VERSION_PUBLISHED
from ..models import InstructionVersion, MapGroupVersion, MediaAsset
from ..timeutil import isoformat_utc, utcnow

_MARKDOWN = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table").enable("strikethrough")
_ASSET_REF = re.compile(r"asset://([0-9a-fA-F-]{36})")
_ALLOWED_TAGS = {
    "p", "br", "strong", "em", "del", "blockquote", "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "code", "pre", "hr", "table", "thead", "tbody", "tr", "th", "td", "img", "a", "span", "div",
}
_ALLOWED_ATTRIBUTES = {
    "img": {"src", "alt", "title", "width", "height"},
    "a": {"href", "title"},
    "th": {"align"},
    "td": {"align"},
}


def instruction_name(map_group_prefix: str, role: int) -> str:
    if role not in (1, 2):
        raise ValueError("role 必须是 1 或 2")
    return f"{map_group_prefix}-{'A' if role == 1 else 'B'}"


def validate_instruction(markdown: str, role: int, min_reading_seconds: int) -> None:
    if role not in (1, 2):
        raise ValueError("role 必须是 1 或 2")
    if not markdown.strip():
        raise ValueError("指导语正文不能为空")
    if min_reading_seconds < 0:
        raise ValueError("最短阅读时间不能为负")


async def validate_instruction_assets(db: AsyncSession, markdown: str) -> None:
    asset_ids = set(_ASSET_REF.findall(markdown))
    if not asset_ids:
        return
    rows = await db.execute(select(MediaAsset).where(MediaAsset.id.in_(asset_ids)))
    found = {asset.id: asset for asset in rows.scalars().all()}
    missing = asset_ids - set(found)
    if missing:
        raise ValueError("指导语引用了不存在的图片资产: " + ", ".join(sorted(missing)))
    for asset in found.values():
        if not asset.content_type.startswith("image/"):
            raise ValueError("指导语只能引用图片资产")


def render_markdown(markdown: str) -> str:
    html = _MARKDOWN.render(markdown)
    html = _ASSET_REF.sub(lambda match: f"/media/{match.group(1)}", html)
    cleaned = nh3.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        link_rel="noopener noreferrer",
        url_schemes={"http", "https", "mailto"},
    )
    return cleaned


def instruction_content_hash(payload: dict) -> str:
    canonical = {
        "name": payload["name"],
        "mapGroupPrefix": payload["map_group_prefix"],
        "role": payload["role"],
        "markdown": payload["markdown"],
        "minReadingSeconds": payload["min_reading_seconds"],
    }
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def serialize_instruction(instruction: InstructionVersion, include_html: bool = True) -> dict:
    data = {
        "versionId": instruction.id,
        "id": instruction.id,
        "name": instruction.name,
        "mapGroupPrefix": instruction.map_group_prefix,
        "version": instruction.version,
        "role": instruction.role,
        "minReadingSeconds": instruction.min_reading_seconds,
        "contentMarkdown": instruction.markdown,
        "contentHash": instruction.content_hash,
        "status": instruction.status,
        "publishedAt": isoformat_utc(instruction.published_at),
        "createdAt": isoformat_utc(instruction.created_at),
    }
    if include_html:
        data["contentHtml"] = render_markdown(instruction.markdown)
    return data


async def next_instruction_version(db: AsyncSession, name: str) -> int:
    rows = await db.execute(select(InstructionVersion.version).where(InstructionVersion.name == name))
    versions = rows.scalars().all()
    return max(versions) + 1 if versions else 1


async def _map_group_for_instruction(db: AsyncSession, map_group_version_id: str) -> MapGroupVersion:
    map_group = await db.get(MapGroupVersion, map_group_version_id)
    if map_group is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "地图组版本不存在")
    if map_group.status not in (VERSION_PUBLISHED, VERSION_ARCHIVED):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "地图组版本尚未发布")
    return map_group


async def create_instruction(db: AsyncSession, data: dict) -> InstructionVersion:
    role = data["role"]
    markdown = data["markdown"]
    min_reading_seconds = data["min_reading_seconds"]
    validate_instruction(markdown, role, min_reading_seconds)
    await validate_instruction_assets(db, markdown)
    map_group = await _map_group_for_instruction(db, data["map_group_version_id"])
    name = instruction_name(map_group.name, role)
    payload = {
        "name": name,
        "map_group_prefix": map_group.name,
        "role": role,
        "markdown": markdown,
        "min_reading_seconds": min_reading_seconds,
    }
    instruction = InstructionVersion(
        name=name,
        map_group_prefix=map_group.name,
        version=await next_instruction_version(db, name),
        role=role,
        markdown=markdown,
        min_reading_seconds=min_reading_seconds,
        status=VERSION_DRAFT,
        content_hash=instruction_content_hash(payload),
    )
    db.add(instruction)
    await db.flush()
    return instruction


async def update_instruction(db: AsyncSession, instruction: InstructionVersion, patch: dict) -> InstructionVersion:
    if instruction.status != VERSION_DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, "已发布的指导语版本不可修改，请创建新版本")
    markdown = patch.get("markdown", instruction.markdown)
    min_reading_seconds = patch.get("min_reading_seconds", instruction.min_reading_seconds)
    validate_instruction(markdown, instruction.role, min_reading_seconds)
    await validate_instruction_assets(db, markdown)
    instruction.markdown = markdown
    instruction.min_reading_seconds = min_reading_seconds
    instruction.content_hash = instruction_content_hash(
        {
            "name": instruction.name,
            "map_group_prefix": instruction.map_group_prefix,
            "role": instruction.role,
            "markdown": markdown,
            "min_reading_seconds": min_reading_seconds,
        }
    )
    await db.flush()
    return instruction


async def publish_instruction(db: AsyncSession, instruction: InstructionVersion) -> InstructionVersion:
    validate_instruction(instruction.markdown, instruction.role, instruction.min_reading_seconds)
    await validate_instruction_assets(db, instruction.markdown)
    rows = await db.execute(
        select(InstructionVersion).where(
            InstructionVersion.name == instruction.name,
            InstructionVersion.status == VERSION_PUBLISHED,
            InstructionVersion.id != instruction.id,
        )
    )
    for previous in rows.scalars().all():
        previous.status = VERSION_ARCHIVED
    instruction.status = VERSION_PUBLISHED
    instruction.published_at = utcnow()
    instruction.content_hash = instruction_content_hash(
        {
            "name": instruction.name,
            "map_group_prefix": instruction.map_group_prefix,
            "role": instruction.role,
            "markdown": instruction.markdown,
            "min_reading_seconds": instruction.min_reading_seconds,
        }
    )
    await db.flush()
    return instruction
