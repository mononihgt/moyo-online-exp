import hashlib
import io
from pathlib import Path

from fastapi import HTTPException, status
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from ..config import get_settings
from ..models import MediaAsset

_FORMAT_INFO = {
    "PNG": (".png", "image/png"),
    "JPEG": (".jpg", "image/jpeg"),
    "WEBP": (".webp", "image/webp"),
    "GIF": (".gif", "image/gif"),
}


def _sanitize_filename(filename: str) -> str:
    base = Path(filename or "image").name
    cleaned = "".join(char for char in base if char.isalnum() or char in ".-_ ").strip()
    return cleaned[:200] or "image"


def _process_image(data: bytes) -> tuple[bytes, str, str, int, int]:
    settings = get_settings()
    try:
        with Image.open(io.BytesIO(data)) as probe:
            source_format = probe.format
            width, height = probe.size
            if source_format != "GIF":
                probe.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "文件不是有效图片") from exc
    if source_format not in _FORMAT_INFO:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "仅接受 PNG、JPEG、WebP、GIF 图片")
    if width <= 0 or height <= 0 or width * height > settings.max_image_pixels:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片像素尺寸超出限制")
    if source_format == "GIF":
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.load()
        except (UnidentifiedImageError, OSError) as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "文件不是有效图片") from exc
        extension, content_type = _FORMAT_INFO[source_format]
        return data, extension, content_type, width, height
    with Image.open(io.BytesIO(data)) as image:
        image = ImageOps.exif_transpose(image)
        width, height = image.size
        if image.mode not in ("RGB", "RGBA", "L"):
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        clean = Image.new(image.mode, image.size)
        clean.paste(image)
        output = io.BytesIO()
        save_kwargs = {}
        if source_format == "JPEG":
            if clean.mode != "RGB":
                clean = clean.convert("RGB")
            save_kwargs = {"quality": 92, "optimize": True}
        elif source_format == "WEBP":
            save_kwargs = {"quality": 92, "method": 4}
        else:
            save_kwargs = {"optimize": True}
        clean.save(output, format=source_format, **save_kwargs)
        extension, content_type = _FORMAT_INFO[source_format]
        return output.getvalue(), extension, content_type, width, height


async def save_image(db: AsyncSession, data: bytes, filename: str, kind: str) -> MediaAsset:
    settings = get_settings()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "上传文件为空")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "图片超过大小限制")
    processed, extension, content_type, width, height = await run_in_threadpool(_process_image, data)
    digest = hashlib.sha256(processed).hexdigest()
    existing = await db.execute(select(MediaAsset).where(MediaAsset.sha256 == digest))
    asset = existing.scalars().first()
    if asset is not None:
        return asset
    relative_path = f"{digest[:2]}/{digest}{extension}"
    absolute_path = Path(settings.media_dir) / relative_path
    await run_in_threadpool(absolute_path.parent.mkdir, parents=True, exist_ok=True)
    await run_in_threadpool(absolute_path.write_bytes, processed)
    asset = MediaAsset(
        kind=kind,
        filename=_sanitize_filename(filename),
        content_type=content_type,
        storage_path=relative_path,
        sha256=digest,
        size_bytes=len(processed),
        width=width,
        height=height,
    )
    db.add(asset)
    await db.flush()
    return asset


def media_absolute_path(asset: MediaAsset) -> Path:
    return Path(get_settings().media_dir) / asset.storage_path


def serialize_media(asset: MediaAsset) -> dict:
    return {
        "assetId": asset.id,
        "id": asset.id,
        "kind": asset.kind,
        "filename": asset.filename,
        "contentType": asset.content_type,
        "sha256": "sha256:" + asset.sha256,
        "sizeBytes": asset.size_bytes,
        "width": asset.width,
        "height": asset.height,
        "url": f"/media/{asset.id}",
    }
