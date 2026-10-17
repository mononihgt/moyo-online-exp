import { useCallback, useEffect, useRef, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";

import type {
  ArchiveReason,
  GameState,
  InstructionState,
  PartnerState,
  RoomStateMessage,
  ServerMessage,
  TrialStartMessage,
  TurnMessage,
  TurnResultMessage,
} from "../shared/types";
import { ArchiveView, NoRoomView, QuestionnaireView } from "./EndViews";
import type { QuestionnaireViewInfo } from "./EndViews";
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

const RESULT_DISPLAY_MS = 1200;
const FULLSCREEN_NOTICE = "浏览器未进入全屏，实验将继续";
const FULLSCREEN_EXIT_NOTICE = "已退出全屏，实验继续";

interface RoomError {
  code: string;
  message: string;
}

interface ArchiveInfo {
  reason: ArchiveReason | null;
  canRebook: boolean;
}

function deriveRestFromGame(game: GameState): RestViewData {
  return {
    completedIsPractice: game.isPractice,
    completedFormalTrial: game.formalTrial,
    nextTrialIndex: -1,
    nextIsPractice:
      game.isPractice === false && game.formalTrial !== null ? false : null,
    nextFormalTrial:
      game.isPractice === false && game.formalTrial !== null
        ? game.formalTrial + 1
        : null,
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
    isPractice: current?.isPractice ?? null,
    formalTrial: current?.formalTrial ?? null,
    round: message.round,
    turnCount: message.turnCount ?? current?.turnCount ?? 0,
    turnSeconds: message.turnSeconds ?? current?.turnSeconds ?? 30,
    restSeconds: current?.restSeconds ?? 0,
    board: message.board,
    visuals: current?.visuals ?? [],
    turnDeadline: message.deadline,
    restDeadline: null,
    submitted: message.submitted,
    partnerSubmitted: message.partnerSubmitted,
    restReady: {},
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
    isPractice: message.isPractice,
    formalTrial: message.formalTrial,
    round: message.round,
    turnCount: message.turnCount,
    turnSeconds: message.turnSeconds,
    restSeconds: current?.restSeconds ?? 0,
    board: message.board,
    visuals: message.visuals,
    turnDeadline: null,
    restDeadline: null,
    submitted: false,
    partnerSubmitted: false,
    restReady: {},
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
  const [formalTrialTotal, setFormalTrialTotal] = useState<number | null>(null);
  const firstFormalSeenRef = useRef(false);
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
          setArchive({ reason: null, canRebook: true });
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
            if (snapshot.isPractice === false && !firstFormalSeenRef.current) {
              firstFormalSeenRef.current = true;
              setFormalTrialTotal(
                Math.max(1, snapshot.totalTrials - 1),
              );
            }
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
            setArchive({
              reason,
              canRebook:
                message.archive?.canRebook ?? reason !== "completed",
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
                  restDeadline: message.deadline,
                  restReady: message.ready,
                },
          );
          break;
        }
        case "trial_start": {
          if (!("trialIndex" in message)) break;
          if (message.isPractice === false && !firstFormalSeenRef.current) {
            firstFormalSeenRef.current = true;
            setFormalTrialTotal(
              message.totalTrials - Math.max(0, message.gameNumber - 1),
            );
          }
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
          setArchive({
            reason: message.reason,
            canRebook: message.canRebook ?? message.reason !== "completed",
          });
          setTerminal(true);
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

  const { status: socketStatus, send } = useRoomSocket(
    roomId,
    roomId !== "" && !terminal,
    handleMessage,
  );

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
    const timer = window.setTimeout(() => setResult(null), RESULT_DISPLAY_MS);
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

  useEffect(() => {
    if (archive !== null && exitPending) {
      navigate("/", {
        replace: true,
        state: { notice: "你已退出本次实验，可以重新预约。" },
      });
    }
  }, [archive, exitPending, navigate]);

  if (roomId === "") {
    return <Navigate to="/" replace />;
  }

  const startRequested =
    startRequestedLocal || roomState?.self.startRequested === true;
  const sentSubmit = send;

  const handleStartMatching = () => {
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
    if (game === null) return;
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
          reason: roomState.archiveReason,
          canRebook: roomState.archiveReason !== "completed",
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
    socketStatus !== "open" &&
    phaseKind !== "turn" &&
    phaseKind !== "rest" &&
    phaseKind !== "connecting";

  return (
    <div className={rootClass} ref={shellRef}>
      {connectionNoticeVisible ? (
        <div className="exp-notice-stack" role="status">
          <div className="exp-notice exp-notice-status">
            连接中断，正在重新连接。请保持页面打开。
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
          formalTrialTotal={formalTrialTotal}
          submitted={submittedLocal || game.submitted}
          onSubmit={handleSubmitSelection}
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
          onReady={handleRestReady}
        />
      ) : phaseKind === "waiting" && roomState !== null ? (
        <WaitingView
          roomState={roomState}
          serverOffsetMs={serverOffsetMs}
          startRequested={startRequested}
          actionPending={exitPending}
          errorCode={waitErrorCode}
          onStart={handleStartMatching}
          onExit={handleExitRoom}
          onHome={() => navigate("/")}
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
          onComplete={handleInstructionComplete}
          onEnterGame={handleEnterGame}
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
              正在等待服务器同步房间状态。
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
