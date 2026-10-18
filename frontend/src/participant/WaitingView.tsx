import { useEffect, useState } from "react";
import { DoorOpen, Users } from "lucide-react";

import { formatDateTime } from "../shared/format";
import type { PartnerState, RoomStateMessage } from "../shared/types";
import {
  WAIT_BOTH_CLICKED,
  WAIT_BOTH_ENTERED_DETAIL,
  WAIT_ERROR_PARTNER_ABSENT,
  WAIT_ERROR_PARTNER_MISSING,
  WAIT_EXIT_CONFIRM,
  WAIT_EXIT_CONTINUE,
  WAIT_EXIT_DETAIL,
  WAIT_EXIT_PARTNER,
  WAIT_EXIT_SINGLE,
  WAIT_EXIT_TITLE,
  WAIT_PARTNER_CLICKED,
  WAIT_PARTNER_NOT_ENTERED_DETAIL,
  WAIT_PARTNER_OFFLINE_DETAIL,
  WAIT_SELF_CLICKED,
  WAIT_SINGLE_DETAIL,
} from "./flowCopy";
import { formatClock, secondsLeft, useNow } from "./time";

function partnerWaitingText(partner: PartnerState): string {
  if (!partner.entered) return "等待搭档进入";
  if (!partner.online) return "搭档离线";
  if (partner.startRequested) return "搭档已点击开始匹配";
  return "搭档已进入";
}

export function WaitingView({
  roomState,
  serverOffsetMs,
  startRequested,
  actionPending,
  canExit,
  errorCode,
  onStart,
  onExit,
}: {
  roomState: RoomStateMessage;
  serverOffsetMs: number;
  startRequested: boolean;
  actionPending: boolean;
  canExit: boolean;
  errorCode: string | null;
  onStart: () => void;
  onExit: () => void;
}) {
  const now = useNow(250);
  const [confirmingExit, setConfirmingExit] = useState(false);
  const waitRemaining = secondsLeft(roomState.waitDeadline, now, serverOffsetMs);
  const onlyOneBooked = roomState.bookedCount < roomState.capacity;
  const partnerEntered = roomState.partner.entered;
  const partnerOnline = roomState.partner.online;
  const bothRequested = startRequested && roomState.partner.startRequested;
  const canStart =
    partnerEntered &&
    partnerOnline &&
    roomState.bookedCount >= roomState.capacity &&
    !startRequested &&
    !actionPending;
  const enteredCount = 1 + (partnerEntered ? 1 : 0);
  const partnerLabel = partnerWaitingText(roomState.partner);
  const showExit = canExit && !partnerEntered;
  const waitError =
    errorCode === "partner_missing"
      ? WAIT_ERROR_PARTNER_MISSING
      : errorCode === "partner_absent"
        ? WAIT_ERROR_PARTNER_ABSENT
        : null;
  const waitingDetail = onlyOneBooked
    ? WAIT_SINGLE_DETAIL
    : !partnerEntered
      ? WAIT_PARTNER_NOT_ENTERED_DETAIL
      : !partnerOnline
        ? WAIT_PARTNER_OFFLINE_DETAIL
        : WAIT_BOTH_ENTERED_DETAIL;

  useEffect(() => {
    if (!confirmingExit) return;
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setConfirmingExit(false);
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [confirmingExit]);

  useEffect(() => {
    if (partnerEntered) setConfirmingExit(false);
  }, [partnerEntered]);

  return (
    <div className="exp-waiting-stage">
      <section className="p-wait-card exp-waiting-card" aria-labelledby="waiting-title">
        <p className="exp-kicker">已进入等待房间</p>
        <h1 className="exp-rest-title" id="waiting-title">
          等待实验开始
        </h1>
        <p className="p-muted">开始时间：{formatDateTime(roomState.startsAt)}</p>

        <div className="p-wait-countdown" aria-live="off">
          {formatClock(waitRemaining ?? 0)}
        </div>
        <p className="p-muted">距离等待窗口结束</p>

        <div className="p-wait-status" data-testid="hud-partner">
          <span
            className={
              partnerOnline
                ? "p-dot p-dot-online"
                : partnerEntered
                  ? "p-dot p-dot-warning"
                  : "p-dot"
            }
            aria-hidden="true"
          />
          <span>{partnerLabel}</span>
        </div>

        <p className="p-muted exp-waiting-count">
          <Users size={16} aria-hidden="true" />
          已到场 {enteredCount}/{roomState.capacity}
        </p>

        <div className="p-banner p-banner-warning" role="status">
          {waitingDetail}
        </div>

        {waitError !== null ? (
          <div className="p-banner p-banner-error" role="alert">
            {waitError}
          </div>
        ) : null}

        {startRequested ? (
          <p className="p-muted" role="status">
            {bothRequested ? WAIT_BOTH_CLICKED : WAIT_SELF_CLICKED}
          </p>
        ) : roomState.partner.startRequested ? (
          <p className="p-muted" role="status">
            {WAIT_PARTNER_CLICKED}
          </p>
        ) : null}

        <div className="p-btn-row exp-waiting-actions">
          <button
            type="button"
            className="p-btn p-btn-primary"
            data-testid="start-matching"
            disabled={!canStart || bothRequested}
            onClick={onStart}
          >
            {startRequested ? "已请求开始" : "开始匹配"}
          </button>
        </div>

        <p className="exp-fullscreen-hint">
          点击“开始匹配”后实验将进入全屏。若浏览器拒绝全屏，实验仍会继续。
        </p>
      </section>

      {showExit ? (
        <div className="exp-exit-bar">
          <button
            type="button"
            className="p-btn p-btn-quiet exp-exit-button"
            data-testid="waiting-exit"
            disabled={actionPending}
            onClick={() => setConfirmingExit(true)}
          >
            <DoorOpen size={16} aria-hidden="true" />
            {onlyOneBooked ? WAIT_EXIT_SINGLE : WAIT_EXIT_PARTNER}
          </button>
        </div>
      ) : null}

      {confirmingExit && showExit ? (
        <div className="exp-modal-backdrop" role="presentation">
          <div
            className="exp-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="waiting-exit-title"
            aria-describedby="waiting-exit-description"
          >
            <h2 className="p-title-sm" id="waiting-exit-title">
              {WAIT_EXIT_TITLE}
            </h2>
            <p className="p-muted" id="waiting-exit-description">
              {WAIT_EXIT_DETAIL}
            </p>
            <div className="p-btn-row exp-modal-actions">
              <button
                type="button"
                className="p-btn p-btn-quiet"
                data-testid="waiting-exit-cancel"
                autoFocus
                disabled={actionPending}
                onClick={() => setConfirmingExit(false)}
              >
                {WAIT_EXIT_CONTINUE}
              </button>
              <button
                type="button"
                className="p-btn p-btn-danger"
                data-testid="waiting-exit-confirm"
                disabled={actionPending}
                onClick={onExit}
              >
                {WAIT_EXIT_CONFIRM}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
