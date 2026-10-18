import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Activity,
  Archive,
  CheckCircle2,
  ClipboardList,
  Copy,
  Database,
  Download,
  ExternalLink,
  Eye,
  FileJson,
  LayoutDashboard,
  RefreshCw,
  Search,
  Send,
  TimerReset,
  UserPlus,
  UserX,
  Wallet,
} from "lucide-react";
import type {
  AdminBooking,
  AdminRoomParticipant,
  ArchiveReason,
  Payment,
  RoomDetail,
  RoomMonitor,
} from "../../shared/types";
import {
  formatCountdown,
  formatDateTime,
  formatDuration,
  formatMoney,
  secondsUntil,
} from "../../shared/format";
import { adminApi, adminDownload, errorMessage } from "../api";
import type {
  ParticipantListResponse,
  QuestionnaireLink,
  ResendQuestionnaireResponse,
} from "../types";
import {
  BookingStatusChip,
  EmptyState,
  ErrorNotice,
  Field,
  InlineNotice,
  JsonDetails,
  LoadingBlock,
  Modal,
  PageHeader,
  ParticipantStatusChip,
  PaymentStatusChip,
  QuestionnaireStatusChip,
  RoomStatusChip,
  centsFromYuan,
  useNow,
  useUi,
  yuanFromCents,
} from "../ui";
import {
  ARCHIVE_REASON_LABELS,
  BOOKING_STATUS_LABELS,
  PARTICIPANT_STATUS_LABELS,
  PAYMENT_STATUS_LABELS,
  archiveReasonOptionsForStatus,
  defaultArchiveReasonForStatus,
  phaseLabel,
} from "../labels";
import {
  RoomConfigFields,
  buildRoomPayload,
  roomFormFromSummary,
  usePublishedOptions,
} from "../roomForm";
import type { RoomFormState } from "../roomForm";

type TabKey = "overview" | "bookings" | "monitor" | "data" | "payments";

const TABS: { key: TabKey; label: string }[] = [
  { key: "overview", label: "概览" },
  { key: "bookings", label: "预约" },
  { key: "monitor", label: "监控" },
  { key: "data", label: "数据" },
  { key: "payments", label: "付款" },
];

const EDITABLE_STATUSES = ["draft", "open", "full", "waiting"];

function findBookingForParticipant(
  detail: RoomDetail,
  participant: AdminRoomParticipant | { role: number; name: string },
): AdminBooking | undefined {
  const detailParticipant = detail.participants.find(
    (item) => item.role === participant.role && item.name === participant.name,
  );
  const candidates = detail.bookings.filter((booking) => booking.status !== "canceled");
  if (detailParticipant) {
    const exact = candidates.find(
      (booking) =>
        booking.name === detailParticipant.name &&
        booking.phoneMasked === detailParticipant.phoneMasked,
    );
    if (exact) return exact;
  }
  return candidates.find((booking) => booking.name === participant.name);
}

export function RoomDetailPage() {
  const { roomId = "" } = useParams();
  const { notify, confirm } = useUi();
  const { options } = usePublishedOptions();
  const now = useNow(1000);

  const [detail, setDetail] = useState<RoomDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);
  const [tab, setTab] = useState<TabKey>("overview");

  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState<RoomFormState | null>(null);
  const [editErrors, setEditErrors] = useState<Record<string, string>>({});
  const [editError, setEditError] = useState<string | null>(null);
  const [savingEdit, setSavingEdit] = useState(false);

  const [candidateQuery, setCandidateQuery] = useState("");
  const [candidates, setCandidates] = useState<
    { id: string; name: string; phoneMasked: string }[] | null
  >(null);
  const [selectedParticipantId, setSelectedParticipantId] = useState("");
  const [bookingError, setBookingError] = useState<string | null>(null);
  const [searchingParticipants, setSearchingParticipants] = useState(false);
  const [addingBooking, setAddingBooking] = useState(false);
  const [bookingBusy, setBookingBusy] = useState<string | null>(null);

  const [monitor, setMonitor] = useState<RoomMonitor | null>(null);
  const [monitorLoading, setMonitorLoading] = useState(false);
  const [monitorError, setMonitorError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [archiveReasonChoice, setArchiveReasonChoice] = useState<string | null>(null);
  const [extendOpen, setExtendOpen] = useState(false);
  const [extendMinutes, setExtendMinutes] = useState("5");
  const [extendError, setExtendError] = useState<string | null>(null);
  const [questionnaireLinks, setQuestionnaireLinks] = useState<QuestionnaireLink[]>([]);

  const [jatosParticipantId, setJatosParticipantId] = useState("");
  const [jatosWorkerId, setJatosWorkerId] = useState("");
  const [jatosStudyResultId, setJatosStudyResultId] = useState("");
  const [jatosComponentResultId, setJatosComponentResultId] = useState("");
  const [jatosAnswers, setJatosAnswers] = useState("");
  const [jatosError, setJatosError] = useState<string | null>(null);
  const [jatosSubmitting, setJatosSubmitting] = useState(false);

  const [paymentModal, setPaymentModal] = useState<{
    payment: Payment;
    amount: string;
    note: string;
  } | null>(null);
  const [paymentError, setPaymentError] = useState<string | null>(null);
  const [paymentSaving, setPaymentSaving] = useState(false);
  const [paymentBusy, setPaymentBusy] = useState<string | null>(null);

  const loadDetail = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await adminApi.get<RoomDetail>(`/rooms/${roomId}`);
      setDetail(response);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [roomId]);

  useEffect(() => {
    void loadDetail();
  }, [loadDetail, reloadNonce]);

  const refresh = useCallback(() => {
    setReloadNonce((value) => value + 1);
  }, []);

  const loadMonitor = useCallback(async () => {
    try {
      const response = await adminApi.get<RoomMonitor>(`/rooms/${roomId}/monitor`);
      setMonitor(response);
      setMonitorError(null);
    } catch (err) {
      setMonitorError(errorMessage(err));
    }
  }, [roomId]);

  useEffect(() => {
    if (tab !== "monitor") return;
    setMonitorLoading(true);
    void loadMonitor().finally(() => setMonitorLoading(false));
    const timer = window.setInterval(() => {
      void loadMonitor();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [tab, loadMonitor]);

  useEffect(() => {
    if (tab !== "bookings") return;
    let cancelled = false;
    setSearchingParticipants(true);
    adminApi
      .get<ParticipantListResponse>("/participants?status=eligible&limit=100")
      .then((response) => {
        if (!cancelled) {
          setCandidates(
            response.participants.map((participant) => ({
              id: participant.id,
              name: participant.name,
              phoneMasked: participant.phoneMasked,
            })),
          );
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) setBookingError(errorMessage(err));
      })
      .finally(() => {
        if (!cancelled) setSearchingParticipants(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tab]);

  const room = detail?.room ?? null;
  const canEdit = room !== null && EDITABLE_STATUSES.includes(room.status);
  const lockStartsAt = room !== null && room.status === "waiting";
  const roomStarted = room !== null && Date.parse(room.startsAt) <= Date.now();
  const archiveOptions =
    room === null ? [] : archiveReasonOptionsForStatus(room.status, roomStarted);
  const defaultArchiveReason =
    room === null
      ? "admin_aborted"
      : defaultArchiveReasonForStatus(room.status, roomStarted);
  const archiveReason: ArchiveReason =
    archiveReasonChoice !== null &&
    archiveOptions.includes(archiveReasonChoice as ArchiveReason)
      ? (archiveReasonChoice as ArchiveReason)
      : defaultArchiveReason;
  const canForceArchive = archiveOptions.length > 0;

  const participantNameById = useMemo(() => {
    const map = new Map<string, string>();
    if (!detail) return map;
    for (const booking of detail.bookings) {
      map.set(booking.participantId, booking.name);
    }
    return map;
  }, [detail]);

  function beginEdit() {
    if (!room) return;
    setEditForm(roomFormFromSummary(room));
    setEditErrors({});
    setEditError(null);
    setEditing(true);
  }

  async function saveEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editForm || !room) return;
    const result = buildRoomPayload(editForm);
    setEditErrors(result.errors);
    if (!result.payload) return;
    setSavingEdit(true);
    setEditError(null);
    try {
      const payload: Record<string, unknown> = { ...result.payload };
      if (room.status === "waiting") {
        delete payload.startsAt;
      }
      await adminApi.patch(`/rooms/${room.id}`, payload);
      notify("房间配置已保存");
      setEditing(false);
      refresh();
    } catch (err) {
      setEditError(errorMessage(err));
    } finally {
      setSavingEdit(false);
    }
  }

  async function searchParticipants(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSearchingParticipants(true);
    setBookingError(null);
    try {
      const params = new URLSearchParams();
      params.set("limit", "50");
      if (candidateQuery.trim()) params.set("query", candidateQuery.trim());
      else params.set("status", "eligible");
      const response = await adminApi.get<ParticipantListResponse>(`/participants?${params.toString()}`);
      setCandidates(
        response.participants.map((participant) => ({
          id: participant.id,
          name: participant.name,
          phoneMasked: participant.phoneMasked,
        })),
      );
      setSelectedParticipantId("");
    } catch (err) {
      setBookingError(errorMessage(err));
    } finally {
      setSearchingParticipants(false);
    }
  }

  async function addBooking(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!room) return;
    if (!selectedParticipantId) {
      setBookingError("请选择参与者");
      return;
    }
    setAddingBooking(true);
    setBookingError(null);
    try {
      await adminApi.post(`/rooms/${room.id}/bookings`, { participantId: selectedParticipantId });
      notify("预约已添加");
      setSelectedParticipantId("");
      refresh();
    } catch (err) {
      setBookingError(errorMessage(err));
    } finally {
      setAddingBooking(false);
    }
  }

  async function removeBooking(booking: AdminBooking) {
    if (!room) return;
    const ok = await confirm({
      title: "移除预约",
      message: `确认移除 ${booking.name} 的预约？移除后房间会重新开放对应名额。已产生的实验记录不会删除。`,
      confirmLabel: "移除预约",
      danger: true,
    });
    if (!ok) return;
    setBookingBusy(booking.id);
    try {
      await adminApi.delete(`/rooms/${room.id}/bookings/${booking.id}`);
      notify("预约已移除");
      refresh();
    } catch (err) {
      notify(errorMessage(err), "error");
    } finally {
      setBookingBusy(null);
    }
  }

  async function markAbsent(booking: AdminBooking) {
    if (!room) return;
    const ok = await confirm({
      title: "标记缺席",
      message: `确认将 ${booking.name} 标记为缺席？缺席记录的付款金额为 0，已有数据会保留。`,
      confirmLabel: "标记缺席",
      danger: true,
    });
    if (!ok) return;
    setBookingBusy(booking.id);
    try {
      await adminApi.post(`/rooms/${room.id}/actions`, {
        action: "mark_absent",
        participantId: booking.participantId,
      });
      notify("已标记缺席");
      refresh();
    } catch (err) {
      notify(errorMessage(err), "error");
    } finally {
      setBookingBusy(null);
    }
  }

  async function runAction(
    action: string,
    body: Record<string, unknown>,
    successMessage: string,
    busyKey: string,
  ): Promise<boolean> {
    if (!room) return false;
    setActionBusy(busyKey);
    try {
      await adminApi.post(`/rooms/${room.id}/actions`, { action, ...body });
      notify(successMessage);
      refresh();
      void loadMonitor();
      return true;
    } catch (err) {
      notify(errorMessage(err), "error");
      return false;
    } finally {
      setActionBusy(null);
    }
  }

  async function forceArchive() {
    if (!canForceArchive) return;
    const ok = await confirm({
      title: "强制归档",
      message: `确认强制归档「${room?.internalLabel ?? ""}」？归档原因：${ARCHIVE_REASON_LABELS[archiveReason]}。未完成问卷的参与者不会被自动标记完成。`,
      confirmLabel: "强制归档",
      danger: true,
    });
    if (!ok) return;
    await runAction("force_archive", { reason: archiveReason }, "房间已归档", "archive");
  }

  async function submitExtend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const minutes = Number(extendMinutes);
    if (!Number.isFinite(minutes) || minutes < 1 || minutes > 1440) {
      setExtendError("延长分钟数必须是 1 到 1440 之间的数字");
      return;
    }
    const ok = await runAction(
      "extend_wait",
      { minutes: Math.round(minutes) },
      `等待窗口已延长 ${Math.round(minutes)} 分钟`,
      "extend",
    );
    if (ok) {
      setExtendOpen(false);
      setExtendError(null);
    }
  }

  async function resendQuestionnaire() {
    if (!room) return;
    setActionBusy("resend");
    try {
      const response = await adminApi.post<ResendQuestionnaireResponse>(`/rooms/${room.id}/actions`, {
        action: "resend_questionnaire",
      });
      setQuestionnaireLinks(response.links);
      notify(`已生成 ${response.links.length} 个问卷链接`);
    } catch (err) {
      notify(errorMessage(err), "error");
    } finally {
      setActionBusy(null);
    }
  }

  async function markCompleted(participant: AdminRoomParticipant | { role: number; name: string }) {
    if (!detail) return;
    const booking = findBookingForParticipant(detail, participant);
    if (!booking) {
      notify("未找到该参与者的预约记录，无法标记完成", "error");
      return;
    }
    const ok = await confirm({
      title: "标记完成",
      message: `确认将 ${participant.name} 标记为已完成？此操作会修改参与者状态，但不会代替问卷提交。`,
      confirmLabel: "标记完成",
    });
    if (!ok) return;
    await runAction(
      "mark_completed",
      { participantId: booking.participantId },
      `${participant.name} 已标记完成`,
      `complete-${booking.participantId}`,
    );
    refresh();
  }

  async function disableParticipant(participant: AdminRoomParticipant | { role: number; name: string }) {
    if (!detail) return;
    const booking = findBookingForParticipant(detail, participant);
    if (!booking) {
      notify("未找到该参与者的预约记录，无法停用", "error");
      return;
    }
    const ok = await confirm({
      title: "停用参与者",
      message: `确认停用 ${participant.name}？停用后无法登录和报名，已有实验记录、预约和付款数据会保留。`,
      confirmLabel: "停用",
      danger: true,
    });
    if (!ok) return;
    await runAction(
      "disable_participant",
      { participantId: booking.participantId },
      `${participant.name} 已停用`,
      `disable-${booking.participantId}`,
    );
    refresh();
  }

  async function submitJatos(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!detail) return;
    setJatosError(null);
    if (!jatosParticipantId) {
      setJatosError("请选择参与者");
      return;
    }
    if (!jatosStudyResultId.trim() || !jatosComponentResultId.trim()) {
      setJatosError("JATOS study result ID 和 component result ID 必填");
      return;
    }
    let answers: unknown;
    try {
      answers = JSON.parse(jatosAnswers);
    } catch {
      setJatosError("问卷答案不是有效的 JSON");
      return;
    }
    if (answers === null || typeof answers !== "object" || Array.isArray(answers)) {
      setJatosError("问卷答案必须是 JSON 对象");
      return;
    }
    const participantName =
      detail.participants.find((item) => {
        const booking = findBookingForParticipant(detail, item);
        return booking?.participantId === jatosParticipantId;
      })?.name ?? jatosParticipantId;
    const ok = await confirm({
      title: "从 JATOS 补齐问卷结果",
      message: `确认用 JATOS 结果补齐 ${participantName} 的问卷？补齐后问卷会标记为完成，答案会写入平台副本，并清理该参与者的问卷草稿。`,
      confirmLabel: "补齐结果",
      danger: true,
    });
    if (!ok) return;
    setJatosSubmitting(true);
    try {
      await adminApi.post(`/rooms/${detail.room.id}/actions`, {
        action: "import_jatos_result",
        participantId: jatosParticipantId,
        jatosWorkerId: jatosWorkerId.trim() || undefined,
        jatosStudyResultId: jatosStudyResultId.trim(),
        jatosComponentResultId: jatosComponentResultId.trim(),
        answers,
      });
      notify("JATOS 结果已补齐");
      setJatosAnswers("");
      refresh();
    } catch (err) {
      setJatosError(errorMessage(err));
    } finally {
      setJatosSubmitting(false);
    }
  }

  function openPayment(payment: Payment) {
    setPaymentModal({
      payment,
      amount: yuanFromCents(payment.overrideAmountCents ?? payment.totalCents),
      note: payment.note ?? "",
    });
    setPaymentError(null);
  }

  async function savePayment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!paymentModal || !paymentModal.payment.id) return;
    const cents = centsFromYuan(paymentModal.amount);
    if (cents === null) {
      setPaymentError("覆盖金额必须是非负金额");
      return;
    }
    if (!paymentModal.note.trim()) {
      setPaymentError("覆盖金额必须填写备注");
      return;
    }
    const ok = await confirm({
      title: "覆盖付款金额",
      message: `确认将合计金额覆盖为 ${formatMoney(cents)}？\n备注：${paymentModal.note.trim()}`,
      confirmLabel: "覆盖金额",
      danger: true,
    });
    if (!ok) return;
    setPaymentSaving(true);
    setPaymentError(null);
    try {
      await adminApi.patch(`/payments/${paymentModal.payment.id}`, {
        overrideAmountCents: cents,
        adminNote: paymentModal.note.trim(),
      });
      notify("付款金额已覆盖");
      setPaymentModal(null);
      refresh();
    } catch (err) {
      setPaymentError(errorMessage(err));
    } finally {
      setPaymentSaving(false);
    }
  }

  async function markPaid(payment: Payment) {
    if (!payment.id) return;
    const ok = await confirm({
      title: "标记已支付",
      message: `确认将 ${formatMoney(payment.totalCents)} 标记为已支付？该操作会记录支付时间并写入审计日志。`,
      confirmLabel: "标记已支付",
    });
    if (!ok) return;
    setPaymentBusy(payment.id);
    try {
      await adminApi.patch(`/payments/${payment.id}`, {
        status: "paid",
        overrideAmountCents: payment.overrideAmountCents,
        adminNote: payment.note,
      });
      notify("已标记为已支付");
      refresh();
    } catch (err) {
      notify(errorMessage(err), "error");
    } finally {
      setPaymentBusy(null);
    }
  }

  async function markPending(payment: Payment) {
    if (!payment.id) return;
    const ok = await confirm({
      title: "设为待支付",
      message: "确认将该付款记录恢复为待支付？支付时间会清除。",
      confirmLabel: "设为待支付",
    });
    if (!ok) return;
    setPaymentBusy(payment.id);
    try {
      await adminApi.patch(`/payments/${payment.id}`, {
        status: "pending",
        overrideAmountCents: payment.overrideAmountCents,
        adminNote: payment.note,
      });
      notify("已设为待支付");
      refresh();
    } catch (err) {
      notify(errorMessage(err), "error");
    } finally {
      setPaymentBusy(null);
    }
  }

  async function downloadRoomJson() {
    if (!detail) return;
    try {
      await adminDownload(`/rooms/${detail.room.id}/export.json`, `room-${detail.room.id}.json`);
    } catch (err) {
      notify(errorMessage(err), "error");
    }
  }

  async function downloadAnalysisZip() {
    if (!detail) return;
    try {
      await adminDownload(`/rooms/${detail.room.id}/analysis.zip`, `analysis-${detail.room.id}.zip`);
    } catch (err) {
      notify(errorMessage(err), "error");
    }
  }

  async function copyLink(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      notify("链接已复制");
    } catch {
      notify("无法访问剪贴板，请手动复制链接", "error");
    }
  }

  if (loading && !detail) {
    return (
      <div>
        <PageHeader title="房间详情" subtitle="加载房间配置与运行状态。" />
        <LoadingBlock rows={8} label="正在加载房间详情" />
      </div>
    );
  }

  if (error && !detail) {
    return (
      <div>
        <PageHeader
          title="房间详情"
          actions={
            <Link className="admin-btn admin-btn-secondary" to="/admin/rooms">
              返回房间列表
            </Link>
          }
        />
        <ErrorNotice message={error} onRetry={() => void loadDetail()} />
      </div>
    );
  }

  if (!detail || !room) {
    return (
      <div>
        <PageHeader title="房间详情" />
        <EmptyState title="房间不存在" description="该房间可能已被删除。" />
      </div>
    );
  }

  const monitorParticipantRows =
    monitor?.participants.map((participant) => {
      const detailParticipant = detail.participants.find((item) => item.role === participant.role);
      return { monitor: participant, detail: detailParticipant };
    }) ?? [];

  return (
    <div>
      <PageHeader
        title={room.internalLabel}
        subtitle={`房间 ${room.id}`}
        actions={
          <div className="admin-btn-row">
            <Link className="admin-btn admin-btn-secondary" to="/admin/rooms">
              返回列表
            </Link>
            <button
              type="button"
              className="admin-btn admin-btn-primary"
              onClick={() => setTab("monitor")}
              data-testid="room-start-matching-monitor"
            >
              <Activity size={16} />
              打开监控
            </button>
          </div>
        }
      />

      <div className="admin-card admin-card-flat" style={{ padding: "14px 20px" }}>
        <div className="admin-stat-row">
          <div className="admin-chip-list">
            <RoomStatusChip status={room.status} />
            <span className="admin-hint">开始 {formatDateTime(room.startsAt)}</span>
            <span className="admin-hint">
              报名 {room.bookedCount}/{room.capacity}
            </span>
            <span className="admin-hint">
              条件 {room.condition.name} v{room.condition.version}
            </span>
            {room.configLockedAt ? (
              <span className="admin-hint">配置锁定 {formatDateTime(room.configLockedAt)}</span>
            ) : null}
          </div>
          {error ? <span className="admin-error">{error}</span> : null}
        </div>
      </div>

      <div className="admin-tabs" role="tablist" aria-label="房间详情分区">
        {TABS.map((entry) => (
          <button
            key={entry.key}
            type="button"
            role="tab"
            aria-selected={tab === entry.key}
            className={tab === entry.key ? "active" : undefined}
            onClick={() => setTab(entry.key)}
            data-testid={`room-tab-${entry.key}`}
          >
            {entry.label}
          </button>
        ))}
      </div>

      {tab === "overview" ? (
        <div className="admin-stack">
          <section className="admin-card">
            <div className="admin-stat-row" style={{ marginBottom: "16px" }}>
              <h2 className="admin-section-title" style={{ marginBottom: 0 }}>
                配置概览
              </h2>
              {canEdit && !editing ? (
                <button
                  type="button"
                  className="admin-btn admin-btn-secondary admin-btn-sm"
                  onClick={beginEdit}
                  data-testid="room-edit"
                >
                  编辑配置
                </button>
              ) : null}
            </div>

            {editing && editForm ? (
              <form onSubmit={saveEdit}>
                <InlineNotice tone="info">
                  {lockStartsAt
                    ? "房间已进入等待阶段，开始时间不可修改。其他配置变动会写入配置变更历史。"
                    : "保存后配置变动会写入配置变更历史。"}
                </InlineNotice>
                <RoomConfigFields
                  form={editForm}
                  errors={editErrors}
                  options={options}
                  onChange={setEditForm}
                  lockStartsAt={lockStartsAt}
                  disabled={savingEdit}
                />
                {editError ? <InlineNotice tone="error">{editError}</InlineNotice> : null}
                <div className="admin-form-actions">
                  <button
                    type="submit"
                    className="admin-btn admin-btn-primary"
                    disabled={savingEdit}
                    data-testid="room-edit-save"
                  >
                    {savingEdit ? "保存中" : "保存配置"}
                  </button>
                  <button
                    type="button"
                    className="admin-btn admin-btn-secondary"
                    onClick={() => setEditing(false)}
                    disabled={savingEdit}
                  >
                    取消
                  </button>
                </div>
              </form>
            ) : (
              <dl className="admin-detail-list">
                <div>
                  <dt>状态</dt>
                  <dd>
                    <RoomStatusChip status={room.status} />
                    {room.archiveReason ? (
                      <span className="admin-hint" style={{ marginLeft: "8px" }}>
                        {ARCHIVE_REASON_LABELS[room.archiveReason] ?? room.archiveReason}
                      </span>
                    ) : null}
                  </dd>
                </div>
                <div>
                  <dt>开始时间</dt>
                  <dd>{formatDateTime(room.startsAt)}</dd>
                </div>
                <div>
                  <dt>条件</dt>
                  <dd>
                    {room.condition.name} v{room.condition.version}
                  </dd>
                </div>
                <div>
                  <dt>玩家 1 指导语</dt>
                  <dd>
                    {room.instructions.player1.name} v{room.instructions.player1.version}
                  </dd>
                </div>
                <div>
                  <dt>玩家 2 指导语</dt>
                  <dd>
                    {room.instructions.player2.name} v{room.instructions.player2.version}
                  </dd>
                </div>
                <div>
                  <dt>问卷</dt>
                  <dd>
                    {room.questionnaire.name} v{room.questionnaire.version}
                  </dd>
                </div>
                <div>
                  <dt>基础费</dt>
                  <dd>{formatMoney(room.basePayCents)}</dd>
                </div>
                <div>
                  <dt>绩效单价</dt>
                  <dd>{formatMoney(room.performanceRateCents)} / 士兵</dd>
                </div>
                <div>
                  <dt>到场费</dt>
                  <dd>{formatMoney(room.showupPayCents)}</dd>
                </div>
                <div>
                  <dt>等待窗口</dt>
                  <dd>{formatDuration(room.waitWindowSeconds)}</dd>
                </div>
                <div>
                  <dt>重连窗口</dt>
                  <dd>{formatDuration(room.reconnectWindowSeconds)}</dd>
                </div>
                <div>
                  <dt>报名人数</dt>
                  <dd>
                    {room.bookedCount}/{room.capacity}
                  </dd>
                </div>
                <div>
                  <dt>发布时间</dt>
                  <dd>{formatDateTime(room.publishedAt)}</dd>
                </div>
                <div>
                  <dt>创建时间</dt>
                  <dd>{formatDateTime(room.createdAt)}</dd>
                </div>
              </dl>
            )}
          </section>

          <section className="admin-card">
            <h2 className="admin-section-title">配置变更历史</h2>
            {detail.configRevisions.length === 0 ? (
              <p className="admin-hint">暂无配置变更记录。</p>
            ) : (
              <div className="admin-table-wrap">
                <table className="admin-table admin-compact-table">
                  <thead>
                    <tr>
                      <th>版本</th>
                      <th>记录时间</th>
                      <th>配置</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...detail.configRevisions].reverse().map((revision) => (
                      <tr key={revision.revision}>
                        <td className="admin-mono">#{revision.revision}</td>
                        <td>{formatDateTime(revision.createdAt)}</td>
                        <td>
                          <JsonDetails value={revision.config} label="查看配置" />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="admin-card">
            <h2 className="admin-section-title">配置快照</h2>
            {detail.configSnapshot ? (
              <JsonDetails value={detail.configSnapshot} label="查看最终配置快照" />
            ) : (
              <p className="admin-hint">房间尚未锁定配置。进入指导语阶段时会生成配置快照。</p>
            )}
          </section>
        </div>
      ) : null}

      {tab === "bookings" ? (
        <div className="admin-stack">
          <section className="admin-card">
            <h2 className="admin-section-title">添加预约</h2>
            {!["open", "full"].includes(room.status) ? (
              <InlineNotice tone="warning">
                只有可报名或已满状态的房间可以添加预约。当前状态：{room.status}。
              </InlineNotice>
            ) : null}
            <form className="admin-inline-form" onSubmit={searchParticipants}>
              <Field label="按姓名搜索参与者" htmlFor="booking-search">
                <input
                  id="booking-search"
                  className="admin-input"
                  value={candidateQuery}
                  onChange={(event) => setCandidateQuery(event.target.value)}
                  placeholder="输入姓名或备注"
                />
              </Field>
              <button type="submit" className="admin-btn admin-btn-secondary" disabled={searchingParticipants}>
                <Search size={15} />
                {searchingParticipants ? "搜索中" : "搜索"}
              </button>
            </form>
            <form className="admin-inline-form" onSubmit={addBooking}>
              <Field label="选择参与者" htmlFor="booking-participant">
                <select
                  id="booking-participant"
                  className="admin-select"
                  value={selectedParticipantId}
                  onChange={(event) => setSelectedParticipantId(event.target.value)}
                  disabled={!["open", "full"].includes(room.status)}
                  data-testid="booking-participant"
                >
                  <option value="">请选择</option>
                  {(candidates ?? []).map((candidate) => (
                    <option key={candidate.id} value={candidate.id}>
                      {candidate.name}（{candidate.phoneMasked}）
                    </option>
                  ))}
                </select>
              </Field>
              <button
                type="submit"
                className="admin-btn admin-btn-primary"
                disabled={addingBooking || !["open", "full"].includes(room.status)}
                data-testid="booking-add-submit"
              >
                <UserPlus size={15} />
                {addingBooking ? "添加中" : "添加预约"}
              </button>
              <span className="admin-hint">
                {searchingParticipants ? "正在加载候选参与者" : `候选 ${candidates?.length ?? 0} 人`}
              </span>
            </form>
            {bookingError ? <InlineNotice tone="error">{bookingError}</InlineNotice> : null}
            <p className="admin-hint" style={{ marginBottom: 0 }}>
              参与者必须已签署当前知情同意书，且没有其他有效预约。
            </p>
          </section>

          <section className="admin-card">
            <div className="admin-stat-row" style={{ marginBottom: "16px" }}>
              <h2 className="admin-section-title" style={{ marginBottom: 0 }}>
                预约名单
              </h2>
              <span className="admin-hint">共 {detail.bookings.length} 条记录</span>
            </div>
            {detail.bookings.length === 0 ? (
              <EmptyState title="暂无预约" description="参与者报名或主试添加后会显示在这里。" />
            ) : (
              <div className="admin-table-wrap">
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>姓名</th>
                      <th>手机号</th>
                      <th>参与者状态</th>
                      <th>预约状态</th>
                      <th>到场时间</th>
                      <th>创建时间</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.bookings.map((booking) => (
                      <tr key={booking.id}>
                        <td>{booking.name}</td>
                        <td className="admin-mono">{booking.phoneMasked}</td>
                        <td>
                          <ParticipantStatusChip status={booking.participantStatus} />
                        </td>
                        <td>
                          <BookingStatusChip status={booking.status} />
                        </td>
                        <td>{formatDateTime(booking.attendedAt)}</td>
                        <td>{formatDateTime(booking.createdAt)}</td>
                        <td className="admin-actions-cell">
                          {["booked", "attended"].includes(booking.status) &&
                          !["instructions", "playing", "questionnaire", "archived"].includes(room.status) ? (
                            <button
                              type="button"
                              className="admin-btn admin-btn-ghost admin-btn-sm"
                              onClick={() => void removeBooking(booking)}
                              disabled={bookingBusy === booking.id}
                            >
                              移除
                            </button>
                          ) : null}
                          {!["no_show", "canceled"].includes(booking.status) ? (
                            <button
                              type="button"
                              className="admin-btn admin-btn-ghost admin-btn-sm"
                              onClick={() => void markAbsent(booking)}
                              disabled={bookingBusy === booking.id}
                            >
                              标记缺席
                            </button>
                          ) : null}
                          {room.status !== "archived" ? (
                            <>
                              <button
                                type="button"
                                className="admin-btn admin-btn-ghost admin-btn-sm"
                                onClick={() => void markCompleted({
                                  role: detail.participants.find(
                                    (item) => item.name === booking.name,
                                  )?.role ?? 1,
                                  name: booking.name,
                                })}
                                disabled={actionBusy !== null}
                              >
                                标记完成
                              </button>
                            </>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      ) : null}

      {tab === "monitor" ? (
        <div className="admin-stack">
          {monitorError ? <ErrorNotice message={monitorError} onRetry={() => void loadMonitor()} /> : null}
          {monitorLoading && !monitor ? <LoadingBlock rows={5} label="正在加载监控" /> : null}
          {monitor ? (
            <>
              <section className="admin-card">
                <div className="admin-stat-row" style={{ marginBottom: "16px" }}>
                  <h2 className="admin-section-title" style={{ marginBottom: 0 }}>
                    运行状态
                  </h2>
                  <span className="admin-hint">每 3 秒刷新</span>
                </div>
                <div className="admin-monitor-panel">
                  <div className="admin-monitor-stat">
                    <div className="admin-monitor-stat-label">阶段</div>
                    <div className="admin-monitor-stat-value">{phaseLabel(monitor.phase)}</div>
                  </div>
                  <div className="admin-monitor-stat">
                    <div className="admin-monitor-stat-label">Trial / 回合</div>
                    <div className="admin-monitor-stat-value">
                      {monitor.trialIndex === null || monitor.trialIndex === undefined
                        ? "—"
                        : monitor.trialIndex + 1}
                      {" / "}
                      {monitor.round ?? "—"}
                    </div>
                  </div>
                  <div className="admin-monitor-stat">
                    <div className="admin-monitor-stat-label">回合倒计时</div>
                    <div className="admin-timer-countdown">
                      {monitor.turnDeadline
                        ? formatCountdown(secondsUntil(monitor.turnDeadline, now))
                        : "—"}
                    </div>
                  </div>
                  <div className="admin-monitor-stat">
                    <div className="admin-monitor-stat-label">休息倒计时</div>
                    <div className="admin-timer-countdown">
                      {monitor.restDeadline
                        ? formatCountdown(secondsUntil(monitor.restDeadline, now))
                        : "—"}
                    </div>
                  </div>
                </div>
              </section>

              <section className="admin-card">
                <h2 className="admin-section-title">参与者</h2>
                {monitor.participants.length === 0 ? (
                  <EmptyState title="暂无房间参与者" description="指导语开始后会记录参与者。" />
                ) : (
                  <div className="admin-table-wrap">
                    <table className="admin-table">
                      <thead>
                        <tr>
                          <th>角色 / 姓名</th>
                          <th>在线</th>
                          <th>指导语</th>
                          <th>问卷</th>
                          <th>断线至</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {monitorParticipantRows.map(({ monitor: participant, detail: detailParticipant }) => (
                          <tr key={participant.role}>
                            <td>
                              玩家 {participant.role} · {participant.name}
                            </td>
                            <td>
                              {participant.online ? (
                                <span style={{ color: "var(--admin-success)" }}>在线</span>
                              ) : (
                                <span style={{ color: "var(--admin-error)" }}>离线</span>
                              )}
                            </td>
                            <td>{participant.instructionCompleted ? "已完成" : "未完成"}</td>
                            <td>
                              <QuestionnaireStatusChip status={participant.questionnaireStatus} />
                            </td>
                            <td>{formatDateTime(participant.disconnectedUntil)}</td>
                            <td className="admin-actions-cell">
                              <button
                                type="button"
                                className="admin-btn admin-btn-ghost admin-btn-sm"
                                onClick={() => void markCompleted(
                                  detailParticipant ?? { role: participant.role, name: participant.name },
                                )}
                                disabled={actionBusy !== null}
                              >
                                <CheckCircle2 size={13} />
                                标记完成
                              </button>
                              <button
                                type="button"
                                className="admin-btn admin-btn-ghost admin-btn-sm"
                                onClick={() => void disableParticipant(
                                  detailParticipant ?? { role: participant.role, name: participant.name },
                                )}
                                disabled={actionBusy !== null}
                              >
                                <UserX size={13} />
                                停用
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>

              <section className="admin-card">
                <h2 className="admin-section-title">房间操作</h2>
                <div className="admin-form-row">
                  <div>
                    <Field label="强制归档原因" htmlFor="archive-reason">
                      <select
                        id="archive-reason"
                        className="admin-select"
                        value={archiveReason}
                        disabled={!canForceArchive}
                        onChange={(event) => setArchiveReasonChoice(event.target.value)}
                      >
                        {archiveOptions.map((reason) => (
                          <option key={reason} value={reason}>
                            {ARCHIVE_REASON_LABELS[reason]}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <button
                      type="button"
                      className="admin-btn admin-btn-danger"
                      onClick={() => void forceArchive()}
                      disabled={actionBusy !== null || !canForceArchive}
                    >
                      <Archive size={15} />
                      强制归档
                    </button>
                    {!canForceArchive ? (
                      <p className="admin-hint">房间已归档，不能再次归档。</p>
                    ) : null}
                  </div>
                  <div>
                    <Field label="等待窗口" htmlFor="extend-wait">
                      <input
                        id="extend-wait"
                        className="admin-input"
                        value={`当前 ${formatDuration(room.waitWindowSeconds)}`}
                        readOnly
                        disabled
                      />
                    </Field>
                    <button
                      type="button"
                      className="admin-btn admin-btn-secondary"
                      onClick={() => {
                        setExtendMinutes("5");
                        setExtendError(null);
                        setExtendOpen(true);
                      }}
                      disabled={room.status !== "waiting" || actionBusy !== null}
                    >
                      <TimerReset size={15} />
                      延长等待窗口
                    </button>
                  </div>
                  <div>
                    <Field label="问卷链接" htmlFor="resend-questionnaire">
                      <input
                        id="resend-questionnaire"
                        className="admin-input"
                        value={room.status === "questionnaire" ? "问卷阶段" : "当前不在问卷阶段"}
                        readOnly
                        disabled
                      />
                    </Field>
                    <button
                      type="button"
                      className="admin-btn admin-btn-secondary"
                      onClick={() => void resendQuestionnaire()}
                      disabled={actionBusy !== null || room.status !== "questionnaire"}
                    >
                      <Send size={15} />
                      重发问卷链接
                    </button>
                  </div>
                </div>
                {questionnaireLinks.length > 0 ? (
                  <div className="admin-import-report">
                    <h3>问卷链接</h3>
                    {questionnaireLinks.map((link) => (
                      <div key={link.participantId} style={{ marginBottom: "10px" }}>
                        <div className="admin-hint">
                          {participantNameById.get(link.participantId) ?? link.participantId}
                        </div>
                        <div className="admin-inline-actions">
                          <span className="admin-url-cell">{link.url}</span>
                          <button
                            type="button"
                            className="admin-btn admin-btn-secondary admin-btn-sm"
                            onClick={() => void copyLink(link.url)}
                          >
                            <Copy size={13} />
                            复制
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : null}
              </section>

              <section className="admin-card">
                <h2 className="admin-section-title">Timer 与事件</h2>
                <div className="admin-grid admin-grid-2">
                  <div>
                    <h3 className="admin-section-title" style={{ fontSize: "1rem" }}>
                      Timers
                    </h3>
                    {monitor.timers.length === 0 ? (
                      <p className="admin-hint">暂无计时器。</p>
                    ) : (
                      <div className="admin-table-wrap">
                        <table className="admin-table admin-compact-table">
                          <thead>
                            <tr>
                              <th>类型</th>
                              <th>到期时间</th>
                              <th>状态</th>
                              <th>触发时间</th>
                            </tr>
                          </thead>
                          <tbody>
                            {monitor.timers.map((timer, index) => (
                              <tr key={`${timer.kind}-${index}`}>
                                <td className="admin-mono">{timer.kind}</td>
                                <td>{formatDateTime(timer.dueAt)}</td>
                                <td>{timer.status}</td>
                                <td>{formatDateTime(timer.firedAt)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                  <div>
                    <h3 className="admin-section-title" style={{ fontSize: "1rem" }}>
                      最近事件
                    </h3>
                    {monitor.events.length === 0 ? (
                      <p className="admin-hint">暂无事件。</p>
                    ) : (
                      <div className="admin-import-errors" style={{ maxHeight: "320px" }}>
                        {monitor.events.map((event, index) => (
                          <div
                            key={`${event.type}-${index}`}
                            style={{
                              padding: "8px 0",
                              borderBottom: "1px solid var(--admin-border)",
                              fontSize: "0.8125rem",
                            }}
                          >
                            <div className="admin-inline-actions" style={{ justifyContent: "space-between" }}>
                              <span className="admin-event-type">{event.type}</span>
                              <span className="admin-hint">{formatDateTime(event.createdAt)}</span>
                            </div>
                            {event.payload ? (
                              <JsonDetails value={event.payload} label="事件数据" />
                            ) : null}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </section>

              <section className="admin-card">
                <h2 className="admin-section-title">Trial 记录</h2>
                {monitor.trials.length === 0 ? (
                  <p className="admin-hint">暂无 Trial 记录。</p>
                ) : (
                  <div className="admin-table-wrap">
                    <table className="admin-table admin-compact-table">
                      <thead>
                        <tr>
                          <th>#</th>
                          <th>类型</th>
                          <th>开始</th>
                          <th>结束</th>
                          <th>胜者</th>
                          <th>结束原因</th>
                        </tr>
                      </thead>
                      <tbody>
                        {monitor.trials.map((trial) => (
                          <tr key={trial.trialIndex}>
                            <td className="admin-mono">{trial.trialIndex + 1}</td>
                            <td>{trial.isPractice ? "练习" : `正式 ${trial.formalTrial}`}</td>
                            <td>{formatDateTime(trial.startedAt)}</td>
                            <td>{formatDateTime(trial.endedAt)}</td>
                            <td>{trial.winner ?? "—"}</td>
                            <td>{trial.endReason ?? "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </>
          ) : null}
        </div>
      ) : null}

      {tab === "data" ? (
        <div className="admin-stack">
          <section className="admin-card">
            <h2 className="admin-section-title">数据导出</h2>
            <div className="admin-btn-row">
              <button
                type="button"
                className="admin-btn admin-btn-primary"
                onClick={() => void downloadRoomJson()}
                data-testid="room-download-json"
              >
                <FileJson size={16} />
                下载完整 JSON
              </button>
              <button
                type="button"
                className="admin-btn admin-btn-primary"
                onClick={() => void downloadAnalysisZip()}
                data-testid="room-download-analysis"
              >
                <Download size={16} />
                下载分析 ZIP
              </button>
            </div>
            <p className="admin-hint" style={{ marginTop: "12px", marginBottom: 0 }}>
              分析 ZIP 使用假名分析编号，不包含姓名和手机号。完整 JSON 包含参与者与原始事件。
            </p>
          </section>

          <section className="admin-card">
            <div className="admin-stat-row" style={{ marginBottom: "16px" }}>
              <h2 className="admin-section-title" style={{ marginBottom: 0 }}>
                参与者数据状态
              </h2>
              <div className="admin-btn-row">
                <button
                  type="button"
                  className="admin-btn admin-btn-secondary admin-btn-sm"
                  onClick={() => void resendQuestionnaire()}
                  disabled={actionBusy !== null || room.status !== "questionnaire"}
                >
                  <Send size={14} />
                  获取问卷链接
                </button>
                {detail.jatosAdminUrl ? (
                  <a
                    className="admin-btn admin-btn-secondary admin-btn-sm"
                    href={detail.jatosAdminUrl}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <ExternalLink size={14} />
                    打开 JATOS 后台
                  </a>
                ) : null}
              </div>
            </div>
            {detail.jatosStudyCode ? (
              <p className="admin-hint">JATOS study code: {detail.jatosStudyCode}</p>
            ) : null}
            {detail.participants.length === 0 ? (
              <EmptyState title="暂无参与者" description="进入指导语后会记录参与者。" />
            ) : (
              <div className="admin-table-wrap">
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>角色</th>
                      <th>分析编号</th>
                      <th>姓名</th>
                      <th>指导语完成</th>
                      <th>问卷状态</th>
                      <th>完成时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.participants.map((participant) => (
                      <tr key={participant.id}>
                        <td>玩家 {participant.role}</td>
                        <td className="admin-mono">{participant.analysisCode}</td>
                        <td>
                          {participant.name}
                          <div className="admin-hint">{participant.phoneMasked}</div>
                        </td>
                        <td>{participant.instructionCompletedAt ? "已完成" : "未完成"}</td>
                        <td>
                          <QuestionnaireStatusChip status={participant.questionnaireStatus} />
                        </td>
                        <td>{formatDateTime(participant.completedAt)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {questionnaireLinks.length > 0 ? (
              <div className="admin-import-report">
                <h3>问卷链接</h3>
                {questionnaireLinks.map((link) => (
                  <div key={link.participantId} className="admin-inline-actions" style={{ marginBottom: "8px" }}>
                    <span className="admin-hint">
                      {participantNameById.get(link.participantId) ?? link.participantId}
                    </span>
                    <span className="admin-url-cell">{link.url}</span>
                    <button
                      type="button"
                      className="admin-btn admin-btn-secondary admin-btn-sm"
                      onClick={() => void copyLink(link.url)}
                    >
                      <Copy size={13} />
                      复制
                    </button>
                  </div>
                ))}
              </div>
            ) : null}
          </section>

          <section className="admin-card">
            <h2 className="admin-section-title">从 JATOS 补齐问卷结果</h2>
            <p className="admin-hint">
              当平台没有收到 JATOS 提交时，可使用 JATOS 后台的结果 ID 和答案 JSON 补齐平台副本。该操作按结果 ID 幂等保存。
            </p>
            <form onSubmit={submitJatos}>
              <div className="admin-form-row">
                <Field label="参与者" htmlFor="jatos-participant">
                  <select
                    id="jatos-participant"
                    className="admin-select"
                    value={jatosParticipantId}
                    onChange={(event) => setJatosParticipantId(event.target.value)}
                  >
                    <option value="">请选择</option>
                    {detail.participants.map((participant) => {
                      const booking = findBookingForParticipant(detail, participant);
                      return (
                        <option
                          key={participant.id}
                          value={booking?.participantId ?? ""}
                          disabled={!booking}
                        >
                          玩家 {participant.role} · {participant.name}
                          {booking ? "" : "（缺少 participantId）"}
                        </option>
                      );
                    })}
                  </select>
                </Field>
                <Field label="JATOS worker ID（可选）" htmlFor="jatos-worker">
                  <input
                    id="jatos-worker"
                    className="admin-input"
                    value={jatosWorkerId}
                    onChange={(event) => setJatosWorkerId(event.target.value)}
                  />
                </Field>
              </div>
              <div className="admin-form-row">
                <Field label="JATOS study result ID" htmlFor="jatos-study-result">
                  <input
                    id="jatos-study-result"
                    className="admin-input"
                    value={jatosStudyResultId}
                    onChange={(event) => setJatosStudyResultId(event.target.value)}
                  />
                </Field>
                <Field label="JATOS component result ID" htmlFor="jatos-component-result">
                  <input
                    id="jatos-component-result"
                    className="admin-input"
                    value={jatosComponentResultId}
                    onChange={(event) => setJatosComponentResultId(event.target.value)}
                  />
                </Field>
              </div>
              <Field label="问卷答案 JSON" htmlFor="jatos-answers" hint="必须是包含题目 ID 与答案的对象。">
                <textarea
                  id="jatos-answers"
                  className="admin-textarea"
                  value={jatosAnswers}
                  onChange={(event) => setJatosAnswers(event.target.value)}
                  placeholder='{"q1": "option_a"}'
                  style={{ minHeight: "120px" }}
                />
              </Field>
              {jatosError ? <InlineNotice tone="error">{jatosError}</InlineNotice> : null}
              <button
                type="submit"
                className="admin-btn admin-btn-primary"
                disabled={jatosSubmitting}
                data-testid="jatos-import-submit"
              >
                {jatosSubmitting ? "补齐中" : "补齐结果"}
              </button>
            </form>
          </section>
        </div>
      ) : null}

      {tab === "payments" ? (
        <div className="admin-stack">
          <section className="admin-card">
            <div className="admin-stat-row" style={{ marginBottom: "16px" }}>
              <h2 className="admin-section-title" style={{ marginBottom: 0 }}>
                房间付款
              </h2>
              <span className="admin-hint">金额为整数分转换后的两位小数</span>
            </div>
            {detail.payments.length === 0 ? (
              <EmptyState
                icon={Wallet}
                title="暂无付款记录"
                description="房间归档后会自动计算参与者付款。"
              />
            ) : (
              <div className="admin-table-wrap">
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>分析编号</th>
                      <th>基础费</th>
                      <th>绩效费</th>
                      <th>到场费</th>
                      <th>覆盖金额</th>
                      <th>合计</th>
                      <th>状态</th>
                      <th>备注</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.payments.map((payment, index) => (
                      <tr key={payment.id ?? index}>
                        <td className="admin-mono">{payment.analysisCode ?? "—"}</td>
                        <td>{formatMoney(payment.basePayCents)}</td>
                        <td>{formatMoney(payment.performancePayCents)}</td>
                        <td>{formatMoney(payment.showupPayCents)}</td>
                        <td>{formatMoney(payment.overrideAmountCents)}</td>
                        <td className="admin-total">{formatMoney(payment.totalCents)}</td>
                        <td>
                          <PaymentStatusChip status={payment.status} />
                        </td>
                        <td className="admin-hint">{payment.note ?? "—"}</td>
                        <td className="admin-actions-cell">
                          <button
                            type="button"
                            className="admin-btn admin-btn-ghost admin-btn-sm"
                            onClick={() => openPayment(payment)}
                            disabled={!payment.id}
                          >
                            覆盖金额
                          </button>
                          {payment.status === "pending" ? (
                            <button
                              type="button"
                              className="admin-btn admin-btn-ghost admin-btn-sm"
                              onClick={() => void markPaid(payment)}
                              disabled={!payment.id || paymentBusy === payment.id}
                            >
                              标记已支付
                            </button>
                          ) : (
                            <button
                              type="button"
                              className="admin-btn admin-btn-ghost admin-btn-sm"
                              onClick={() => void markPending(payment)}
                              disabled={!payment.id || paymentBusy === payment.id}
                            >
                              设为待支付
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      ) : null}

      {extendOpen ? (
        <Modal
          title="延长等待窗口"
          onClose={() => setExtendOpen(false)}
          footer={
            <>
              <button type="button" className="admin-btn admin-btn-secondary" onClick={() => setExtendOpen(false)}>
                取消
              </button>
              <button
                type="submit"
                form="extend-wait-form"
                className="admin-btn admin-btn-primary"
                disabled={actionBusy === "extend"}
              >
                {actionBusy === "extend" ? "保存中" : "延长"}
              </button>
            </>
          }
        >
          <form id="extend-wait-form" onSubmit={submitExtend}>
            <p className="admin-hint">仅在房间处于等待阶段时可用。延长后配置变更会记录到历史。</p>
            <Field label="延长分钟数" htmlFor="extend-minutes" error={extendError}>
              <input
                id="extend-minutes"
                className="admin-input"
                type="number"
                min="1"
                max="1440"
                value={extendMinutes}
                onChange={(event) => setExtendMinutes(event.target.value)}
              />
            </Field>
          </form>
        </Modal>
      ) : null}

      {paymentModal ? (
        <Modal
          title="覆盖付款金额"
          onClose={() => setPaymentModal(null)}
          footer={
            <>
              <button type="button" className="admin-btn admin-btn-secondary" onClick={() => setPaymentModal(null)}>
                取消
              </button>
              <button
                type="submit"
                form="payment-override-form"
                className="admin-btn admin-btn-danger"
                disabled={paymentSaving}
                data-testid="payment-override-submit"
              >
                {paymentSaving ? "保存中" : "保存覆盖金额"}
              </button>
            </>
          }
        >
          <form id="payment-override-form" onSubmit={savePayment}>
            <div className="admin-payment-summary" style={{ marginBottom: "16px" }}>
              <span>自动金额 {formatMoney(
                paymentModal.payment.basePayCents +
                  paymentModal.payment.performancePayCents +
                  paymentModal.payment.showupPayCents,
              )}</span>
              <span>当前合计 {formatMoney(paymentModal.payment.totalCents)}</span>
            </div>
            <Field label="覆盖金额（元）" htmlFor="payment-override-amount" error={paymentError}>
              <input
                id="payment-override-amount"
                className="admin-input"
                type="number"
                min="0"
                step="0.01"
                value={paymentModal.amount}
                onChange={(event) =>
                  setPaymentModal({ ...paymentModal, amount: event.target.value })
                }
                data-testid="payment-override-amount"
              />
            </Field>
            <Field
              label="备注"
              htmlFor="payment-override-note"
              hint="覆盖金额必须填写备注，备注会写入审计日志。"
            >
              <textarea
                id="payment-override-note"
                className="admin-textarea"
                value={paymentModal.note}
                onChange={(event) => setPaymentModal({ ...paymentModal, note: event.target.value })}
                style={{ minHeight: "90px" }}
                data-testid="payment-override-note"
              />
            </Field>
          </form>
        </Modal>
      ) : null}
    </div>
  );
}
