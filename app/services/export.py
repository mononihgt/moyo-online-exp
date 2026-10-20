import csv
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import BOOKING_CANCELED, SCHEMA_VERSION, TIMEZONE
from ..models import (
    Booking,
    GameTrial,
    InstructionVersion,
    MapGroupVersion,
    MediaAsset,
    Payment,
    QuestionnaireResponse,
    QuestionnaireVersion,
    Room,
    RoomConfigRevision,
    RoomEvent,
    RoomParticipant,
    Turn,
)
from ..timeutil import isoformat_utc, utcnow
from .map_groups import serialize_map_group_snapshot
from .media import media_absolute_path
from .payments import serialize_payment
from .questionnaires import protected_question_ids, serialize_questionnaire

_ASSET_REF = re.compile(r"asset://([0-9a-fA-F-]{36})")
_SENSITIVE_PAYLOAD_KEYS = {
    "name",
    "realName",
    "phone",
    "phoneHash",
    "phoneEncrypted",
    "alipayPhone",
    "alipayPhoneEncrypted",
    "documentNumber",
    "documentNumberEncrypted",
    "identityDocument",
    "realNameEncrypted",
    "token",
    "jatosToken",
    "password",
    "cookie",
    "session",
}


def _sanitize_event_payload(payload: dict, analysis_codes: dict[str, str]) -> dict:
    def clean(value):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if key in _SENSITIVE_PAYLOAD_KEYS:
                    continue
                if key == "participantId":
                    code = analysis_codes.get(item)
                    if code is not None:
                        result["analysisCode"] = code
                    continue
                if key == "participant_id":
                    code = analysis_codes.get(item)
                    if code is not None:
                        result["analysisCode"] = code
                    continue
                result[key] = clean(item)
            return result
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    return clean(payload)


def _csv_bytes(header: list[str], rows: list[list]) -> bytes:
    buffer = io.StringIO()
    buffer.write("﻿")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([_csv_cell(value) for value in row])
    return buffer.getvalue().encode("utf-8")


def _csv_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _turn_payload(turn: Turn) -> dict:
    return {
        "round": turn.round,
        "selections": turn.selections_json,
        "selectionSources": turn.selection_sources_json,
        "autoSelected": turn.auto_selected_json,
        "soldierPolicies": turn.policy_json,
        "warLocation": turn.war_json.get("location", []),
        "warLost": turn.losses_json,
        "logistics": turn.logistics_json,
        "numOfWar": turn.num_of_war,
        "turnSeed": turn.turn_seed,
        "board": turn.board_json,
        "forced": turn.forced,
        "recordedAt": isoformat_utc(turn.created_at),
    }


def _trial_params(raw: dict | None) -> dict:
    data = raw if isinstance(raw, dict) else {}
    return {"soldiersA": data.get("soldiersA"), "soldiersB": data.get("soldiersB")}


def _trial_plan_payload(plan: dict | None) -> dict:
    if not isinstance(plan, dict) or not plan:
        return {}
    order = []
    for position, item in enumerate(plan.get("order") or []):
        if isinstance(item, dict):
            entry = {
                "trialIndex": item.get("trialIndex", item.get("trial_index", position)),
                "sourceIndex": item.get("sourceIndex", item.get("source_index")),
            }
            if "isPractice" in item:
                entry["isPractice"] = item["isPractice"]
            if "formalTrial" in item:
                entry["formalTrial"] = item["formalTrial"]
            if "params" in item:
                entry["params"] = _trial_params(item["params"])
            order.append(entry)
        else:
            order.append({"trialIndex": position, "sourceIndex": item})
    return {
        "seed": plan.get("seed"),
        "order": order,
        "generatedAt": plan.get("generatedAt"),
    }


async def _room_instructions(db: AsyncSession, room: Room) -> dict:
    if room.config_snapshot:
        instructions = room.config_snapshot.get("instructions", {})
        return {
            role: {
                "versionId": data.get("versionId") or data.get("id"),
                "name": data.get("name"),
                "mapGroupPrefix": data.get("mapGroupPrefix"),
                "role": data.get("role"),
                "minReadingSeconds": data.get("minReadingSeconds"),
                "contentMarkdown": data.get("contentMarkdown"),
                "contentHash": data.get("contentHash"),
                "publishedAt": data.get("publishedAt"),
            }
            for role, data in instructions.items()
        }
    versions = {
        1: await db.get(InstructionVersion, room.instruction_version_p1_id),
        2: await db.get(InstructionVersion, room.instruction_version_p2_id),
    }
    return {
        f"player{role}": {
            "versionId": version.id,
            "name": version.name,
            "mapGroupPrefix": version.map_group_prefix,
            "role": version.role,
            "minReadingSeconds": version.min_reading_seconds,
            "contentMarkdown": version.markdown,
            "contentHash": version.content_hash,
            "publishedAt": isoformat_utc(version.published_at),
        }
        for role, version in versions.items()
    }


async def _room_questionnaire(db: AsyncSession, room: Room) -> dict:
    if room.config_snapshot and room.config_snapshot.get("questionnaire"):
        data = room.config_snapshot["questionnaire"]
        schema = data.get("schema")
        protected = data.get("protectedQuestionIds")
        if protected is None and isinstance(schema, dict):
            protected = protected_question_ids(schema)
        return {
            "versionId": data.get("versionId") or data.get("id"),
            "name": data.get("name"),
            "version": data.get("version"),
            "contentHash": data.get("contentHash"),
            "publishedAt": data.get("publishedAt"),
            "schema": schema,
            "protectedQuestionIds": protected or [],
        }
    version = await db.get(QuestionnaireVersion, room.questionnaire_version_id)
    data = serialize_questionnaire(version)
    return {
        "versionId": data["versionId"],
        "name": data["name"],
        "version": data["version"],
        "contentHash": data["contentHash"],
        "publishedAt": data["publishedAt"],
        "schema": data["schema"],
        "protectedQuestionIds": data["protectedQuestionIds"],
    }


async def _room_map_group(db: AsyncSession, room: Room) -> dict:
    if room.config_snapshot and room.config_snapshot.get("mapGroup"):
        return room.config_snapshot["mapGroup"]
    map_group = await db.get(MapGroupVersion, room.map_group_version_id)
    return serialize_map_group_snapshot(map_group)


async def build_archive_snapshot(db: AsyncSession, room: Room) -> dict:
    map_group = await _room_map_group(db, room)
    instructions = await _room_instructions(db, room)
    questionnaire = await _room_questionnaire(db, room)
    assets, media_entries = await _collect_media(db, map_group, instructions)
    for asset in assets:
        if not media_absolute_path(asset).exists():
            raise RuntimeError(f"归档快照引用的媒体文件缺失: {asset.id}")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "createdAt": isoformat_utc(room.archived_at or utcnow()),
        "room": {
            "id": room.id,
            "startsAt": isoformat_utc(room.starts_at),
            "archivedAt": isoformat_utc(room.archived_at),
            "archiveReason": room.archive_reason,
            "mapGroupVersionId": room.map_group_version_id,
            "instructionVersionP1Id": room.instruction_version_p1_id,
            "instructionVersionP2Id": room.instruction_version_p2_id,
            "questionnaireVersionId": room.questionnaire_version_id,
            "waitWindowSeconds": room.wait_window_seconds,
            "reconnectWindowSeconds": room.reconnect_window_seconds,
            "configLockedAt": isoformat_utc(room.config_locked_at),
        },
        "mapGroup": map_group,
        "instructions": instructions,
        "questionnaire": questionnaire,
        "media": media_entries,
    }


async def build_room_export(db: AsyncSession, room: Room) -> dict:
    snapshot = room.archive_snapshot_json if isinstance(room.archive_snapshot_json, dict) else {}
    map_group = snapshot.get("mapGroup") or await _room_map_group(db, room)
    instructions = snapshot.get("instructions") or await _room_instructions(db, room)
    questionnaire = snapshot.get("questionnaire") or await _room_questionnaire(db, room)
    protected_ids = set(questionnaire.get("protectedQuestionIds") or [])
    media_entries = snapshot.get("media")
    revisions_query = await db.execute(
        select(RoomConfigRevision)
        .where(RoomConfigRevision.room_id == room.id)
        .order_by(RoomConfigRevision.revision)
    )
    revisions = [
        {"revision": row.revision, "createdAt": isoformat_utc(row.created_at), "config": row.config_json}
        for row in revisions_query.scalars().all()
    ]
    room_payload = {
        "id": room.id,
        "internalLabel": room.internal_label,
        "startsAt": isoformat_utc(room.starts_at),
        "publishedAt": isoformat_utc(room.published_at),
        "archivedAt": isoformat_utc(room.archived_at),
        "status": room.status,
        "archiveReason": room.archive_reason,
        "timezone": TIMEZONE,
        "waitWindowSeconds": room.wait_window_seconds,
        "reconnectWindowSeconds": room.reconnect_window_seconds,
        "configLockedAt": isoformat_utc(room.config_locked_at),
        "archiveSnapshotAt": snapshot.get("createdAt"),
        "mapGroupVersionId": room.map_group_version_id,
        "configRevisions": revisions,
    }

    bookings_query = await db.execute(
        select(Booking)
        .where(Booking.room_id == room.id)
        .order_by(Booking.created_at, Booking.id)
    )
    bookings: dict[str, Booking] = {}
    for booking in bookings_query.scalars().all():
        existing = bookings.get(booking.participant_id)
        if existing is None or (
            existing.status == BOOKING_CANCELED and booking.status != BOOKING_CANCELED
        ):
            bookings[booking.participant_id] = booking
    rows_query = await db.execute(
        select(RoomParticipant).where(RoomParticipant.room_id == room.id).order_by(RoomParticipant.role)
    )
    room_participants = list(rows_query.scalars().all())
    participant_ids = {row.participant_id for row in room_participants} | set(bookings)
    responses_query = await db.execute(
        select(QuestionnaireResponse)
        .where(QuestionnaireResponse.room_id == room.id)
        .order_by(QuestionnaireResponse.completed_at)
    )
    responses_by_participant: dict[str, list[QuestionnaireResponse]] = {}
    for response in responses_query.scalars().all():
        responses_by_participant.setdefault(response.participant_id, []).append(response)
    analysis_codes = {row.participant_id: row.analysis_code for row in room_participants}

    def _sanitized_answers(response: QuestionnaireResponse | None) -> dict | None:
        if response is None or not isinstance(response.answers_json, dict):
            return None
        return {key: value for key, value in response.answers_json.items() if key not in protected_ids}

    participant_payloads = []
    for participant_id in sorted(participant_ids):
        row = next((item for item in room_participants if item.participant_id == participant_id), None)
        booking = bookings.get(participant_id)
        responses = responses_by_participant.get(participant_id, [])
        canonical = next((response for response in responses if response.canonical), None)
        instruction_payload = None
        if row is not None:
            instruction = instructions.get(f"player{row.role}") or {}
            instruction_payload = {
                "versionId": instruction.get("versionId"),
                "startedAt": isoformat_utc(row.instruction_started_at),
                "completedAt": isoformat_utc(row.instruction_completed_at),
                "minReadingSeconds": instruction.get("minReadingSeconds"),
                "connectedSeconds": row.instruction_connected_seconds,
            }
        questionnaire_payload = None
        if row is not None:
            questionnaire_payload = {
                "status": row.questionnaire_status,
                "startedAt": isoformat_utc(row.questionnaire_started_at),
                "completedAt": isoformat_utc(row.completed_at),
                "jatosWorkerId": canonical.jatos_worker_id if canonical else None,
                "jatosStudyResultId": canonical.jatos_study_result_id if canonical else None,
                "jatosComponentResultId": canonical.jatos_component_result_id if canonical else None,
                "attempts": [
                    {
                        "jatosWorkerId": response.jatos_worker_id,
                        "jatosStudyResultId": response.jatos_study_result_id,
                        "jatosComponentResultId": response.jatos_component_result_id,
                        "submittedAt": isoformat_utc(response.completed_at),
                        "canonical": response.canonical,
                    }
                    for response in responses
                ],
                "answers": _sanitized_answers(canonical),
            }
        participant_payloads.append(
            {
                "analysisCode": analysis_codes.get(participant_id),
                "role": row.role if row else None,
                "bookingStatus": booking.status if booking else None,
                "attendedAt": isoformat_utc(booking.attended_at) if booking else None,
                "instruction": instruction_payload,
                "questionnaire": questionnaire_payload,
                "completedAt": isoformat_utc(row.completed_at) if row else None,
            }
        )

    trials_query = await db.execute(
        select(GameTrial).where(GameTrial.room_id == room.id).order_by(GameTrial.trial_index)
    )
    trials = list(trials_query.scalars().all())
    trial_payloads = []
    for trial in trials:
        turns_query = await db.execute(
            select(Turn).where(Turn.game_trial_id == trial.id).order_by(Turn.round)
        )
        turns = [_turn_payload(turn) for turn in turns_query.scalars().all()]
        trial_payloads.append(
            {
                "trialIndex": trial.trial_index,
                "gameNumber": trial.game_number,
                "sourceIndex": trial.source_index,
                "isPractice": trial.is_practice,
                "formalTrial": trial.formal_trial,
                "params": _trial_params(trial.params_json),
                "seed": trial.seed,
                "startedAt": isoformat_utc(trial.started_at),
                "endedAt": isoformat_utc(trial.ended_at),
                "winner": trial.winner,
                "endReason": trial.end_reason,
                "endTurn": trial.end_turn,
                "completedRounds": trial.completed_rounds,
                "forcedRounds": trial.forced_rounds,
                "initialState": trial.initial_state_json,
                "turns": turns,
                "summary": trial.summary_json,
            }
        )

    events_query = await db.execute(
        select(RoomEvent).where(RoomEvent.room_id == room.id).order_by(RoomEvent.created_at)
    )
    events = []
    for event in events_query.scalars().all():
        code = None
        if event.participant_id is not None:
            code = analysis_codes.get(event.participant_id)
            if code is None:
                participant_row = next(
                    (row for row in room_participants if row.participant_id == event.participant_id), None
                )
                code = participant_row.analysis_code if participant_row else None
        events.append(
            {
                "type": event.type,
                "analysisCode": code,
                "createdAt": isoformat_utc(event.created_at),
                "payload": _sanitize_event_payload(event.payload_json or {}, analysis_codes),
            }
        )

    payments_query = await db.execute(select(Payment).where(Payment.room_id == room.id))
    payments = []
    for payment in payments_query.scalars().all():
        data = serialize_payment(payment, analysis_codes.get(payment.participant_id))
        data.pop("id", None)
        data.pop("roomId", None)
        data.pop("source", None)
        payments.append(data)

    if media_entries is None:
        _media_assets, media_entries = await _collect_media(db, map_group, instructions)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "exportedAt": isoformat_utc(utcnow()),
        "room": room_payload,
        "mapGroup": map_group,
        "instructions": instructions,
        "questionnaire": questionnaire,
        "participants": participant_payloads,
        "trialPlan": _trial_plan_payload(room.trial_plan_json),
        "trials": trial_payloads,
        "events": events,
        "payments": payments,
        "media": media_entries,
    }


async def _collect_media(db: AsyncSession, map_group: dict, instructions: dict) -> tuple[list[MediaAsset], list[dict]]:
    asset_ids: set[str] = set()
    for item in map_group.get("maps", []):
        for cell in item.get("cells") or []:
            if cell:
                asset_ids.add(cell)
    for instruction in instructions.values():
        asset_ids.update(_ASSET_REF.findall(instruction.get("contentMarkdown") or ""))
    if not asset_ids:
        return [], []
    rows = await db.execute(select(MediaAsset).where(MediaAsset.id.in_(asset_ids)))
    assets = sorted(rows.scalars().all(), key=lambda item: item.id)
    if len(assets) != len(asset_ids):
        missing = asset_ids - {asset.id for asset in assets}
        raise RuntimeError("导出引用了不存在的媒体资产: " + ", ".join(sorted(missing)))
    entries = []
    for asset in assets:
        extension = Path(asset.storage_path).suffix
        entries.append(
            {
                "assetId": asset.id,
                "filename": asset.filename,
                "contentType": asset.content_type,
                "sha256": "sha256:" + asset.sha256,
                "sizeBytes": asset.size_bytes,
                "width": asset.width,
                "height": asset.height,
                "path": f"media/{asset.id}{extension}",
            }
        )
    return assets, entries


async def _assets_for_media_entries(
    db: AsyncSession, entries: list[dict]
) -> tuple[list[MediaAsset], list[dict]]:
    if not entries:
        return [], []
    asset_ids = [entry["assetId"] for entry in entries]
    rows = await db.execute(select(MediaAsset).where(MediaAsset.id.in_(asset_ids)))
    by_id = {asset.id: asset for asset in rows.scalars().all()}
    missing = [asset_id for asset_id in asset_ids if asset_id not in by_id]
    if missing:
        raise RuntimeError("导出引用了不存在的媒体资产: " + ", ".join(sorted(missing)))
    assets = []
    for entry in entries:
        asset = by_id[entry["assetId"]]
        if "sha256:" + asset.sha256 != entry.get("sha256"):
            raise RuntimeError(f"媒体快照哈希不匹配: {asset.id}")
        assets.append(asset)
    return assets, entries


async def build_analysis_zip(db: AsyncSession, room: Room) -> bytes:
    export = await build_room_export(db, room)
    assets, media_entries = await _assets_for_media_entries(db, export.get("media") or [])
    participants_rows = []
    for participant in export["participants"]:
        instruction = participant.get("instruction") or {}
        questionnaire = participant.get("questionnaire") or {}
        participants_rows.append(
            [
                participant.get("analysisCode"),
                participant.get("role"),
                participant.get("bookingStatus"),
                participant.get("attendedAt"),
                instruction.get("completedAt"),
                questionnaire.get("status"),
                questionnaire.get("completedAt"),
                participant.get("completedAt"),
            ]
        )
    participants_csv = _csv_bytes(
        [
            "analysisCode",
            "role",
            "bookingStatus",
            "attendedAt",
            "instructionCompletedAt",
            "questionnaireStatus",
            "questionnaireCompletedAt",
            "completedAt",
        ],
        participants_rows,
    )

    turn_rows = []
    for trial in export["trials"]:
        for turn in trial["turns"]:
            turn_rows.append(
                [
                    room.id,
                    trial["trialIndex"],
                    trial["gameNumber"],
                    trial["sourceIndex"],
                    trial["isPractice"],
                    trial["formalTrial"],
                    turn["round"],
                    turn["selections"].get("player1", []),
                    turn["selections"].get("player2", []),
                    turn["selectionSources"].get("player1"),
                    turn["selectionSources"].get("player2"),
                    turn["autoSelected"].get("player1", False),
                    turn["autoSelected"].get("player2", False),
                    turn["soldierPolicies"].get("player1", []),
                    turn["soldierPolicies"].get("player2", []),
                    turn["board"].get("owners", []),
                    turn["board"].get("soldiers", []),
                    turn["warLocation"],
                    turn["warLost"].get("player1", []),
                    turn["warLost"].get("player2", []),
                    turn["logistics"].get("player1", 0),
                    turn["logistics"].get("player2", 0),
                    turn["numOfWar"],
                    turn["forced"],
                    turn["recordedAt"],
                ]
            )
    turns_csv = _csv_bytes(
        [
            "roomId",
            "trialIndex",
            "gameNumber",
            "sourceIndex",
            "isPractice",
            "formalTrial",
            "round",
            "selectionPlayer1",
            "selectionPlayer2",
            "sourcePlayer1",
            "sourcePlayer2",
            "autoSelectedPlayer1",
            "autoSelectedPlayer2",
            "soldierPolicyPlayer1",
            "soldierPolicyPlayer2",
            "owners",
            "soldiers",
            "warLocation",
            "warLostPlayer1",
            "warLostPlayer2",
            "logisticsPlayer1",
            "logisticsPlayer2",
            "numOfWar",
            "forced",
            "recordedAt",
        ],
        turn_rows,
    )

    events_csv = _csv_bytes(
        ["type", "analysisCode", "createdAt", "payload"],
        [[event["type"], event["analysisCode"], event["createdAt"], event["payload"]] for event in export["events"]],
    )

    payment_rows = []
    for payment in export["payments"]:
        payment_rows.append(
            [
                payment["analysisCode"],
                payment["basePayCents"],
                payment["performancePayCents"],
                payment["showupPayCents"],
                payment["overrideAmountCents"],
                payment["totalCents"],
                payment["status"],
                payment["computedAt"],
                payment["deadlineAt"],
                payment["paidAt"],
                payment["note"],
            ]
        )
    payment_csv = _csv_bytes(
        [
            "analysisCode",
            "basePayCents",
            "performancePayCents",
            "showupPayCents",
            "overrideAmountCents",
            "totalCents",
            "status",
            "computedAt",
            "deadlineAt",
            "paidAt",
            "note",
        ],
        payment_rows,
    )

    questionnaire_payload = {
        "versionId": export["questionnaire"]["versionId"],
        "version": export["questionnaire"]["version"],
        "contentHash": export["questionnaire"]["contentHash"],
        "protectedQuestionIds": export["questionnaire"].get("protectedQuestionIds") or [],
        "responses": [
            {
                "analysisCode": participant["analysisCode"],
                "status": (participant.get("questionnaire") or {}).get("status"),
                "completedAt": (participant.get("questionnaire") or {}).get("completedAt"),
                "jatosWorkerId": (participant.get("questionnaire") or {}).get("jatosWorkerId"),
                "jatosStudyResultId": (participant.get("questionnaire") or {}).get("jatosStudyResultId"),
                "jatosComponentResultId": (participant.get("questionnaire") or {}).get("jatosComponentResultId"),
                "answers": (participant.get("questionnaire") or {}).get("answers"),
            }
            for participant in export["participants"]
        ],
    }

    files: dict[str, bytes] = {}
    files["room.json"] = json.dumps(export, ensure_ascii=False, indent=2).encode("utf-8")
    files["participants.csv"] = participants_csv
    files["turns.csv"] = turns_csv
    files["events.csv"] = events_csv
    files["questionnaire.json"] = json.dumps(questionnaire_payload, ensure_ascii=False, indent=2).encode("utf-8")
    files["payment.csv"] = payment_csv
    for trial in export["trials"]:
        files[f"trials/trial{trial['trialIndex']}.json"] = json.dumps(
            trial, ensure_ascii=False, indent=2
        ).encode("utf-8")
    media_manifest = {"assets": media_entries}
    files["media/manifest.json"] = json.dumps(media_manifest, ensure_ascii=False, indent=2).encode("utf-8")
    for asset, entry in zip(assets, media_entries):
        path = media_absolute_path(asset)
        if not path.exists():
            raise RuntimeError(f"媒体文件缺失: {asset.id}")
        files[entry["path"]] = path.read_bytes()

    manifest_files = []
    for path in sorted(files):
        data = files[path]
        manifest_files.append(
            {
                "path": path,
                "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
            }
        )
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "roomId": room.id,
        "exportedAt": export["exportedAt"],
        "containsPII": False,
        "mediaIncluded": True,
        "files": manifest_files,
        "rowCounts": {
            "participants": len(export["participants"]),
            "trials": len(export["trials"]),
            "turns": sum(len(trial["turns"]) for trial in export["trials"]),
            "events": len(export["events"]),
            "payments": len(export["payments"]),
        },
    }
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.writestr(path, files[path])
    return buffer.getvalue()
