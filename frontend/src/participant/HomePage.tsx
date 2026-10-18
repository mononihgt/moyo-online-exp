import { useCallback, useEffect, useMemo, useState } from "react";
import { CalendarPlus, ClipboardList, LogOut, Mail, PlayCircle, RefreshCw, XCircle } from "lucide-react";
import { Link, useLocation } from "react-router-dom";

import { formatDateTime } from "../shared/format";
import type { BookableRoom, CurrentRoom } from "../shared/types";
import type {
  BookableRoomsResponse,
  MyRoomResponse,
  PendingQuestionnaire,
  QuestionnaireContextResponse,
} from "./apiTypes";
import { ROOM_STATUS_LABELS, formatUnknownError, isUnauthorized } from "./apiTypes";
import { LoadingCard, PageLinks, StatusChip } from "./common";
import { PageFrame, SessionNotice, useSession } from "./session";
import { useNow, formatClock, secondsLeft } from "./time";

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
  const [continuing, setContinuing] = useState(false);
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

  const bookRoom = async () => {
    if (selectedRoom === null || booking) return;
    setActionError("");
    setActionNotice("");
    setBooking(true);
    try {
      await session.request(`/api/rooms/${selectedRoom.id}/book`, { method: "POST" });
      setSelectedRoomId(null);
      setActionNotice("预约成功。请在开始时间前进入等待。");
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
      setActionNotice("已取消预约。你可以重新选择场次。");
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

  const continueQuestionnaire = async (roomId: string) => {
    if (continuing) return;
    setActionError("");
    setContinuing(true);
    try {
      const context = await session.request<QuestionnaireContextResponse>(
        `/api/questionnaire/context?roomId=${encodeURIComponent(roomId)}`,
      );
      if (context.submitted) {
        setActionError("该实验的问卷已提交。");
        return;
      }
      if (context.url === null) {
        setActionError("暂时无法生成问卷链接，请联系实验主试。");
        return;
      }
      window.location.href = context.url;
    } catch (error: unknown) {
      if (!isUnauthorized(error)) {
        setActionError(
          formatUnknownError(error, "无法继续填写问卷，请联系实验主试。"),
        );
      }
    } finally {
      setContinuing(false);
    }
  };

  const activeRoomId = room?.roomId ?? null;
  const extraPending = pending.filter((item) => item.roomId !== activeRoomId);
  const blockingHint =
    room !== null
      ? "你已有预约。如需改报其他场次，请先取消当前预约。"
      : null;

  return (
    <PageFrame>
      <header className="p-topbar">
        <div className="p-topbar-identity">
          <span className="p-topbar-name">{session.me.name}</span>
          <span className="p-topbar-phone">{session.me.phoneMasked}</span>
        </div>
        <div className="p-topbar-actions">
          <Link className="p-nav-link" to="/history">
            <ClipboardList size={16} aria-hidden="true" />
            历史实验
          </Link>
          <Link className="p-nav-link" to="/contact">
            <Mail size={16} aria-hidden="true" />
            联系主试
          </Link>
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
          {room !== null ? (
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
                      : room.status === "waiting" ||
                          room.status === "instructions" ||
                          room.status === "playing"
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
              </dl>

              {room.status === "questionnaire" &&
              room.questionnaireStatus !== "completed" ? (
                <div className="p-banner p-banner-warning" role="status">
                  实验已结束，仍需填写后测问卷。完成后才能确认实验记录与报酬。
                </div>
              ) : null}

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
                {room.status === "questionnaire" &&
                room.questionnaireStatus !== "completed" ? (
                  <button
                    type="button"
                    className={
                      canEnterNow
                        ? "p-btn p-btn-secondary"
                        : "p-btn p-btn-primary"
                    }
                    data-testid="continue-questionnaire"
                    disabled={continuing}
                    onClick={() => void continueQuestionnaire(room.roomId)}
                  >
                    继续填写问卷
                  </button>
                ) : null}
                {!canEnterNow && bookingId !== null ? (
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
                {!canEnterNow && bookingId === null ? (
                  <Link className="p-btn p-btn-secondary" to={`/room/${room.roomId}`}>
                    查看房间状态
                  </Link>
                ) : null}
              </div>
              {!canEnterNow ? (
                <p className="p-muted p-current-booking-note">
                  开始时间到达后才能进入实验。开始前可以取消预约。
                </p>
              ) : null}
            </section>
          ) : (
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
          )}

          {extraPending.length > 0 ? (
            <section className="p-card" aria-labelledby="pending-questionnaire-title">
              <h2 className="p-section-title" id="pending-questionnaire-title">
                待完成问卷
              </h2>
              <ul className="p-list">
                {extraPending.map((item) => (
                  <li key={item.roomId} className="p-row">
                    <span>{formatDateTime(item.startsAt)}</span>
                    <button
                      type="button"
                      className="p-linkish"
                      disabled={continuing}
                      onClick={() => void continueQuestionnaire(item.roomId)}
                    >
                      继续填写问卷
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {session.me.isCompleted || session.me.isDisabled || !session.me.canBook ? (
            <section className="p-card p-account-status" aria-labelledby="account-status-title">
              <h2 className="p-section-title" id="account-status-title">
                预约状态
              </h2>
              <p className="p-muted">
                {session.me.isCompleted
                  ? "你已完成全部实验，无法再预约新的场次。你可以查看历史实验与报酬记录。"
                  : session.me.isDisabled
                    ? "你的账号当前已停用，无法预约新的场次。如有疑问，请联系实验主试。"
                    : "你当前无法预约新的场次。如有疑问，请联系实验主试。"}
              </p>
            </section>
          ) : (
            <section className="p-card" aria-labelledby="bookable-title">
              <div className="p-row">
                <h2 className="p-section-title" id="bookable-title">
                  可预约场次
                </h2>
                <span className="p-muted">
                  {serverNow !== null ? "时间为北京时间" : ""}
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
                      预约后如需改报，请先取消当前预约。实验开始前可以取消。
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
          )}

          <PageLinks items={["history", "contact"]} />
        </>
      )}
    </PageFrame>
  );
}
