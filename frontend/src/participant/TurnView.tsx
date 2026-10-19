import { useEffect, useRef, useState } from "react";

import type {
  BoardState,
  GameState,
  PartnerState,
  TurnMessage,
  TurnResultMessage,
} from "../shared/types";
import { ExitControl } from "./ExitControl";
import { TURN_SELF_DISCONNECTED } from "./flowCopy";
import { GameBoard } from "./GameBoard";
import type { SocketStatus } from "./RoomSocket";
import { formatClock, secondsLeft, useNow } from "./time";

function hudTrialLabel(game: GameState, round: number): string {
  const turnCount = game.turnCount > 0 ? game.turnCount : 0;
  if (game.isPractice === true) {
    return `练习 ${round}/${turnCount}`;
  }
  if (game.isPractice === false && game.formalTrials > 0) {
    const formalPosition = game.gameNumber - game.practiceTrials;
    return `正式 ${formalPosition}/${game.formalTrials} · 回合 ${round}/${turnCount}`;
  }
  return `回合 ${round}/${turnCount}`;
}

export function TurnView({
  role,
  game,
  turn,
  result,
  partner,
  socketStatus,
  serverOffsetMs,
  submitted,
  exitPending,
  canExit,
  onSubmit,
  onExit,
}: {
  role: 1 | 2;
  game: GameState;
  turn: TurnMessage | null;
  result: TurnResultMessage | null;
  partner: PartnerState;
  socketStatus: SocketStatus;
  serverOffsetMs: number;
  submitted: boolean;
  exitPending: boolean;
  canExit: boolean;
  onSubmit: (cells: number[]) => void;
  onExit: () => void;
}) {
  const now = useNow(250);
  const [selected, setSelected] = useState<number[]>([]);
  const socketActive = socketStatus === "open";
  const clockActive = socketActive && partner.online;
  const roundKey = `${game.trialIndex}:${game.round}`;
  const roleKey = role === 1 ? "player1" : "player2";
  const lastRemainingRef = useRef(game.turnSeconds);

  useEffect(() => {
    setSelected([]);
  }, [roundKey]);

  useEffect(() => {
    if (result !== null) {
      setSelected([]);
    }
  }, [result]);

  const board: BoardState | null =
    result?.board ?? game.board ?? turn?.board ?? null;
  const warCells = result?.warLocation ?? [];
  const flashKey = result === null ? "" : `war-${result.trialIndex}-${result.round}`;
  const displayRound = result?.round ?? game.round;
  const deadline = result?.deadline ?? game.turnDeadline ?? turn?.deadline;
  const turnSeconds = game.turnSeconds > 0 ? game.turnSeconds : 30;
  const rawRemaining = secondsLeft(deadline, now, serverOffsetMs);
  if (rawRemaining !== null && clockActive) {
    lastRemainingRef.current =
      result !== null ? Math.min(rawRemaining, turnSeconds) : rawRemaining;
  }
  const remaining = clockActive
    ? rawRemaining ?? lastRemainingRef.current
    : lastRemainingRef.current;
  const displayRemaining = result !== null ? turnSeconds : remaining;
  const progress = Math.max(0, Math.min(100, (displayRemaining / turnSeconds) * 100));
  const countdownTone =
    displayRemaining <= 5 ? "danger" : displayRemaining <= 10 ? "warning" : "normal";
  const partnerText = partner.online ? "另一名玩家在线" : "另一名玩家离线";
  const boardSelected = result !== null ? [] : selected;
  const submittedView = result !== null || submitted;
  const autoSelectedBySelf =
    result !== null && result.autoSelected[roleKey] === true;

  const toggleCell = (index: number) => {
    if (result !== null || submitted || !socketActive || exitPending) return;
    setSelected((current) =>
      current.includes(index)
        ? current.filter((candidate) => candidate !== index)
        : [...current, index].sort((left, right) => left - right),
    );
  };

  const canSubmit =
    selected.length > 0 &&
    result === null &&
    !submitted &&
    socketActive &&
    !exitPending;

  const submit = () => {
    if (!canSubmit) return;
    onSubmit(selected);
  };

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.code !== "Space" && event.key !== " ") return;
      if (event.repeat || event.altKey || event.ctrlKey || event.metaKey) return;
      const target = event.target;
      if (target instanceof HTMLElement) {
        if (
          target.closest(
            "button, a, input, textarea, select, [contenteditable='true'], [role='dialog']",
          )
        ) {
          return;
        }
      }
      if (!canSubmit) return;
      event.preventDefault();
      onSubmit(selected);
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [canSubmit, onSubmit, selected]);

  return (
    <>
      <div className="exp-hud">
        <div className="exp-hud-left">
          <span>{hudTrialLabel(game, displayRound)}</span>
        </div>
        <div className="exp-countdown-slot">
          <span className="exp-countdown-label">剩余时间</span>
          <span
            className={
              countdownTone === "danger"
                ? "exp-countdown exp-countdown-danger"
                : countdownTone === "warning"
                  ? "exp-countdown exp-countdown-warning"
                  : "exp-countdown"
            }
            data-testid="game-countdown"
            role="timer"
            aria-label={`回合剩余时间 ${formatClock(displayRemaining)}`}
          >
            {formatClock(displayRemaining)}
            <span className="exp-progress" aria-hidden="true">
              <span
                className="exp-progress-fill"
                style={{ width: `${progress}%` }}
              />
            </span>
          </span>
        </div>
        <div className="exp-hud-right">
          <span className="exp-hud-role">你是玩家 {role === 1 ? "○" : "◇"}</span>
          <span className="exp-hud-partner" data-testid="hud-partner">
            <span
              className={
                partner.online ? "exp-partner-dot" : "exp-partner-dot offline"
              }
              aria-hidden="true"
            />
            {partnerText}
          </span>
          {canExit ? (
            <ExitControl onConfirm={onExit} disabled={exitPending} />
          ) : null}
        </div>
      </div>

      {!socketActive ? (
        <div className="exp-connection-banner" role="status">
          {TURN_SELF_DISCONNECTED}
        </div>
      ) : null}
      <p className="exp-small-screen exp-viewport-hint">
        建议使用桌面浏览器并保持窗口足够大
      </p>

      {board !== null ? (
        <div className="exp-game">
          <GameBoard
            board={board}
            visuals={game.visuals}
            selected={boardSelected}
            warCells={warCells}
            flashKey={flashKey}
            disabled={result !== null || submitted || !socketActive || exitPending}
            onToggle={toggleCell}
            onClear={() => {
              if (result !== null || submitted || !socketActive || exitPending) return;
              setSelected([]);
            }}
          />
          <div className="exp-actions exp-actions-column">
            <button
              type="button"
              className="exp-confirm"
              data-testid="confirm-selection"
              disabled={!canSubmit}
              onClick={submit}
            >
              {submittedView
                ? autoSelectedBySelf
                  ? "已自动选择"
                  : "已提交"
                : "确认选择"}
            </button>
            <p className="exp-hint" role="status">
              {exitPending
                ? "正在退出实验，请稍候…"
                : autoSelectedBySelf
                  ? "已自动选择，等待下一回合。"
                  : submittedView
                    ? "已提交，等待另一名参与者或回合结算。"
                    : !socketActive
                      ? "连接中断，正在重新连接…"
                      : selected.length === 0
                        ? "至少选择一个格子"
                        : `已选择 ${selected.length} 个格子 · 空格键提交，右键取消选择`}
            </p>
          </div>
        </div>
      ) : (
        <div className="exp-centered">
          <p className="p-muted" role="status">
            正在加载棋盘…
          </p>
        </div>
      )}
    </>
  );
}
