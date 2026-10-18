import { useEffect, useState } from "react";

import type { InstructionState, PartnerState } from "../shared/types";
import { ROLE_LABELS } from "./apiTypes";
import { ExitControl } from "./ExitControl";
import {
  INSTRUCTION_PARTNER_OFFLINE,
  INSTRUCTION_SELF_DISCONNECTED,
} from "./flowCopy";
import { formatClock } from "./time";

export function InstructionsView({
  instruction,
  partner,
  connectionActive,
  actionPending,
  exitPending,
  canExit,
  onComplete,
  onEnterGame,
  onExit,
}: {
  instruction: InstructionState;
  partner: PartnerState;
  connectionActive: boolean;
  actionPending: boolean;
  exitPending: boolean;
  canExit: boolean;
  onComplete: () => void;
  onEnterGame: () => void;
  onExit: () => void;
}) {
  const [elapsed, setElapsed] = useState(instruction.connectedSeconds);

  useEffect(() => {
    setElapsed(instruction.connectedSeconds);
  }, [instruction.connectedSeconds]);

  const clockActive = connectionActive && partner.online;

  useEffect(() => {
    if (!clockActive || instruction.completed) return;
    const timer = window.setInterval(() => {
      setElapsed((current) => current + 1);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [clockActive, instruction.completed]);

  const remaining = Math.max(0, instruction.minReadingSeconds - elapsed);
  const canComplete = instruction.completed || remaining === 0;
  const bothCompleted = instruction.bothCompleted || (instruction.completed && instruction.partnerCompleted);
  const partnerReading = instruction.partnerCompleted
    ? "搭档已完成阅读"
    : partner.online
      ? "搭档正在阅读"
      : INSTRUCTION_PARTNER_OFFLINE;

  return (
    <div className="exp-instructions">
      <header className="exp-instructions-header">
        <div>
          <p className="exp-kicker">实验指导语</p>
          <h1 className="exp-instruction-title">指导语</h1>
          <p className="p-muted exp-role-line">
            你是{ROLE_LABELS[instruction.role]}。棋盘上你的棋子使用
            {instruction.role === 1 ? "圆形" : "菱形"}标记，另一名参与者使用
            {instruction.role === 1 ? "菱形" : "圆形"}标记。
          </p>
        </div>
        <div className="exp-instructions-side">
          {canExit ? (
            <ExitControl onConfirm={onExit} disabled={exitPending} />
          ) : null}
          <div className="exp-reading-status" role="status">
            <div>
              最短阅读时间：{formatClock(instruction.minReadingSeconds)}
            </div>
            <div>
              {instruction.completed
                ? "你已完成阅读"
                : remaining > 0
                  ? `请继续阅读，剩余 ${formatClock(remaining)}`
                  : "已满足最短阅读时间"}
            </div>
            <div>{partnerReading}</div>
            {!connectionActive ? (
              <div className="exp-reading-paused">
                {INSTRUCTION_SELF_DISCONNECTED}
              </div>
            ) : null}
          </div>
        </div>
      </header>

      <article
        className="exp-instruction-content"
        data-testid="instruction-content"
        dangerouslySetInnerHTML={{ __html: instruction.contentHtml }}
      />

      <div className="exp-instruction-actions">
        <button
          type="button"
          className="p-btn p-btn-primary"
          data-testid="instruction-complete"
          disabled={
            !canComplete || instruction.completed || actionPending || exitPending
          }
          onClick={onComplete}
          aria-describedby="reading-remaining"
        >
          {instruction.completed
            ? "阅读已完成"
            : remaining > 0
              ? `阅读完成（剩余 ${formatClock(remaining)}）`
              : "阅读完成"}
        </button>
        <span className="p-muted" id="reading-remaining">
          {instruction.completed
            ? instruction.partnerCompleted
              ? "双方均已完成阅读。"
              : "等待搭档完成阅读。"
            : remaining > 0
              ? `至少还需阅读 ${formatClock(remaining)}。`
              : "现在可以确认完成阅读。"}
        </span>
      </div>

      {bothCompleted ? (
        <div className="exp-enter-card">
          <h2 className="p-section-title">双方已完成阅读</h2>
          <p className="p-muted">
            {instruction.bothEnterRequested
              ? "双方均已确认进入，正在开始实验…"
              : "确认后将进入实验。若浏览器仍未全屏，点击时会再次尝试进入全屏。"}
          </p>
          <button
            type="button"
            className="p-btn p-btn-primary"
            data-testid="enter-game"
            disabled={instruction.enterRequested || actionPending || exitPending}
            onClick={onEnterGame}
          >
            {instruction.enterRequested ? "已确认，等待搭档" : "进入实验"}
          </button>
        </div>
      ) : null}
    </div>
  );
}
