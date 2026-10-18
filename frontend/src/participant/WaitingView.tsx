import { useEffect, useState } from "react";
import { DoorOpen, RefreshCw, Users } from "lucide-react";

import { formatDateTime } from "../shared/format";
import type { PartnerState, RoomStateMessage } from "../shared/types";
import { formatClock, secondsLeft, useNow } from "./time";

function partnerWaitingText(partner: PartnerState, reconnectRemaining: number | null): string {
  if (partner.startRequested) return "搭档已点击开始匹配";
  if (!partner.entered) return "等待搭档进入";
  if (!partner.online) {
    if (reconnectRemaining !== null && reconnectRemaining > 0) {
      return `搭档离线，重连剩余 ${formatClock(reconnectRemaining)}`;
    }
    return "搭档离线";
  }
  return "搭档已进入";
}

export function WaitingView({
  roomState,
  serverOffsetMs,
  startRequested,
  actionPending,
  errorCode,
  onStart,
  onExit,
  onHome,
}: {
  roomState: RoomStateMessage;
  serverOffsetMs: number;
  startRequested: boolean;
  actionPending: boolean;
  errorCode: string | null;
  onStart: () => void;
  onExit: () => void;
  onHome: () => void;
}) {
  const now = useNow(250);
  const [confirmingExit, setConfirmingExit] = useState(false);
  const waitRemaining = secondsLeft(roomState.waitDeadline, now, serverOffsetMs);
  const reconnectRemaining = secondsLeft(
    roomState.partner.disconnectedUntil,
    now,
    serverOffsetMs,
  );
  const onlyOneBooked = roomState.bookedCount < roomState.capacity;
  const onePersonOnly =
    onlyOneBooked ||
    errorCode === "partner_missing" ||
    errorCode === "partner_absent";
  const bothRequested = startRequested && roomState.partner.startRequested;
  const partnerLabel = partnerWaitingText(roomState.partner, reconnectRemaining);

  useEffect(() => {
    if (!confirmingExit) return;
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setConfirmingExit(false);
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [confirmingExit]);

  useEffect(() => {
    if (roomState.partner.entered) setConfirmingExit(false);
  }, [roomState.partner.entered]);

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
              roomState.partner.online
                ? "p-dot p-dot-online"
                : roomState.partner.entered
                  ? "p-dot p-dot-warning"
                  : "p-dot"
            }
            aria-hidden="true"
          />
          <span>{partnerLabel}</span>
        </div>

        <p className="p-muted exp-waiting-count">
          <Users size={16} aria-hidden="true" />
          已到场 {roomState.bookedCount}/{roomState.capacity}
        </p>

        {onePersonOnly ? (
          <div className="p-banner p-banner-warning" role="status">
            {onlyOneBooked
              ? "只有你一人报名。本次实验需要两名参与者，可以稍等搭档，或返回首页取消预约后改报其他时间。"
              : "搭档尚未到场或不在线。本次实验需要两名参与者，可以稍等搭档，或返回首页取消预约后改报其他时间。"}
          </div>
        ) : null}

        {startRequested ? (
          <p className="p-muted" role="status">
            {bothRequested
              ? "双方均已请求开始，正在进入实验…"
              : "你已请求开始，等待搭档点击开始匹配。"}
          </p>
        ) : roomState.partner.startRequested ? (
          <p className="p-muted" role="status">
            搭档已点击开始匹配，请点击开始匹配。
          </p>
        ) : null}

        <div className="p-btn-row exp-waiting-actions">
          <button
            type="button"
            className="p-btn p-btn-primary"
            data-testid="start-matching"
            disabled={startRequested || actionPending || onePersonOnly}
            onClick={onStart}
          >
            {startRequested ? "已请求开始" : "开始匹配"}
          </button>
          {onePersonOnly ? (
            <button
              type="button"
              className="p-btn p-btn-secondary"
              onClick={onHome}
            >
              <RefreshCw size={18} aria-hidden="true" />
              改报其他时间
            </button>
          ) : null}
        </div>

        <p className="exp-fullscreen-hint">
          点击“开始匹配”后实验将进入全屏。若浏览器拒绝全屏，实验仍会继续。
        </p>
      </section>

      {!roomState.partner.entered ? (
        <div className="exp-exit-bar">
          <button
            type="button"
            className="p-btn p-btn-quiet exp-exit-button"
            data-testid="exit-room"
            onClick={() => setConfirmingExit(true)}
          >
            <DoorOpen size={16} aria-hidden="true" />
            另一名被试可能放鸽子了，我退出本次实验
          </button>
        </div>
      ) : null}

      {confirmingExit ? (
        <div className="exp-modal-backdrop" role="presentation">
          <div
            className="exp-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="exit-title"
            aria-describedby="exit-description"
          >
            <h2 className="p-title-sm" id="exit-title">
              确认退出实验？
            </h2>
            <p className="p-muted" id="exit-description">
              退出后本次实验会结束，另一名参与者会看到你已离开。你可以返回首页重新预约其他时间。
            </p>
            <div className="p-btn-row exp-modal-actions">
              <button
                type="button"
                className="p-btn p-btn-quiet"
                autoFocus
                onClick={() => setConfirmingExit(false)}
              >
                继续等待
              </button>
              <button
                type="button"
                className="p-btn p-btn-danger"
                disabled={actionPending}
                onClick={() => {
                  setConfirmingExit(false);
                  onExit();
                }}
              >
                确认退出
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
