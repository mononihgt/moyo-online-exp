import { useCallback, useEffect, useRef, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";

import type {
  ArchiveReason,
  ExitReason,
  GameState,
  InstructionState,
  PartnerState,
  RewardKind,
  RoomStateMessage,
  ServerMessage,
  TrialStartMessage,
  TurnMessage,
  TurnResultMessage,
} from "../shared/types";
import { ArchiveView, NoRoomView, QuestionnaireView } from "./EndViews";
import type { QuestionnaireViewInfo } from "./EndViews";
import { SELF_EXIT_NOTICE } from "./flowCopy";
import { InstructionsView } from "./InstructionsView";
import { RestView, restDataFromMessage } from "./RestView";
import type { RestViewData } from "./RestView";
import { useRoomSocket } from "./RoomSocket";
import { TurnView } from "./TurnView";
import { WaitingView } from "./WaitingView";
import { exitFullscreenSilently } from "./time";

const EMPTY_PARTNER: PartnerState = {
  online: false,
  entered: false,
  startRequested: false,
  instructionCompleted: false,
  disconnectedUntil: null,
};

const RESULT_DISPLAY_MS = 1000;
const FULLSCREEN_NOTICE = "浏览器未进入全屏，实验将继续";
const FULLSCREEN_EXIT_NOTICE = "已退出全屏，实验继续";

interface RoomError {
  code: string;
  message: string;
}

interface ArchiveInfo {
  reason: ArchiveReason | null;
  canRebook: boolean;
  selfExited: boolean;
  selfExitReason: ExitReason | null;
  partnerExitReason: ExitReason | null;
  questionnaireCompleted: boolean;
  questionnaireRequired: boolean;
  rewardKind: RewardKind;
}

const REBOOKABLE_ARCHIVE_REASONS: ArchiveReason[] = [
  "not_full",
  "no_show",
  "no_start",
  "abandoned",
  "admin_aborted",
  "admin_cancelled",
];

function fallbackRebook(reason: ArchiveReason | null): boolean {
  return reason !== null && REBOOKABLE_ARCHIVE_REASONS.includes(reason);
}

function deriveRestFromGame(game: GameState): RestViewData {
  return {
    completedIsPractice: game.isPractice,
    completedFormalTrial: game.formalTrial,
    formalTrials: game.formalTrials,
    finalSoldiers: game.finalSoldiers,
    restSeconds: game.restSeconds,
    deadline: game.restDeadline,
    ready: game.restReady,
  };
}

function mergeTurn(current: GameState | null, message: TurnMessage): GameState {
  return {
    phase: "turn",
    trialIndex: message.trialIndex,
    gameNumber: current?.gameNumber ?? message.trialIndex + 1,
    totalTrials: current?.totalTrials ?? 0,
    practiceTrials: current?.practiceTrials ?? 0,
    formalTrials: current?.formalTrials ?? 0,
    isPractice: current?.isPractice ?? null,
    formalTrial: current?.formalTrial ?? null,
    round: message.round,
    turnCount: message.turnCount ?? current?.turnCount ?? 0,
    turnSeconds: message.turnSeconds ?? current?.turnSeconds ?? 30,
    restSeconds: current?.restSeconds ?? 0,
    initialSoldiersA: message.initialSoldiersA ?? current?.initialSoldiersA ?? 0,
    initialSoldiersB: message.initialSoldiersB ?? current?.initialSoldiersB ?? 0,
    reinforcementA: message.reinforcementA ?? current?.reinforcementA ?? 0,
    reinforcementB: message.reinforcementB ?? current?.reinforcementB ?? 0,
    sourceIndex: message.sourceIndex ?? current?.sourceIndex ?? null,
    board: message.board,
    visuals: current?.visuals ?? [],
    turnDeadline: message.deadline,
    restDeadline: null,
    submitted: message.submitted,
    partnerSubmitted: message.partnerSubmitted,
    restReady: {},
    finalSoldiers: null,
  };
}

function gameFromTrialStart(
  current: GameState | null,
  message: TrialStartMessage,
): GameState {
  return {
    phase: "turn",
    trialIndex: message.trialIndex,
    gameNumber: message.gameNumber,
    totalTrials: message.totalTrials,
    practiceTrials: message.practiceTrials,
    formalTrials: message.formalTrials,
    isPractice: message.isPractice,
    formalTrial: message.formalTrial,
    round: message.round,
    turnCount: message.turnCount,
    turnSeconds: message.turnSeconds,
    restSeconds: current?.restSeconds ?? 0,
    initialSoldiersA: message.initialSoldiersA,
    initialSoldiersB: message.initialSoldiersB,
    reinforcementA: message.reinforcementA,
    reinforcementB: message.reinforcementB,
    sourceIndex: message.sourceIndex,
    board: message.board,
    visuals: message.visuals,
    turnDeadline: null,
    restDeadline: null,
    submitted: false,
    partnerSubmitted: false,
    restReady: {},
    finalSoldiers: null,
  };
}

export default function RoomPage() {
  const params = useParams<{ roomId: string }>();
  const roomId = params.roomId ?? "";
  const navigate = useNavigate();
  const shellRef = useRef<HTMLDivElement | null>(null);
  const suppressFullscreenNoticeRef = useRef(false);
  const wasFullscreenRef = useRef(false);

  const [roomState, setRoomState] = useState<RoomStateMessage | null>(null);
  const [game, setGame] = useState<GameState | null>(null);
  const [turn, setTurn] = useState<TurnMessage | null>(null);
  const [result, setResult] = useState<TurnResultMessage | null>(null);
  const [rest, setRest] = useState<RestViewData | null>(null);
  const [instruction, setInstruction] = useState<InstructionState | null>(null);
  const [partner, setPartner] = useState<PartnerState>(EMPTY_PARTNER);
  const [questionnaire, setQuestionnaire] =
    useState<QuestionnaireViewInfo | null>(null);
  const [archive, setArchive] = useState<ArchiveInfo | null>(null);
  const [roomMissing, setRoomMissing] = useState(false);
  const [serverOffsetMs, setServerOffsetMs] = useState(0);
  const [error, setError] = useState<RoomError | null>(null);
  const [waitErrorCode, setWaitErrorCode] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [startRequestedLocal, setStartRequestedLocal] = useState(false);
  const [instructionCompleteSent, setInstructionCompleteSent] = useState(false);
  const [enterRequestedLocal, setEnterRequestedLocal] = useState(false);
  const [submittedLocal, setSubmittedLocal] = useState(false);
  const [restSelfReadyLocal, setRestSelfReadyLocal] = useState(false);
  const [exitPending, setExitPending] = useState(false);
  const [terminal, setTerminal] = useState(false);
  const [inactivityWarning, setInactivityWarning] = useState<number | null>(null);
  const roomWasActiveRef = useRef(false);

  const handleMessage = useCallback(
    (message: ServerMessage) => {
      if (message.type === "pong") {
        setServerOffsetMs(Date.parse(message.serverNow) - Date.now());
        return;
      }
      if (message.type === "error") {
        if (message.code === "room_mismatch") return;
        if (message.code === "no_active_room") {
          setRoomMissing(true);
          setTerminal(true);
          return;
        }
        if (message.code === "room_archived") {
          setArchive({
            reason: null,
            canRebook: false,
            selfExited: false,
            selfExitReason: null,
            partnerExitReason: null,
            questionnaireCompleted: false,
            questionnaireRequired: false,
            rewardKind: "none",
          });
          setTerminal(true);
          return;
        }
        if (message.code === "partner_missing" || message.code === "partner_absent") {
          setWaitErrorCode(message.code);
        }
        setError({ code: message.code, message: message.message });
        setStartRequestedLocal(false);
        setInstructionCompleteSent(false);
        setEnterRequestedLocal(false);
        setRestSelfReadyLocal(false);
        setExitPending(false);
        return;
      }
      if ("roomId" in message && message.roomId !== roomId) {
        if (message.type === "room_state") {
          navigate(`/room/${message.roomId}`, { replace: true });
        }
        return;
      }

      switch (message.type) {
        case "room_state": {
          if (message.status !== "archived") {
            roomWasActiveRef.current = true;
          }
          setRoomState(message);
          setPartner(message.partner);
          setServerOffsetMs(Date.parse(message.serverNow) - Date.now());
          if (message.role !== null) {
            setInstruction((current) =>
              current === null ? current : { ...current, role: message.role as 1 | 2 },
            );
          }
          if (message.instruction) {
            setInstruction(message.instruction);
          }
          if (message.partner.entered && message.bookedCount >= message.capacity) {
            setWaitErrorCode(null);
          }
          if (message.game) {
            const snapshot = message.game;
            setGame(snapshot);
            setTurn(null);
            setSubmittedLocal(snapshot.submitted);
            if (snapshot.phase === "rest") {
              setRest(deriveRestFromGame(snapshot));
              setRestSelfReadyLocal(false);
            } else {
              setRest(null);
              setRestSelfReadyLocal(false);
            }
          } else if (
            message.status !== "playing" &&
            message.status !== "questionnaire"
          ) {
            setGame(null);
            setTurn(null);
            setRest(null);
            setResult(null);
            setSubmittedLocal(false);
          }
          if (message.questionnaire) {
            setQuestionnaire(message.questionnaire);
          } else if (message.status === "questionnaire") {
            const questionStatus =
              message.self.questionnaireStatus ?? "in_progress";
            setQuestionnaire({
              url: null,
              status: questionStatus,
              submitted: questionStatus === "completed",
            });
          }
          if (message.archive || message.status === "archived") {
            const reason = message.archive?.reason ?? message.archiveReason;
            const selfExited = message.archive?.selfExited === true;
            const questionnaireCompleted =
              message.self.questionnaireStatus === "completed";
            setArchive({
              reason,
              canRebook:
                message.archive?.canRebook ?? fallbackRebook(reason),
              selfExited,
              selfExitReason: message.archive?.selfExitReason ?? null,
              partnerExitReason: message.archive?.partnerExitReason ?? null,
              questionnaireCompleted,
              questionnaireRequired:
                message.archive?.questionnaireRequired === true,
              rewardKind:
                message.archive?.rewardKind ??
                (reason === "completed" ? "completion" : "none"),
            });
            setTerminal(true);
          }
          break;
        }
        case "partner_state": {
          setPartner(message.partner);
          setRoomState((current) =>
            current === null ? current : { ...current, partner: message.partner },
          );
          break;
        }
        case "instruction_state": {
          setInstruction(message.instruction);
          break;
        }
        case "turn": {
          setTurn(message);
          setGame((current) => mergeTurn(current, message));
          setSubmittedLocal(message.submitted);
          setRest(null);
          setRestSelfReadyLocal(false);
          break;
        }
        case "turn_result": {
          setResult(message);
          setSubmittedLocal(true);
          setGame((current) =>
            current === null
              ? current
              : {
                  ...current,
                  initialSoldiersA:
                    message.initialSoldiersA ?? current.initialSoldiersA,
                  initialSoldiersB:
                    message.initialSoldiersB ?? current.initialSoldiersB,
                  reinforcementA:
                    message.reinforcementA ?? current.reinforcementA,
                  reinforcementB:
                    message.reinforcementB ?? current.reinforcementB,
                  sourceIndex: message.sourceIndex ?? current.sourceIndex,
                  board: message.board,
                  submitted: true,
                  partnerSubmitted: true,
                  turnDeadline: message.deadline ?? current.turnDeadline,
                },
          );
          break;
        }
        case "rest": {
          setRest(restDataFromMessage(message));
          setRestSelfReadyLocal(false);
          setGame((current) =>
            current === null
              ? current
              : {
                  ...current,
                  phase: "rest",
                  isPractice: message.completedIsPractice,
                  formalTrial: message.completedFormalTrial,
                  formalTrials: message.formalTrials,
                  finalSoldiers: message.finalSoldiers,
                  restDeadline: message.deadline,
                  restReady: message.ready,
                },
          );
          break;
        }
        case "trial_start": {
          if (!("trialIndex" in message)) break;
          setResult(null);
          setRest(null);
          setTurn(null);
          setSubmittedLocal(false);
          setRestSelfReadyLocal(false);
          setGame((current) => gameFromTrialStart(current, message));
          break;
        }
        case "game_start": {
          setGame((current) =>
            current === null
              ? current
              : { ...current, totalTrials: message.totalTrials },
          );
          break;
        }
        case "game_over": {
          setQuestionnaire((current) => ({
            url: message.questionnaireUrl,
            status: current?.status ?? "in_progress",
            submitted: false,
          }));
          break;
        }
        case "questionnaire_required": {
          setQuestionnaire({
            url: message.url,
            status: message.status,
            submitted: message.status === "completed",
          });
          break;
        }
        case "room_archived": {
          if (
            message.selfExited &&
            message.selfExitReason === "manual" &&
            roomWasActiveRef.current
          ) {
            setTerminal(true);
            navigate("/", {
              replace: true,
              state: { notice: SELF_EXIT_NOTICE },
            });
            break;
          }
          setArchive({
            reason: message.reason,
            canRebook: message.canRebook,
            selfExited: message.selfExited,
            selfExitReason: message.selfExitReason,
            partnerExitReason: message.partnerExitReason,
            questionnaireCompleted:
              message.selfQuestionnaireStatus === "completed",
            questionnaireRequired: message.questionnaireRequired === true,
            rewardKind: message.rewardKind,
          });
          setTerminal(true);
          break;
        }
        case "inactivity_warning": {
          setInactivityWarning(message.remainingSeconds);
          break;
        }
        case "rest_complete": {
          setRest(null);
          break;
        }
        default:
          break;
      }
    },
    [navigate, roomId],
  );

  const { status: socketStatus, send, superseded } = useRoomSocket(
    roomId,
    roomId !== "" && !terminal,
    handleMessage,
  );

  useEffect(() => {
    if (roomId === "" || terminal || socketStatus !== "open") return;
    let lastSent = 0;
    const report = () => {
      setInactivityWarning(null);
      const now = Date.now();
      if (now - lastSent < 10_000) return;
      lastSent = now;
      send({ type: "activity", roomId });
    };
    const reportVisibility = () => {
      const visible = document.visibilityState === "visible";
      send({ type: "visibility", roomId, visible });
      if (visible) report();
    };
    reportVisibility();
    window.addEventListener("pointerdown", report, { passive: true });
    window.addEventListener("keydown", report);
    window.addEventListener("wheel", report, { passive: true });
    window.addEventListener("touchstart", report, { passive: true });
    document.addEventListener("visibilitychange", reportVisibility);
    return () => {
      window.removeEventListener("pointerdown", report);
      window.removeEventListener("keydown", report);
      window.removeEventListener("wheel", report);
      window.removeEventListener("touchstart", report);
      document.removeEventListener("visibilitychange", reportVisibility);
    };
  }, [roomId, socketStatus, terminal, send]);

  useEffect(() => {
    if (terminal) setInactivityWarning(null);
  }, [terminal]);

  const requestFullscreen = useCallback(() => {
    const element = shellRef.current;
    if (element === null) return;
    if (document.fullscreenElement === element) return;
    if (
      typeof element.requestFullscreen !== "function" ||
      document.fullscreenEnabled === false
    ) {
      setNotice(FULLSCREEN_NOTICE);
      return;
    }
    try {
      Promise.resolve(element.requestFullscreen()).catch(() => {
        setNotice(FULLSCREEN_NOTICE);
      });
    } catch {
      setNotice(FULLSCREEN_NOTICE);
    }
  }, []);

  useEffect(() => {
    const handleFullscreenChange = () => {
      const element = document.fullscreenElement;
      if (element === shellRef.current) {
        wasFullscreenRef.current = true;
        suppressFullscreenNoticeRef.current = false;
        return;
      }
      if (element === null && wasFullscreenRef.current) {
        wasFullscreenRef.current = false;
        if (!suppressFullscreenNoticeRef.current) {
          setNotice(FULLSCREEN_EXIT_NOTICE);
        }
      }
    };
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => {
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
    };
  }, []);

  useEffect(() => {
    return () => {
      suppressFullscreenNoticeRef.current = true;
      exitFullscreenSilently();
    };
  }, []);

  const shouldExitFullscreen =
    questionnaire !== null || archive !== null || roomMissing;
  useEffect(() => {
    if (!shouldExitFullscreen) return;
    suppressFullscreenNoticeRef.current = true;
    exitFullscreenSilently();
  }, [shouldExitFullscreen]);

  useEffect(() => {
    if (result === null) return;
    const delay =
      result.resultDisplayMs ??
      (result.warLocation.length > 0 ? RESULT_DISPLAY_MS : 0);
    if (delay <= 0) {
      setResult(null);
      return;
    }
    const timer = window.setTimeout(() => setResult(null), delay);
    return () => window.clearTimeout(timer);
  }, [result]);

  useEffect(() => {
    if (notice === "") return;
    const timer = window.setTimeout(() => setNotice(""), 6000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  useEffect(() => {
    if (error === null) return;
    const timer = window.setTimeout(() => setError(null), 6000);
    return () => window.clearTimeout(timer);
  }, [error]);

  if (roomId === "") {
    return <Navigate to="/" replace />;
  }

  if (superseded) {
    return (
      <div className="exp-centered">
        <div className="exp-end-card">
          <p className="exp-kicker">实验已在另一个标签页打开</p>
          <h1 className="exp-rest-title">请回到另一个标签页继续</h1>
          <p className="exp-rest-info">
            这个页面已经停止连接，避免两个页面互相影响。如果另一个标签页已经关闭，可以刷新本页继续。
          </p>
          <div className="p-btn-row exp-end-actions">
            <button
              type="button"
              className="p-btn p-btn-primary"
              data-testid="takeover-refresh"
              onClick={() => window.location.reload()}
            >
              刷新这个页面
            </button>
            <Link
              className="p-btn p-btn-secondary"
              data-testid="takeover-home"
              to="/"
            >
              返回首页
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const startRequested =
    startRequestedLocal || roomState?.self.startRequested === true;
  const sentSubmit = send;

  const handleStartMatching = () => {
    if (exitPending) return;
    requestFullscreen();
    if (sentSubmit({ type: "start_matching", roomId })) {
      setError(null);
      setStartRequestedLocal(true);
    } else {
      setError({
        code: "connection",
        message: "连接中断，正在重新连接。请稍后重试。",
      });
    }
  };

  const handleInstructionComplete = () => {
    if (exitPending) return;
    if (sentSubmit({ type: "instruction_complete", roomId })) {
      setInstructionCompleteSent(true);
    } else {
      setError({
        code: "connection",
        message: "连接中断，正在重新连接。请稍后重试。",
      });
    }
  };

  const handleEnterGame = () => {
    if (exitPending) return;
    requestFullscreen();
    if (sentSubmit({ type: "enter_game", roomId })) {
      setEnterRequestedLocal(true);
    } else {
      setError({
        code: "connection",
        message: "连接中断，正在重新连接。请稍后重试。",
      });
    }
  };

  const handleSubmitSelection = (cells: number[]) => {
    if (game === null || exitPending) return;
    const clientMsgId =
      typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
        ? crypto.randomUUID()
        : `sel-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const sent = sentSubmit({
      type: "submit_selection",
      roomId,
      trialIndex: game.trialIndex,
      round: game.round,
      cells,
      clientMsgId,
    });
    if (sent) {
      setSubmittedLocal(true);
    } else {
      setError({
        code: "connection",
        message: "连接中断，正在重新连接。请稍后重试提交。",
      });
    }
  };

  const handleRestReady = () => {
    if (exitPending) return;
    if (sentSubmit({ type: "rest_ready", roomId })) {
      setRestSelfReadyLocal(true);
    } else {
      setError({
        code: "connection",
        message: "连接中断，正在重新连接。请稍后重试。",
      });
    }
  };

  const handleExitRoom = () => {
    if (exitPending) return;
    if (sentSubmit({ type: "exit_room", roomId })) {
      setExitPending(true);
      setNotice("正在退出实验，请稍候…");
    } else {
      setError({
        code: "connection",
        message: "连接中断，正在重新连接。请稍后重试。",
      });
    }
  };

  const role = roomState?.role ?? instruction?.role ?? null;
  const archiveInfo: ArchiveInfo | null =
    archive ??
    (roomState?.status === "archived"
      ? {
          reason: roomState.archive?.reason ?? roomState.archiveReason,
          canRebook:
            roomState.archive?.canRebook ??
            fallbackRebook(roomState.archiveReason),
          selfExited: roomState.archive?.selfExited === true,
          selfExitReason: roomState.archive?.selfExitReason ?? null,
          partnerExitReason: roomState.archive?.partnerExitReason ?? null,
          questionnaireCompleted:
            roomState.self.questionnaireStatus === "completed",
          questionnaireRequired: roomState.archive?.questionnaireRequired === true,
          rewardKind:
            roomState.archive?.rewardKind ??
            (roomState.archiveReason === "completed" ? "completion" : "none"),
        }
      : null);
  const questionnaireInfo: QuestionnaireViewInfo | null =
    questionnaire ??
    (roomState?.status === "questionnaire"
      ? {
          url: null,
          status: roomState.self.questionnaireStatus ?? "in_progress",
          submitted: roomState.self.questionnaireStatus === "completed",
        }
      : null);
  const gamePhase = game?.phase ?? null;
  const restVisible = rest ?? (gamePhase === "rest" && game ? deriveRestFromGame(game) : null);

  let phaseKind:
    | "archive"
    | "missing"
    | "turn"
    | "questionnaire"
    | "connecting"
    | "waiting"
    | "instructions"
    | "rest"
    | "loading";
  if (archiveInfo !== null) {
    phaseKind = "archive";
  } else if (roomMissing) {
    phaseKind = "missing";
  } else if (result !== null && game !== null) {
    phaseKind = "turn";
  } else if (questionnaireInfo !== null) {
    phaseKind = "questionnaire";
  } else if (roomState === null) {
    phaseKind = "connecting";
  } else if (roomState.status === "instructions") {
    phaseKind = "instructions";
  } else if (
    roomState.status === "waiting" ||
    roomState.status === "open" ||
    roomState.status === "full"
  ) {
    phaseKind = "waiting";
  } else if (roomState.status === "playing") {
    if (restVisible !== null) {
      phaseKind = "rest";
    } else if (game !== null && role !== null) {
      phaseKind = "turn";
    } else {
      phaseKind = "loading";
    }
  } else {
    phaseKind = "loading";
  }

  const waitingActive = phaseKind === "waiting" && startRequested;
  const canExit = roomState?.self.canExit !== false;
  const rootClass = [
    "exp-root",
    phaseKind === "waiting"
      ? waitingActive
        ? "exp-root-waiting exp-waiting-active"
        : "exp-root-waiting"
      : "",
    phaseKind === "connecting" || phaseKind === "loading"
      ? "exp-root-connecting"
      : "",
    phaseKind === "turn" || phaseKind === "rest" ? "exp-locked" : "",
    phaseKind === "archive" || phaseKind === "questionnaire"
      ? "exp-root-end"
      : "",
  ]
    .filter((part) => part !== "")
    .join(" ");

  const connectionNoticeVisible =
    socketStatus !== "open" && phaseKind === "waiting";

  return (
    <div className={rootClass} ref={shellRef}>
      {connectionNoticeVisible ? (
        <div className="exp-notice-stack" role="status">
          <div className="exp-notice exp-notice-status">
            连接中断，正在重新连接。请保持页面打开。
          </div>
        </div>
      ) : null}
      {inactivityWarning !== null ? (
        <div className="exp-notice-stack" role="status">
          <div className="exp-notice exp-notice-status">
            你已长时间没有操作。若继续无操作，实验将在 {inactivityWarning} 秒后自动结束，本次实验不产生报酬。
            <button
              type="button"
              className="p-linkish"
              data-testid="inactivity-ack"
              onClick={() => {
                setInactivityWarning(null);
                send({ type: "activity", roomId });
              }}
            >
              我还在
            </button>
          </div>
        </div>
      ) : null}
      {error !== null || notice !== "" ? (
        <div className="exp-notice-stack">
          {notice !== "" ? (
            <div className="exp-notice" role="status">
              {notice}
            </div>
          ) : null}
          {error !== null ? (
            <div className="exp-notice exp-notice-error" role="alert">
              {error.message}
            </div>
          ) : null}
        </div>
      ) : null}

      {phaseKind === "archive" && archiveInfo !== null ? (
        <ArchiveView
          roomId={roomId}
          reason={archiveInfo.reason}
          canRebook={archiveInfo.canRebook}
          selfExited={archiveInfo.selfExited}
          selfExitReason={archiveInfo.selfExitReason}
          partnerExitReason={archiveInfo.partnerExitReason}
          questionnaireCompleted={archiveInfo.questionnaireCompleted}
          questionnaireRequired={archiveInfo.questionnaireRequired}
          rewardKind={archiveInfo.rewardKind}
        />
      ) : phaseKind === "missing" ? (
        <NoRoomView />
      ) : phaseKind === "questionnaire" ? (
        <QuestionnaireView roomId={roomId} info={questionnaireInfo} />
      ) : phaseKind === "turn" && game !== null && role !== null ? (
        <TurnView
          role={role}
          game={game}
          turn={turn}
          result={result}
          partner={partner}
          socketStatus={socketStatus}
          serverOffsetMs={serverOffsetMs}
          submitted={submittedLocal || game.submitted}
          exitPending={exitPending}
          canExit={canExit}
          onSubmit={handleSubmitSelection}
          onExit={handleExitRoom}
        />
      ) : phaseKind === "rest" && restVisible !== null && role !== null ? (
        <RestView
          data={restVisible}
          role={role}
          partner={partner}
          socketStatus={socketStatus}
          serverOffsetMs={serverOffsetMs}
          selfReady={
            restSelfReadyLocal ||
            restVisible.ready[String(role)] === true
          }
          exitPending={exitPending}
          canExit={canExit}
          onReady={handleRestReady}
          onExit={handleExitRoom}
        />
      ) : phaseKind === "waiting" && roomState !== null ? (
        <WaitingView
          roomState={roomState}
          serverOffsetMs={serverOffsetMs}
          startRequested={startRequested}
          actionPending={exitPending}
          canExit={canExit}
          errorCode={waitErrorCode}
          errorMessage={
            error !== null &&
            (error.code === "partner_missing" || error.code === "partner_absent")
              ? error.message
              : null
          }
          onStart={handleStartMatching}
          onExit={handleExitRoom}
        />
      ) : phaseKind === "instructions" &&
        instruction !== null &&
        roomState !== null ? (
        <InstructionsView
          instruction={{
            ...instruction,
            enterRequested:
              instruction.enterRequested || enterRequestedLocal,
          }}
          partner={partner}
          connectionActive={socketStatus === "open"}
          actionPending={instructionCompleteSent && !instruction.completed}
          exitPending={exitPending}
          canExit={canExit}
          onComplete={handleInstructionComplete}
          onEnterGame={handleEnterGame}
          onExit={handleExitRoom}
        />
      ) : phaseKind === "connecting" || phaseKind === "loading" ? (
        <div className="exp-centered">
          <div className="exp-end-card">
            <h1 className="exp-rest-title">
              {phaseKind === "connecting" ? "正在连接实验…" : "正在同步实验状态…"}
            </h1>
            <p className="exp-rest-info" role="status">
              {socketStatus === "open"
                ? "正在获取最新的实验状态。"
                : "连接中断，正在重新连接。请保持页面打开。"}
            </p>
          </div>
        </div>
      ) : (
        <div className="exp-centered">
          <div className="exp-end-card">
            <h1 className="exp-rest-title">正在准备实验…</h1>
            <p className="exp-rest-info" role="status">
              正在等待服务器同步实验状态。
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
