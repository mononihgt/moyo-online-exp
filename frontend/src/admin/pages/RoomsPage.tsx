import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  CalendarDays,
  Copy,
  Download,
  FileJson,
  Layers,
  Plus,
} from "lucide-react";
import type { RoomSection, RoomSummary } from "../../shared/types";
import { formatDateTime } from "../../shared/format";
import { adminApi, adminDownload, errorMessage } from "../api";
import type { RoomListResponse, RoomResponse } from "../types";
import {
  EmptyState,
  ErrorNotice,
  Field,
  InlineNotice,
  LoadingBlock,
  Modal,
  PageHeader,
  RoomStatusChip,
  fromShanghaiInput,
  useNow,
  useUi,
} from "../ui";
import {
  RoomConfigFields,
  buildRoomPayload,
  defaultRoomForm,
  defaultStartInput,
  usePublishedOptions,
} from "../roomForm";
import type { RoomFormState } from "../roomForm";
import { ARCHIVE_REASON_LABELS } from "../labels";

type ModalState =
  | { type: "create" }
  | { type: "batch" }
  | { type: "copy"; room: RoomSummary }
  | null;

const SECTION_OPTIONS: { key: RoomSection; label: string; description: string }[] = [
  { key: "draft", label: "未开放预约", description: "草稿房间，可继续编辑配置并开放预约。" },
  { key: "open", label: "开放预约", description: "可报名与已满、尚未开始的房间。" },
  { key: "in_progress", label: "进行中", description: "等待、指导语、对局与问卷阶段的房间。" },
  { key: "unpaid", label: "未完全支付", description: "已归档且仍有待支付付款的房间。" },
  { key: "archived", label: "已归档", description: "已归档且没有待支付付款的房间。" },
];

const EMPTY_COUNTS: Record<RoomSection, number> = {
  draft: 0,
  open: 0,
  in_progress: 0,
  unpaid: 0,
  archived: 0,
};

const IN_PROGRESS_STATUSES = ["waiting", "instructions", "playing", "questionnaire"];
const PRE_START_STATUSES = ["draft", "open", "full"];

function resolveSection(params: URLSearchParams): RoomSection {
  const section = params.get("section");
  if (section !== null) {
    const match = SECTION_OPTIONS.find((entry) => entry.key === section);
    if (match) return match.key;
  }
  const status = params.get("status");
  switch (status) {
    case "draft":
      return "draft";
    case "open":
    case "full":
      return "open";
    case "waiting":
    case "instructions":
    case "playing":
    case "questionnaire":
      return "in_progress";
    case "archived":
      return "archived";
    default:
      return "draft";
  }
}

export function RoomsPage() {
  const { notify, confirm } = useUi();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [section, setSection] = useState<RoomSection>(() => resolveSection(searchParams));
  const [rooms, setRooms] = useState<RoomSummary[]>([]);
  const [counts, setCounts] = useState<Record<RoomSection, number>>(EMPTY_COUNTS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);
  const [modal, setModal] = useState<ModalState>(null);
  const [form, setForm] = useState<RoomFormState>(() =>
    defaultRoomForm({ mapGroups: [], instructions: [], questionnaires: [] }),
  );
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});
  const [modalError, setModalError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [batchCount, setBatchCount] = useState("2");
  const [copyLabel, setCopyLabel] = useState("");
  const [copyStartsAt, setCopyStartsAt] = useState(defaultStartInput());
  const [busyId, setBusyId] = useState<string | null>(null);
  const now = useNow(30000);
  const { options, loading: optionsLoading, error: optionsError } = usePublishedOptions();

  const sectionMeta = SECTION_OPTIONS.find((entry) => entry.key === section) ?? SECTION_OPTIONS[0];

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.set("section", section);
      const response = await adminApi.get<RoomListResponse>(`/rooms?${params.toString()}`);
      setRooms(response.rooms);
      setCounts({ ...EMPTY_COUNTS, ...response.counts });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [section]);

  useEffect(() => {
    void load();
  }, [load, reloadNonce]);

  const createRequested = searchParams.get("create") === "1";

  useEffect(() => {
    if (!createRequested || optionsLoading) return;
    setForm(defaultRoomForm(options));
    setSection("draft");
    setFormErrors({});
    setModalError(null);
    setModal({ type: "create" });
    const next = new URLSearchParams(searchParams);
    next.delete("create");
    next.delete("status");
    next.set("section", "draft");
    setSearchParams(next, { replace: true });
    // 仅响应一次 URL 中的创建请求
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [createRequested, optionsLoading]);

  const refresh = useCallback(() => {
    setReloadNonce((value) => value + 1);
  }, []);

  function changeSection(next: RoomSection) {
    setSection(next);
    const nextParams = new URLSearchParams(searchParams);
    nextParams.delete("status");
    nextParams.set("section", next);
    setSearchParams(nextParams, { replace: true });
  }

  function openCreate() {
    setForm(defaultRoomForm(options));
    setFormErrors({});
    setModalError(null);
    setModal({ type: "create" });
  }

  function openBatch() {
    setForm(defaultRoomForm(options));
    setBatchCount("2");
    setFormErrors({});
    setModalError(null);
    setModal({ type: "batch" });
  }

  function openCopy(room: RoomSummary) {
    setCopyLabel(`${room.internalLabel} 副本`);
    setCopyStartsAt(defaultStartInput());
    setFormErrors({});
    setModalError(null);
    setModal({ type: "copy", room });
  }

  function closeModal() {
    if (submitting) return;
    setModal(null);
    setModalError(null);
    setFormErrors({});
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const result = buildRoomPayload(form);
    setFormErrors(result.errors);
    if (!result.payload) return;
    setSubmitting(true);
    setModalError(null);
    try {
      const response = await adminApi.post<RoomResponse>("/rooms", result.payload);
      notify("Room 已创建");
      setModal(null);
      refresh();
      navigate(`/admin/rooms/${response.room.id}`);
    } catch (err) {
      setModalError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleBatch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const result = buildRoomPayload(form);
    const count = Number(batchCount);
    const nextErrors = { ...result.errors };
    if (!Number.isInteger(count) || count < 1 || count > 20) {
      nextErrors.batchCount = "数量必须是 1 到 20 之间的整数";
    }
    setFormErrors(nextErrors);
    if (!result.payload || Object.keys(nextErrors).length > 0) return;
    setSubmitting(true);
    setModalError(null);
    try {
      const response = await adminApi.post<{ rooms: RoomSummary[] }>("/rooms/batch", {
        template: result.payload,
        count,
      });
      notify(`已创建 ${response.rooms.length} 个 Room`);
      setModal(null);
      refresh();
    } catch (err) {
      setModalError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCopy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (modal?.type !== "copy") return;
    const nextErrors: Record<string, string> = {};
    if (!copyLabel.trim()) nextErrors.copyLabel = "请填写内部名称";
    if (!copyStartsAt) nextErrors.copyStartsAt = "请选择新的开始时间";
    let startsAt: string | null = null;
    if (copyStartsAt) {
      try {
        startsAt = fromShanghaiInput(copyStartsAt);
        if (Number.isNaN(new Date(startsAt).getTime())) throw new Error("invalid");
      } catch {
        nextErrors.copyStartsAt = "开始时间格式不正确";
      }
    }
    setFormErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;
    setSubmitting(true);
    setModalError(null);
    try {
      const response = await adminApi.post<RoomResponse>(`/rooms/${modal.room.id}/copy`, {
        internalLabel: copyLabel.trim(),
        startsAt,
      });
      notify("Room 已复制");
      setModal(null);
      refresh();
      navigate(`/admin/rooms/${response.room.id}`);
    } catch (err) {
      setModalError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function publishRoom(room: RoomSummary) {
    const ok = await confirm({
      title: "开放预约",
      message: [
        `确认开放「${room.internalLabel}」的预约？`,
        `开始时间：${formatDateTime(room.startsAt)}`,
        `地图组：${room.mapGroup.name} v${room.mapGroup.version}`,
        `指导语：${room.instructions.player1.name} v${room.instructions.player1.version} / ${room.instructions.player2.name} v${room.instructions.player2.version}`,
        `问卷：${room.questionnaire.name} v${room.questionnaire.version}`,
        "开放后房间进入可报名状态。",
      ].join("\n"),
      confirmLabel: "开放预约",
    });
    if (!ok) return;
    setBusyId(room.id);
    try {
      await adminApi.post(`/rooms/${room.id}/publish`);
      notify("Room 已开放预约");
      refresh();
    } catch (err) {
      notify(errorMessage(err), "error");
    } finally {
      setBusyId(null);
    }
  }

  async function closeBooking(room: RoomSummary) {
    const ok = await confirm({
      title: "关闭预约",
      message: [
        `确认关闭「${room.internalLabel}」的预约？`,
        "关闭后房间回到草稿状态，可继续修改配置。",
        "仅在没有有效预约时可以关闭预约。",
      ].join("\n"),
      confirmLabel: "关闭预约",
    });
    if (!ok) return;
    setBusyId(room.id);
    try {
      await adminApi.post(`/rooms/${room.id}/close-booking`);
      notify("Room 已关闭预约并回到草稿状态");
      refresh();
    } catch (err) {
      notify(errorMessage(err), "error");
    } finally {
      setBusyId(null);
    }
  }

  async function cancelRoom(room: RoomSummary) {
    const ok = await confirm({
      title: "取消 Room",
      message: `确认取消「${room.internalLabel}」？已报名参与者会看到房间取消，已有记录会保留，相关预约会进入付款补算流程。`,
      confirmLabel: "取消 Room",
      danger: true,
    });
    if (!ok) return;
    setBusyId(room.id);
    try {
      await adminApi.post(`/rooms/${room.id}/cancel`);
      notify("Room 已取消并归档");
      refresh();
    } catch (err) {
      notify(errorMessage(err), "error");
    } finally {
      setBusyId(null);
    }
  }

  async function archiveRoom(room: RoomSummary) {
    const ok = await confirm({
      title: "归档 Room",
      message: `确认归档「${room.internalLabel}」？房间将结束当前流程，未完成问卷的参与者不会被自动标记完成。已有数据会保留。`,
      confirmLabel: "归档",
      danger: true,
    });
    if (!ok) return;
    setBusyId(room.id);
    try {
      await adminApi.post(`/rooms/${room.id}/archive`, {});
      notify("Room 已归档");
      refresh();
    } catch (err) {
      notify(errorMessage(err), "error");
    } finally {
      setBusyId(null);
    }
  }

  async function exportRoom(room: RoomSummary, kind: "json" | "analysis") {
    try {
      if (kind === "json") {
        await adminDownload(`/rooms/${room.id}/export.json`, `room-${room.id}.json`);
      } else {
        await adminDownload(`/rooms/${room.id}/analysis.zip`, `analysis-${room.id}.zip`);
      }
    } catch (err) {
      notify(errorMessage(err), "error");
    }
  }

  function roomStarted(room: RoomSummary): boolean {
    return Date.parse(room.startsAt) <= now;
  }

  const canCloseBooking = (room: RoomSummary): boolean =>
    ["open", "full"].includes(room.status) && !roomStarted(room) && room.bookedCount === 0;

  return (
    <div>
      <PageHeader
        title="房间"
        subtitle="按分区创建、开放和归档实验房间。列表状态为实时数据库状态。"
        actions={
          section === "draft" ? (
            <div className="admin-btn-row">
              <button
                type="button"
                className="admin-btn admin-btn-secondary"
                onClick={openBatch}
                disabled={optionsLoading}
                data-testid="room-batch-create"
              >
                <Layers size={16} />
                批量创建
              </button>
              <button
                type="button"
                className="admin-btn admin-btn-primary"
                onClick={openCreate}
                disabled={optionsLoading}
                data-testid="room-create"
              >
                <Plus size={16} />
                创建 Room
              </button>
            </div>
          ) : undefined
        }
      />

      {optionsError ? <InlineNotice tone="warning">版本选项加载失败：{optionsError}</InlineNotice> : null}
      {error ? <ErrorNotice message={error} onRetry={() => void load()} /> : null}

      <div className="admin-toolbar">
        <select
          className="admin-select"
          value={section}
          onChange={(event) => changeSection(event.target.value as RoomSection)}
          aria-label="按分区筛选房间"
          style={{ maxWidth: "240px" }}
          data-testid="room-section-filter"
        >
          {SECTION_OPTIONS.map((entry) => (
            <option key={entry.key} value={entry.key}>
              {entry.label}（{counts[entry.key] ?? 0}）
            </option>
          ))}
        </select>
        <span className="admin-hint">
          {sectionMeta.description} 共 {rooms.length} 个房间
        </span>
      </div>

      {loading ? (
        <LoadingBlock rows={7} label="正在加载房间" />
      ) : rooms.length === 0 ? (
        <EmptyState
          icon={CalendarDays}
          title="该分区暂无房间"
          description={sectionMeta.description}
          action={
            section === "draft" ? (
              <button type="button" className="admin-btn admin-btn-primary" onClick={openCreate}>
                创建 Room
              </button>
            ) : undefined
          }
        />
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>内部名称</th>
                <th>开始时间</th>
                <th>地图组</th>
                <th>指导语</th>
                <th>问卷</th>
                <th>预约</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {rooms.map((room) => {
                const started = roomStarted(room);
                return (
                  <tr key={room.id}>
                    <td>
                      <Link className="admin-row-link" to={`/admin/rooms/${room.id}`}>
                        {room.internalLabel}
                      </Link>
                    </td>
                    <td>{formatDateTime(room.startsAt)}</td>
                    <td>
                      <div>
                        {room.mapGroup.name} v{room.mapGroup.version}
                      </div>
                      <div className="admin-hint">
                        {room.mapGroup.rows} × {room.mapGroup.cols} ·{" "}
                        {room.mapGroup.mode === "both" ? "Both" : "A/B"}
                      </div>
                    </td>
                    <td>
                      <div>
                        P1: {room.instructions.player1.name} v{room.instructions.player1.version}
                      </div>
                      <div className="admin-hint">
                        P2: {room.instructions.player2.name} v{room.instructions.player2.version}
                      </div>
                    </td>
                    <td>
                      <div>{room.questionnaire.name}</div>
                      <div className="admin-hint">v{room.questionnaire.version}</div>
                    </td>
                    <td>
                      {room.bookedCount}/{room.capacity}
                    </td>
                    <td>
                      <RoomStatusChip status={room.status} />
                      {room.archiveReason ? (
                        <div className="admin-hint" style={{ marginTop: "2px" }}>
                          {ARCHIVE_REASON_LABELS[room.archiveReason] ?? room.archiveReason}
                        </div>
                      ) : null}
                    </td>
                    <td className="admin-actions-cell">
                      <Link className="admin-btn admin-btn-ghost admin-btn-sm" to={`/admin/rooms/${room.id}`}>
                        查看
                      </Link>
                      {room.status === "draft" ? (
                        <button
                          type="button"
                          className="admin-btn admin-btn-ghost admin-btn-sm"
                          onClick={() => void publishRoom(room)}
                          disabled={busyId === room.id || started}
                          title={started ? "开始时间必须晚于当前时间" : undefined}
                          data-testid="room-publish"
                          data-room-id={room.id}
                        >
                          开放预约
                        </button>
                      ) : null}
                      {["open", "full"].includes(room.status) ? (
                        <button
                          type="button"
                          className="admin-btn admin-btn-ghost admin-btn-sm"
                          onClick={() => void closeBooking(room)}
                          disabled={busyId === room.id || !canCloseBooking(room)}
                          title={
                            started
                              ? "开始时间已过，不能关闭预约"
                              : room.bookedCount > 0
                                ? "存在有效预约，无法关闭预约"
                                : undefined
                          }
                          data-testid="room-close-booking"
                          data-room-id={room.id}
                        >
                          关闭预约
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className="admin-btn admin-btn-ghost admin-btn-sm"
                        onClick={() => openCopy(room)}
                        disabled={busyId === room.id}
                        data-testid="room-copy"
                      >
                        <Copy size={13} />
                        复制
                      </button>
                      {PRE_START_STATUSES.includes(room.status) ? (
                        <button
                          type="button"
                          className="admin-btn admin-btn-ghost admin-btn-sm"
                          onClick={() => void cancelRoom(room)}
                          disabled={busyId === room.id}
                        >
                          取消
                        </button>
                      ) : null}
                      {IN_PROGRESS_STATUSES.includes(room.status) ? (
                        <button
                          type="button"
                          className="admin-btn admin-btn-ghost admin-btn-sm"
                          onClick={() => void archiveRoom(room)}
                          disabled={busyId === room.id}
                        >
                          归档
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className="admin-btn admin-btn-ghost admin-btn-sm"
                        onClick={() => void exportRoom(room, "json")}
                        data-testid="room-export-json"
                      >
                        <FileJson size={13} />
                        导出 JSON
                      </button>
                      <button
                        type="button"
                        className="admin-btn admin-btn-ghost admin-btn-sm"
                        onClick={() => void exportRoom(room, "analysis")}
                        data-testid="room-export-analysis"
                      >
                        <Download size={13} />
                        分析 ZIP
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {modal?.type === "create" ? (
        <Modal title="创建 Room" onClose={closeModal} wide>
          <form onSubmit={handleCreate}>
            {optionsLoading ? <LoadingBlock rows={3} label="正在加载版本选项" /> : null}
            <RoomConfigFields
              form={form}
              errors={formErrors}
              options={options}
              onChange={setForm}
              disabled={submitting}
            />
            {modalError ? <InlineNotice tone="error">{modalError}</InlineNotice> : null}
            <div className="admin-modal-actions">
              <button type="button" className="admin-btn admin-btn-secondary" onClick={closeModal}>
                取消
              </button>
              <button
                type="submit"
                className="admin-btn admin-btn-primary"
                disabled={submitting || optionsLoading}
                data-testid="room-submit"
              >
                {submitting ? "创建中" : "创建 Room"}
              </button>
            </div>
          </form>
        </Modal>
      ) : null}

      {modal?.type === "batch" ? (
        <Modal title="批量创建并行 Room" onClose={closeModal} wide>
          <form onSubmit={handleBatch}>
            <InlineNotice tone="info">
              所有 Room 使用相同的地图组、指导语、问卷、开始时间与窗口配置。内部名称会按数量追加序号。
            </InlineNotice>
            {optionsLoading ? <LoadingBlock rows={3} label="正在加载版本选项" /> : null}
            <RoomConfigFields
              form={form}
              errors={formErrors}
              options={options}
              onChange={setForm}
              disabled={submitting}
            />
            <div className="admin-form-section">
              <Field label="创建数量" htmlFor="batch-count" error={formErrors.batchCount}>
                <input
                  id="batch-count"
                  className="admin-input"
                  type="number"
                  min="1"
                  max="20"
                  step="1"
                  value={batchCount}
                  onChange={(event) => setBatchCount(event.target.value)}
                  data-testid="room-batch-count"
                />
              </Field>
            </div>
            {modalError ? <InlineNotice tone="error">{modalError}</InlineNotice> : null}
            <div className="admin-modal-actions">
              <button type="button" className="admin-btn admin-btn-secondary" onClick={closeModal}>
                取消
              </button>
              <button
                type="submit"
                className="admin-btn admin-btn-primary"
                disabled={submitting || optionsLoading}
                data-testid="room-batch-submit"
              >
                {submitting ? "创建中" : "批量创建"}
              </button>
            </div>
          </form>
        </Modal>
      ) : null}

      {modal?.type === "copy" ? (
        <Modal title="复制 Room" onClose={closeModal}>
          <form onSubmit={handleCopy}>
            <InlineNotice tone="info">
              复制会保留地图组、指导语、问卷与窗口配置，不复制预约和运行数据。付款参数与容量继承自地图组。
            </InlineNotice>
            <Field label="内部名称" htmlFor="copy-label" error={formErrors.copyLabel}>
              <input
                id="copy-label"
                className="admin-input"
                value={copyLabel}
                onChange={(event) => setCopyLabel(event.target.value)}
                data-testid="room-copy-label"
              />
            </Field>
            <Field label="新的开始时间（Asia/Shanghai）" htmlFor="copy-start" error={formErrors.copyStartsAt}>
              <input
                id="copy-start"
                className="admin-input"
                type="datetime-local"
                value={copyStartsAt}
                onChange={(event) => setCopyStartsAt(event.target.value)}
                data-testid="room-copy-start"
              />
            </Field>
            <div className="admin-hint">
              来源：{modal.room.internalLabel}（{formatDateTime(modal.room.startsAt)}，
              {modal.room.mapGroup.name} v{modal.room.mapGroup.version}）
            </div>
            {modalError ? <InlineNotice tone="error">{modalError}</InlineNotice> : null}
            <div className="admin-modal-actions">
              <button type="button" className="admin-btn admin-btn-secondary" onClick={closeModal}>
                取消
              </button>
              <button
                type="submit"
                className="admin-btn admin-btn-primary"
                disabled={submitting}
                data-testid="room-copy-submit"
              >
                {submitting ? "复制中" : "复制 Room"}
              </button>
            </div>
          </form>
        </Modal>
      ) : null}
    </div>
  );
}
