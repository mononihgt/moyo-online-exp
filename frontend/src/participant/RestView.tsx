import { useRef } from "react";

import type { PartnerState, RestMessage, TrialScores } from "../shared/types";
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
  formalTrials: number;
  finalSoldiers: TrialScores | null;
  restSeconds: number;
  deadline: string | null;
  ready: Record<string, boolean>;
}

export function restDataFromMessage(message: RestMessage): RestViewData {
  return {
    completedIsPractice: message.completedIsPractice,
    completedFormalTrial: message.completedFormalTrial,
    formalTrials: message.formalTrials,
    finalSoldiers: message.finalSoldiers,
    restSeconds: message.restSeconds,
    deadline: message.deadline,
    ready: message.ready,
  };
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
    <div className="exp-rest" data-testid="rest-view">
      <div className="exp-rest-split">
        <section className="exp-rest-main" aria-label="休息操作">
          <p className="exp-kicker">对局间休息</p>
          {data.completedIsPractice === true ? (
            <h1 className="exp-rest-title" data-testid="rest-title">
              练习结束
            </h1>
          ) : null}
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
                ? "另一名参与者已准备"
                : partner.online
                  ? "等待另一名参与者准备"
                  : reconnectRemaining !== null && reconnectRemaining > 0
                    ? `另一名参与者离线，重连剩余 ${formatClock(reconnectRemaining)}`
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
                ? "已准备，等待另一名参与者"
                : "我休息好了，可以继续"}
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
        </section>

        <section
          className="exp-rest-summary"
          aria-label="本局结算"
          data-testid="rest-summary"
        >
          <div className="exp-rest-summary-head">
            <h2 className="exp-rest-summary-title">本局结算</h2>
            <span className="exp-rest-trial-chip" data-testid="rest-trial-chip">
              {data.completedIsPractice === true ? (
                "练习局"
              ) : (
                <>
                  对局{" "}
                  <strong>
                    {data.completedFormalTrial ?? 0}/{data.formalTrials}
                  </strong>
                </>
              )}
            </span>
          </div>
          <div className="exp-rest-score-row">
            <span>
              <span className="exp-rest-marker" aria-hidden="true">
                ◇
              </span>{" "}
              得分
            </span>
            <strong data-testid="rest-score-player2">
              {data.finalSoldiers?.player2 ?? "—"}
            </strong>
          </div>
          <div className="exp-rest-score-row">
            <span>
              <span className="exp-rest-marker" aria-hidden="true">
                ○
              </span>{" "}
              得分
            </span>
            <strong data-testid="rest-score-player1">
              {data.finalSoldiers?.player1 ?? "—"}
            </strong>
          </div>
        </section>
      </div>
      <p className="exp-small-screen exp-viewport-hint">
        建议使用桌面浏览器并保持窗口足够大
      </p>
    </div>
  );
}
