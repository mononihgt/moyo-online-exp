import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CalendarPlus,
  ClipboardCheck,
  LogOut,
  PlayCircle,
  RefreshCw,
  XCircle,
} from "lucide-react";
import { Link, useLocation } from "react-router-dom";

import { formatDateTime } from "../shared/format";
import type { BookableRoom, CurrentRoom } from "../shared/types";
import type {
  BookableRoomsResponse,
  MyRoomResponse,
  PendingQuestionnaire,
} from "./apiTypes";
import { ROOM_STATUS_LABELS, formatUnknownError, isUnauthorized } from "./apiTypes";
import { LoadingCard, PageLinks, StatusChip } from "./common";
import { ContinueQuestionnaireButton } from "./ContinueQuestionnaireButton";
import {
  ACCOUNT_COMPLETED,
  ACCOUNT_DISABLED,
  ACCOUNT_PENDING_QUESTIONNAIRE,
  AFTER_START_BOOKING_NOTE,
  BOOKABLE_HIDDEN_NOTE,
  BOOKING_SUCCESS,
  CANCEL_SUCCESS,
  PENDING_QUESTIONNAIRE_ARCHIVED_DETAIL,
  PENDING_QUESTIONNAIRE_DETAIL,
  PENDING_QUESTIONNAIRE_TITLE,
  SELF_SUBMITTED_DETAIL,
  SELF_SUBMITTED_TITLE,
  VIEW_REWARD_INFO,
} from "./flowCopy";
import { PageFrame, SessionNotice, useSession } from "./session";
import { useNow, formatClock, secondsLeft } from "./time";

const STARTED_STATUSES = ["waiting", "instructions", "playing", "questionnaire"];

export default function HomePage() {
  const session = useSession();
  const location = useLocation();
  const notice = (location.state as { notice?: string } | null)?.notice ?? "";
  const [room, setRoom] = useState<CurrentRoom | null>(null);
  const [bookingId, setBookingId] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingQuestionnaire[]>([]);
  const [rooms, setRooms] = useState<BookableRoom[]>([]);
  const [serverNow, setServerNow] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionNotice, setActionNotice] = useState("");
  const [selectedRoomId, setSelectedRoomId] = useState<string | null>(null);
  const [booking, setBooking] = useState(false);
  const [canceling, setCanceling] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const now = useNow(1000);

  const load = useCallback(
    async (alive: { current: boolean }) => {
      setLoadError("");
      try {
        const myRoom = await session.request<MyRoomResponse>("/api/my-room");
        if (!alive.current) return;
        setRoom(myRoom.room);
        setBookingId(myRoom.bookingId ?? null);
        setPending(myRoom.pendingQuestionnaires ?? []);
        if (session.me.canBook) {
          const bookable = await session.request<BookableRoomsResponse>("/api/rooms/bookable");
          if (!alive.current) return;
          setRooms(bookable.rooms);
          setServerNow(bookable.serverNow);
        } else {
          setRooms([]);
          setServerNow(null);
        }
      } catch (error: unknown) {
        if (!alive.current || isUnauthorized(error)) return;
        setLoadError(formatUnknownError(error, "无法加载预约信息，请稍后重试。"));
      } finally {
        if (alive.current) setLoading(false);
      }
    },
    [session],
  );

  useEffect(() => {
    const alive = { current: true };
    setLoading(true);
    void load(alive);
    return () => {
      alive.current = false;
    };
  }, [load, reloadToken]);

  const selectedRoom = useMemo(
    () => rooms.find((candidate) => candidate.id === selectedRoomId) ?? null,
    [rooms, selectedRoomId],
  );

  useEffect(() => {
    if (selectedRoomId !== null && selectedRoom === null) {
      setSelectedRoomId(null);
    }
  }, [selectedRoom, selectedRoomId]);

  const offsetMs = useMemo(
    () => (serverNow === null ? 0 : Date.parse(serverNow) - Date.now()),
    [serverNow],
  );
  const startRemaining =
    room === null ? null : secondsLeft(room.startsAt, now, offsetMs);
  const canEnterNow =
    room !== null &&
    (room.canEnter ||
      (startRemaining === 0 &&
        (room.status === "open" || room.status === "full")));
  const bookingStarted =
    room !== null &&
    (startRemaining === 0 ||
      STARTED_STATUSES.includes(room.status) ||
      (!room.canCancel && room.bookingStatus === "booked"));

  const activePending = useMemo<PendingQuestionnaire | null>(() => {
    if (
      room === null ||
      room.status !== "questionnaire" ||
      room.questionnaireStatus === "completed"
    ) {
      return null;
    }
    return {
      roomId: room.roomId,
      startsAt: room.startsAt,
      questionnaireStatus: room.questionnaireStatus ?? "not_started",
      archiveReason: null,
      canContinue: true,
    };
  }, [room]);

  const pendingItems = useMemo(() => {
    const seen = new Set<string>();
    const items: PendingQuestionnaire[] = [];
    const candidates = activePending === null ? pending : [activePending, ...pending];
    for (const item of candidates) {
      if (seen.has(item.roomId)) continue;
      if (!item.canContinue) continue;
      if (item.questionnaireStatus === "completed") continue;
      seen.add(item.roomId);
      items.push(item);
    }
    return items;
  }, [activePending, pending]);

  const hasPending = pendingItems.length > 0;
  const pendingLocked = hasPending || session.me.hasPendingQuestionnaire;
  const selfCompletedPartnerPending =
    room !== null &&
    room.status === "questionnaire" &&
    room.questionnaireStatus === "completed";
  const activeRoomIsPending =
    room !== null && pendingItems.some((item) => item.roomId === room.roomId);
  const showCurrentRoomCard =
    room !== null && !activeRoomIsPending && !selfCompletedPartnerPending;
  const accountLocked =
    session.me.isCompleted || session.me.isDisabled || !session.me.canBook;

  const bookRoom = async () => {
    if (selectedRoom === null || booking) return;
    setActionError("");
    setActionNotice("");
    setBooking(true);
    try {
      await session.request(`/api/rooms/${selectedRoom.id}/book`, { method: "POST" });
      setSelectedRoomId(null);
      setActionNotice(BOOKING_SUCCESS);
      setLoading(true);
      setReloadToken((token) => token + 1);
    } catch (error: unknown) {
      if (isUnauthorized(error)) return;
      setActionError(formatUnknownError(error, "预约失败，请稍后重试。"));
    } finally {
      setBooking(false);
    }
  };

  const cancelBooking = async () => {
    if (bookingId === null || canceling) return;
    setActionError("");
    setActionNotice("");
    setCanceling(true);
    try {
      await session.request(`/api/bookings/${bookingId}/cancel`, { method: "POST" });
      setActionNotice(CANCEL_SUCCESS);
      setLoading(true);
      setReloadToken((token) => token + 1);
    } catch (error: unknown) {
      if (isUnauthorized(error)) return;
      setActionError(formatUnknownError(error, "取消预约失败，请稍后重试。"));
    } finally {
      setCanceling(false);
    }
  };

  const logout = async () => {
    try {
      await session.logout();
    } catch (error: unknown) {
      if (isUnauthorized(error)) return;
      setActionError(formatUnknownError(error, "退出登录失败，请稍后重试。"));
    }
  };

  const blockingHint =
    room !== null && !bookingStarted
      ? "你已有预约。如需改报其他场次，请先取消当前预约。"
      : null;

  const showBookable =
    session.me.canBook && !pendingLocked && !selfCompletedPartnerPending;
  const showHiddenBookable = pendingLocked;

  return (
    <PageFrame>
      <header className="p-topbar">
        <div className="p-topbar-identity">
          <span className="p-topbar-name">{session.me.name}</span>
          <span className="p-topbar-phone">{session.me.phoneMasked}</span>
        </div>
        <div className="p-topbar-actions">
          <button
            type="button"
            className="p-linkish p-topbar-logout"
            onClick={() => void logout()}
          >
            <LogOut size={16} aria-hidden="true" />
            退出登录
          </button>
        </div>
      </header>

      <SessionNotice text={notice} />
      {actionNotice !== "" ? (
        <div className="p-banner p-banner-success" role="status">
          {actionNotice}
        </div>
      ) : null}
      {actionError !== "" ? (
        <div className="p-banner p-banner-error" role="alert">
          {actionError}
        </div>
      ) : null}

      {loading ? (
        <LoadingCard text="正在加载预约信息…" />
      ) : loadError !== "" ? (
        <div className="p-card">
          <div className="p-banner p-banner-error" role="alert">
            {loadError}
          </div>
          <button
            type="button"
            className="p-btn p-btn-secondary"
            onClick={() => {
              setLoading(true);
              setReloadToken((token) => token + 1);
            }}
          >
            <RefreshCw size={16} aria-hidden="true" />
            重新加载
          </button>
        </div>
      ) : (
        <>
          {pendingItems.map((item, index) => {
            const archived = item.archiveReason === "questionnaire_incomplete";
            return (
              <section
                key={item.roomId}
                className="p-card p-pending-questionnaire"
                data-testid="pending-questionnaire-card"
                aria-labelledby={`pending-questionnaire-title-${index}`}
              >
                <div className="p-row">
                  <h2
                    className="p-section-title"
                    id={`pending-questionnaire-title-${index}`}
                  >
                    {PENDING_QUESTIONNAIRE_TITLE}
                  </h2>
                  <StatusChip tone="warning">
                    {archived ? "已归档" : "待填写"}
                  </StatusChip>
                </div>
                <p className="p-muted">{formatDateTime(item.startsAt)}</p>
                <div className="p-banner p-banner-warning" role="status">
                  {archived
                    ? PENDING_QUESTIONNAIRE_ARCHIVED_DETAIL
                    : PENDING_QUESTIONNAIRE_DETAIL}
                </div>
                <div className="p-btn-row">
                  <ContinueQuestionnaireButton
                    roomId={item.roomId}
                    testId={
                      index === 0
                        ? "continue-questionnaire"
                        : `continue-questionnaire-${item.roomId}`
                    }
                  />
                  <Link
                    className="p-btn p-btn-secondary"
                    data-testid="reward-info"
                    to={`/complete?room=${encodeURIComponent(item.roomId)}`}
                  >
                    {VIEW_REWARD_INFO}
                  </Link>
                </div>
              </section>
            );
          })}

          {showCurrentRoomCard && room !== null ? (
            <section
              className="p-card p-current-booking"
              data-testid="current-booking"
              aria-labelledby="current-booking-title"
            >
              <div className="p-row">
                <h2 className="p-section-title" id="current-booking-title">
                  当前预约
                </h2>
                <StatusChip
                  tone={
                    room.status === "questionnaire"
                      ? "warning"
                      : STARTED_STATUSES.includes(room.status)
                        ? "success"
                        : "neutral"
                  }
                >
                  {ROOM_STATUS_LABELS[room.status]}
                </StatusChip>
              </div>
              <dl className="p-detail-list">
                <div className="p-detail-row">
                  <dt>开始时间</dt>
                  <dd>{formatDateTime(room.startsAt)}</dd>
                </div>
                <div className="p-detail-row">
                  <dt>预约人数</dt>
                  <dd>
                    {room.bookedCount}/{room.capacity}
                  </dd>
                </div>
                {startRemaining !== null && !canEnterNow ? (
                  <div className="p-detail-row">
                    <dt>距离开始</dt>
                    <dd className="p-mono">{formatClock(startRemaining)}</dd>
                  </div>
                ) : null}
                <div className="p-detail-row">
                  <dt>预约状态</dt>
                  <dd>{ROOM_STATUS_LABELS[room.status]}</dd>
                </div>
              </dl>

              <div className="p-btn-row">
                {canEnterNow ? (
                  <Link
                    className="p-btn p-btn-primary"
                    to={`/room/${room.roomId}`}
                    data-testid="enter-room"
                  >
                    <PlayCircle size={18} aria-hidden="true" />
                    进入实验
                  </Link>
                ) : null}
                {room.canCancel && bookingId !== null ? (
                  <button
                    type="button"
                    className="p-btn p-btn-secondary"
                    data-testid="cancel-booking"
                    disabled={canceling}
                    onClick={() => void cancelBooking()}
                  >
                    <XCircle size={18} aria-hidden="true" />
                    {canceling ? "正在取消…" : "取消预约"}
                  </button>
                ) : null}
              </div>
              {bookingStarted ? (
                <p className="p-muted p-current-booking-note">
                  {AFTER_START_BOOKING_NOTE}
                </p>
              ) : room.canCancel ? (
                <p className="p-muted p-current-booking-note">
                  开始时间到达后才能进入实验。开始前可以取消预约。
                </p>
              ) : (
                <p className="p-muted p-current-booking-note">
                  开始时间到达后才能进入实验。
                </p>
              )}
            </section>
          ) : null}

          {selfCompletedPartnerPending ? (
            <section
              className="p-card p-current-booking"
              data-testid="experiment-completed"
              aria-labelledby="experiment-completed-title"
            >
              <h2 className="p-section-title" id="experiment-completed-title">
                {SELF_SUBMITTED_TITLE}
              </h2>
              <p className="p-muted">{SELF_SUBMITTED_DETAIL}</p>
              <div className="p-btn-row">
                <Link
                  className="p-btn p-btn-primary"
                  data-testid="reward-info"
                  to={`/complete?room=${encodeURIComponent(room.roomId)}`}
                >
                  <ClipboardCheck size={18} aria-hidden="true" />
                  {VIEW_REWARD_INFO}
                </Link>
                <Link className="p-btn p-btn-secondary" to="/history">
                  历史实验
                </Link>
              </div>
            </section>
          ) : null}

          {!showCurrentRoomCard &&
          !hasPending &&
          !selfCompletedPartnerPending ? (
            <section
              className="p-card p-current-booking p-card-quiet"
              data-testid="current-booking"
            >
              <h2 className="p-section-title">当前预约</h2>
              <p className="p-muted">
                你当前没有预约。
                {session.me.canBook
                  ? "请在下方选择一个开始时间完成预约。"
                  : "当前账号无法预约新的场次。"}
              </p>
            </section>
          ) : null}

          {accountLocked ? (
            <section className="p-card p-account-status" aria-labelledby="account-status-title">
              <h2 className="p-section-title" id="account-status-title">
                预约状态
              </h2>
              <p className="p-muted">
                {session.me.isCompleted
                  ? ACCOUNT_COMPLETED
                  : session.me.isDisabled
                    ? ACCOUNT_DISABLED
                    : pendingLocked
                      ? ACCOUNT_PENDING_QUESTIONNAIRE
                      : "你当前无法预约新的场次。如有疑问，请联系实验主试。"}
              </p>
            </section>
          ) : null}

          {showHiddenBookable ? (
            <section className="p-card" data-testid="bookable-hidden" aria-labelledby="bookable-hidden-title">
              <h2 className="p-section-title" id="bookable-hidden-title">
                可预约场次
              </h2>
              <div className="p-banner p-banner-info" role="status">
                {BOOKABLE_HIDDEN_NOTE}
              </div>
            </section>
          ) : null}

          {showBookable ? (
            <section className="p-card" aria-labelledby="bookable-title">
              <div className="p-row">
                <h2 className="p-section-title" id="bookable-title">
                  可预约场次
                </h2>
                <span className="p-muted">
                  {serverNow !== null ? "Beijing UTC+8" : ""}
                </span>
              </div>
              {blockingHint !== null ? (
                <div className="p-banner p-banner-info" role="status">
                  {blockingHint}
                </div>
              ) : null}
              {rooms.length === 0 ? (
                <div className="p-empty">当前没有可预约的场次，请稍后再来查看。</div>
              ) : (
                <div className="p-room-grid" role="group" aria-label="可预约场次">
                  {rooms.map((candidate) => {
                    const disabled = !candidate.canBook;
                    const selected = candidate.id === selectedRoomId;
                    return (
                      <button
                        key={candidate.id}
                        type="button"
                        className={
                          selected
                            ? "p-room-button p-room-option-selected"
                            : "p-room-button"
                        }
                        data-testid="room-option"
                        data-room-id={candidate.id}
                        disabled={disabled}
                        aria-pressed={selected}
                        onClick={() => {
                          setActionError("");
                          setActionNotice("");
                          setSelectedRoomId(selected ? null : candidate.id);
                        }}
                      >
                        <span className="p-room-time">
                          {formatDateTime(candidate.startsAt)}
                        </span>
                        <span className="p-room-count">
                          {candidate.full
                            ? "已满"
                            : `${candidate.bookedCount}/${candidate.capacity} 已预约`}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}

              {selectedRoom !== null ? (
                <div className="p-booking-confirm">
                  <div>
                    <p className="p-label">已选择场次</p>
                    <p>{formatDateTime(selectedRoom.startsAt)}</p>
                    <p className="p-muted">
                      确认预约后如需修改时间，请先取消当前预约。实验开始前可以取消。
                    </p>
                  </div>
                  <div className="p-btn-row">
                    <button
                      type="button"
                      className="p-btn p-btn-primary"
                      data-testid="book-room"
                      disabled={booking || !selectedRoom.canBook}
                      onClick={() => void bookRoom()}
                    >
                      <CalendarPlus size={18} aria-hidden="true" />
                      {booking ? "正在预约…" : "确认预约"}
                    </button>
                    <button
                      type="button"
                      className="p-btn p-btn-secondary"
                      disabled={booking}
                      onClick={() => setSelectedRoomId(null)}
                    >
                      取消选择
                    </button>
                  </div>
                </div>
              ) : null}
            </section>
          ) : null}

          <PageLinks items={["history", "contact"]} />
        </>
      )}
    </PageFrame>
  );
}
