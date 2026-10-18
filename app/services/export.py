import csv
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import QUESTIONNAIRE_COMPLETED, SCHEMA_VERSION, TIMEZONE
from ..models import (
    Booking,
    ConditionVersion,
    GameTrial,
    InstructionVersion,
    MediaAsset,
    Participant,
    Payment,
    QuestionnaireResponse,
    QuestionnaireVersion,
    Room,
    RoomConfigRevision,
    RoomEvent,
    RoomParticipant,
    Turn,
)
from ..security import decrypt_phone
from ..timeutil import isoformat_utc, utcnow
from .conditions import serialize_condition_snapshot
from .media import media_absolute_path
from .payments import serialize_payment
from .questionnaires import serialize_questionnaire

_ASSET_REF = re.compile(r"asset://([0-9a-fA-F-]{36})")
_SENSITIVE_PAYLOAD_KEYS = {
    "name",
    "phone",
    "phoneHash",
    "phoneEncrypted",
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


async def _room_instructions(db: AsyncSession, room: Room) -> dict:
    if room.config_snapshot:
        instructions = room.config_snapshot.get("instructions", {})
        return {
            role: {
                "versionId": data.get("versionId") or data.get("id"),
                "name": data.get("name"),
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
        return {
            "versionId": data.get("versionId") or data.get("id"),
            "name": data.get("name"),
            "version": data.get("version"),
            "contentHash": data.get("contentHash"),
            "publishedAt": data.get("publishedAt"),
            "schema": data.get("schema"),
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
    }


async def _room_condition(db: AsyncSession, room: Room) -> dict:
    if room.config_snapshot and room.config_snapshot.get("condition"):
        return room.config_snapshot["condition"]
    condition = await db.get(ConditionVersion, room.condition_version_id)
    return serialize_condition_snapshot(condition)


async def build_room_export(db: AsyncSession, room: Room) -> dict:
    condition = await _room_condition(db, room)
    instructions = await _room_instructions(db, room)
    questionnaire = await _room_questionnaire(db, room)
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
        "archivedAt": isoformat_utc(room.archived_at),
        "status": room.status,
        "archiveReason": room.archive_reason,
        "timezone": TIMEZONE,
        "waitWindowSeconds": room.wait_window_seconds,
        "reconnectWindowSeconds": room.reconnect_window_seconds,
        "configLockedAt": isoformat_utc(room.config_locked_at),
        "basePayCents": room.base_pay_cents,
        "performanceRateCents": room.performance_rate_cents,
        "showupPayCents": room.showup_pay_cents,
        "configRevisions": revisions,
    }

    bookings_query = await db.execute(select(Booking).where(Booking.room_id == room.id))
    bookings = {booking.participant_id: booking for booking in bookings_query.scalars().all()}
    rows_query = await db.execute(
        select(RoomParticipant).where(RoomParticipant.room_id == room.id).order_by(RoomParticipant.role)
    )
    room_participants = list(rows_query.scalars().all())
    participant_ids = {row.participant_id for row in room_participants}
    if not participant_ids:
        participant_ids = {booking.participant_id for booking in bookings.values() if booking.status != "canceled"}
    responses_query = await db.execute(
        select(QuestionnaireResponse)
        .where(QuestionnaireResponse.room_id == room.id)
        .order_by(QuestionnaireResponse.completed_at)
    )
    responses_by_participant: dict[str, list[QuestionnaireResponse]] = {}
    for response in responses_query.scalars().all():
        responses_by_participant.setdefault(response.participant_id, []).append(response)
    analysis_codes = {row.participant_id: row.analysis_code for row in room_participants}
    participant_payloads = []
    for participant_id in sorted(participant_ids):
        row = next((item for item in room_participants if item.participant_id == participant_id), None)
        booking = bookings.get(participant_id)
        responses = responses_by_participant.get(participant_id, [])
        canonical = next((response for response in responses if response.canonical), None)
        instruction_payload = None
        if row is not None:
            version_id = instructions[f"player{row.role}"]["versionId"]
            instruction_payload = {
                "versionId": version_id,
                "startedAt": isoformat_utc(row.instruction_started_at),
                "completedAt": isoformat_utc(row.instruction_completed_at),
                "minReadingSeconds": instructions[f"player{row.role}"]["minReadingSeconds"],
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
                "answers": canonical.answers_json if canonical else None,
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
                "params": trial.params_json,
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
        payments.append(data)

    media_assets, media_entries = await _collect_media(db, condition, instructions)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "exportedAt": isoformat_utc(utcnow()),
        "room": room_payload,
        "condition": condition,
        "instructions": instructions,
        "questionnaire": questionnaire,
        "participants": participant_payloads,
        "trialPlan": room.trial_plan_json,
        "trials": trial_payloads,
        "events": events,
        "payments": payments,
        "media": media_entries,
    }


async def _collect_media(db: AsyncSession, condition: dict, instructions: dict) -> tuple[list[MediaAsset], list[dict]]:
    asset_ids: set[str] = set()
    for player in ("player1", "player2"):
        for visual in condition.get("visuals", {}).get(player, []):
            if visual.get("backgroundAssetId"):
                asset_ids.add(visual["backgroundAssetId"])
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
                "path": f"media/{asset.id}{extension}",
            }
        )
    return assets, entries


async def build_analysis_zip(db: AsyncSession, room: Room) -> bytes:
    export = await build_room_export(db, room)
    condition = export["condition"]
    instructions = export["instructions"]
    assets, media_entries = await _collect_media(db, condition, instructions)
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
        },
    }
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.writestr(path, files[path])
    return buffer.getvalue()


async def build_payment_export_csv(db: AsyncSession) -> bytes:
    rows = await db.execute(
        select(Payment, Participant, Room, RoomParticipant)
        .join(Participant, Participant.id == Payment.participant_id)
        .join(Room, Room.id == Payment.room_id)
        .join(
            RoomParticipant,
            (RoomParticipant.room_id == Payment.room_id)
            & (RoomParticipant.participant_id == Payment.participant_id),
        )
        .where(RoomParticipant.questionnaire_status == QUESTIONNAIRE_COMPLETED)
        .order_by(Room.starts_at, Participant.name)
    )
    header = [
        "analysisCode",
        "participantId",
        "name",
        "phone",
        "roomId",
        "roomStartsAt",
        "basePayCents",
        "performancePayCents",
        "showupPayCents",
        "overrideAmountCents",
        "totalCents",
        "status",
        "deadlineAt",
        "paidAt",
        "note",
    ]
    data_rows = []
    for payment, participant, room, role_row in rows.all():
        data_rows.append(
            [
                role_row.analysis_code if role_row else None,
                participant.id,
                participant.name,
                decrypt_phone(participant.phone_encrypted),
                room.id,
                isoformat_utc(room.starts_at),
                payment.base_pay_cents,
                payment.performance_pay_cents,
                payment.showup_pay_cents,
                payment.override_amount_cents,
                payment.total_cents,
                payment.status,
                isoformat_utc(payment.deadline_at),
                isoformat_utc(payment.paid_at),
                payment.admin_note,
            ]
        )
    return _csv_bytes(header, data_rows)
