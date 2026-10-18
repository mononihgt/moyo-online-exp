import { useRef } from "react";

import type { PartnerState, RestMessage } from "../shared/types";
import { ExitControl } from "./ExitControl";
import {
  PARTNER_OFFLINE_RECONNECTING,
  REST_SELF_DISCONNECTED,
} from "./flowCopy";
import type { SocketStatus } from "./RoomSocket";
import { formatClock, secondsLeft, useNow } from "./time";

export interface RestViewData {
  completedIsPractice: boolean | null;
  completedFormalTrial: number | null;
  nextTrialIndex: number | null;
  nextIsPractice: boolean | null;
  nextFormalTrial: number | null;
  restSeconds: number;
  deadline: string | null;
  ready: Record<string, boolean>;
}

export function restDataFromMessage(message: RestMessage): RestViewData {
  return {
    completedIsPractice: message.completedIsPractice,
    completedFormalTrial: message.completedFormalTrial,
    nextTrialIndex: message.nextTrialIndex,
    nextIsPractice: message.nextIsPractice,
    nextFormalTrial: message.nextFormalTrial,
    restSeconds: message.restSeconds,
    deadline: message.deadline,
    ready: message.ready,
  };
}

function restTitle(data: RestViewData): string {
  if (data.completedIsPractice === true) return "练习结束";
  if (data.completedFormalTrial !== null) {
    return `第 ${data.completedFormalTrial} 个正式 trial 结束`;
  }
  return "本 trial 结束";
}

function nextTrialText(data: RestViewData): string {
  if (data.nextTrialIndex === null) {
    return "全部 trial 已完成，即将进入实验结束页面。";
  }
  if (data.nextTrialIndex === -1) {
    return "接下来进入下一项 trial。";
  }
  if (data.nextIsPractice === true) return "接下来是练习 trial。";
  if (data.nextFormalTrial !== null) {
    return `接下来是第 ${data.nextFormalTrial} 个正式 trial。`;
  }
  return "接下来进入下一项 trial。";
}

export function RestView({
  data,
  role,
  partner,
  socketStatus,
  serverOffsetMs,
  selfReady,
  exitPending,
  canExit,
  onReady,
  onExit,
}: {
  data: RestViewData;
  role: 1 | 2 | null;
  partner: PartnerState;
  socketStatus: SocketStatus;
  serverOffsetMs: number;
  selfReady: boolean;
  exitPending: boolean;
  canExit: boolean;
  onReady: () => void;
  onExit: () => void;
}) {
  const now = useNow(250);
  const heldRef = useRef(data.restSeconds);
  const socketActive = socketStatus === "open";
  const clockActive = socketActive && partner.online;
  const rawRemaining = secondsLeft(data.deadline, now, serverOffsetMs);
  const reconnectRemaining = secondsLeft(
    partner.disconnectedUntil,
    now,
    serverOffsetMs,
  );
  if (rawRemaining !== null && clockActive) {
    heldRef.current = rawRemaining;
  }
  const remaining = clockActive
    ? rawRemaining ?? heldRef.current
    : heldRef.current;
  const partnerReady =
    role !== null && data.ready[role === 1 ? "2" : "1"] === true;
  const bothReady = selfReady && partnerReady;

  return (
    <div className="exp-rest">
      <p className="exp-kicker">trial 间休息</p>
      <h1 className="exp-rest-title" data-testid="rest-title">
        {restTitle(data)}
      </h1>
      <p className="exp-rest-info">{nextTrialText(data)}</p>
      <div className="exp-rest-countdown" data-testid="rest-countdown" role="timer">
        {formatClock(remaining)}
      </div>
      <p className="exp-rest-info">
        倒计时结束后将自动继续；双方都准备好也会提前继续。
      </p>
      <div className="p-wait-status">
        <span
          className={
            partnerReady
              ? "p-dot p-dot-online"
              : partner.online
                ? "p-dot p-dot-warning"
                : "p-dot"
          }
          aria-hidden="true"
        />
        <span>
          {partnerReady
            ? "搭档已准备"
            : partner.online
              ? "等待搭档准备"
              : reconnectRemaining !== null && reconnectRemaining > 0
                ? `搭档离线，重连剩余 ${formatClock(reconnectRemaining)}`
                : PARTNER_OFFLINE_RECONNECTING}
        </span>
      </div>
      {!socketActive ? (
        <p className="p-muted" role="status">
          {REST_SELF_DISCONNECTED}
        </p>
      ) : null}
      <button
        type="button"
        className="p-btn p-btn-primary exp-rest-ready"
        data-testid="rest-ready"
        disabled={selfReady || !socketActive || exitPending}
        onClick={onReady}
      >
        {bothReady
          ? "正在进入下一项…"
          : selfReady
            ? "已准备，等待搭档"
            : "准备继续"}
      </button>
      {canExit ? (
        <div className="exp-rest-exit">
          {exitPending ? (
            <p className="p-muted" role="status">
              正在退出实验，请稍候…
            </p>
          ) : null}
          <ExitControl onConfirm={onExit} disabled={exitPending} />
        </div>
      ) : null}
      <p className="exp-small-screen exp-viewport-hint">
        建议使用桌面浏览器并保持窗口足够大
      </p>
    </div>
  );
}
