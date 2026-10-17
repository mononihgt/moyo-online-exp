import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { CalendarDays, CalendarPlus, Copy, Layers, Plus } from "lucide-react";
import type { RoomStatus, RoomSummary } from "../../shared/types";
import { formatDateTime, formatMoney } from "../../shared/format";
import { adminApi, errorMessage } from "../api";
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
import { ROOM_STATUS_LABELS } from "../labels";

type ModalState =
  | { type: "create" }
  | { type: "batch" }
  | { type: "copy"; room: RoomSummary }
  | null;

const STATUS_OPTIONS = Object.keys(ROOM_STATUS_LABELS) as RoomStatus[];

export function RoomsPage() {
  const { notify, confirm } = useUi();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [statusFilter, setStatusFilter] = useState(searchParams.get("status") ?? "");
  const [rooms, setRooms] = useState<RoomSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);
  const [modal, setModal] = useState<ModalState>(null);
  const [form, setForm] = useState<RoomFormState>(() => defaultRoomForm({
    conditions: [],
    instructions: [],
    questionnaires: [],
  }));
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});
  const [modalError, setModalError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [batchCount, setBatchCount] = useState("2");
  const [batchConditionIds, setBatchConditionIds] = useState<string[]>([]);
  const [copyLabel, setCopyLabel] = useState("");
  const [copyStartsAt, setCopyStartsAt] = useState(defaultStartInput());
  const [busyId, setBusyId] = useState<string | null>(null);
  const { options, loading: optionsLoading, error: optionsError } = usePublishedOptions();

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (statusFilter) params.set("status", statusFilter);
      params.set("limit", "300");
      const response = await adminApi.get<RoomListResponse>(`/rooms?${params.toString()}`);
      setRooms(response.rooms);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    void load();
  }, [load, reloadNonce]);

  const createRequested = searchParams.get("create") === "1";

  useEffect(() => {
    if (!createRequested || optionsLoading) return;
    const nextForm = defaultRoomForm(options);
    setForm(nextForm);
    setFormErrors({});
    setModalError(null);
    setModal({ type: "create" });
    const next = new URLSearchParams(searchParams);
    next.delete("create");
    setSearchParams(next, { replace: true });
    // 仅响应一次 URL 中的创建请求
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [createRequested, optionsLoading]);

  const refresh = useCallback(() => {
    setReloadNonce((value) => value + 1);
  }, []);

  function openCreate() {
    setForm(defaultRoomForm(options));
    setFormErrors({});
    setModalError(null);
    setModal({ type: "create" });
  }

  function openBatch() {
    const nextForm = defaultRoomForm(options);
    setForm(nextForm);
    setBatchConditionIds(nextForm.conditionVersionId ? [nextForm.conditionVersionId] : []);
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
        conditionVersionIds: batchConditionIds.length > 0 ? batchConditionIds : undefined,
      });
      notify(`已创建 ${response.rooms.length} 个并行 Room`);
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
    if (!copyLabel.trim()) {
      setFormErrors({ copyLabel: "请填写内部名称" });
      return;
    }
    if (!copyStartsAt) {
      setFormErrors({ copyStartsAt: "请选择新的开始时间" });
      return;
    }
    setSubmitting(true);
    setModalError(null);
    try {
      const response = await adminApi.post<RoomResponse>(`/rooms/${modal.room.id}/copy`, {
        internalLabel: copyLabel.trim(),
        startsAt: fromShanghaiInput(copyStartsAt),
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
      title: "发布 Room",
      message: [
        `确认发布「${room.internalLabel}」？`,
        `开始时间：${formatDateTime(room.startsAt)}`,
        `条件：${room.condition.name} v${room.condition.version}`,
        `指导语：${room.instructions.player1.name} v${room.instructions.player1.version} / ${room.instructions.player2.name} v${room.instructions.player2.version}`,
        `问卷：${room.questionnaire.name} v${room.questionnaire.version}`,
        "发布后房间进入可报名状态。",
      ].join("\n"),
      confirmLabel: "发布",
    });
    if (!ok) return;
    setBusyId(room.id);
    try {
      await adminApi.post(`/rooms/${room.id}/publish`);
      notify("Room 已发布");
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

  function toggleBatchCondition(id: string, checked: boolean) {
    setBatchConditionIds((current) =>
      checked ? [...current, id] : current.filter((item) => item !== id),
    );
  }

  return (
    <div>
      <PageHeader
        title="房间"
        subtitle="创建、发布和管理实验房间。房间列表中的状态为实时数据库状态。"
        actions={
          <div className="admin-btn-row">
            <button
              type="button"
              className="admin-btn admin-btn-secondary"
              onClick={openBatch}
              data-testid="room-batch-create"
            >
              <Layers size={16} />
              批量创建
            </button>
            <button
              type="button"
              className="admin-btn admin-btn-primary"
              onClick={openCreate}
              data-testid="room-create"
            >
              <Plus size={16} />
              创建 Room
            </button>
          </div>
        }
      />

      {optionsError ? <InlineNotice tone="warning">版本选项加载失败：{optionsError}</InlineNotice> : null}
      {error ? <ErrorNotice message={error} onRetry={() => void load()} /> : null}

      <div className="admin-toolbar">
        <select
          className="admin-select"
          value={statusFilter}
          onChange={(event) => {
            setStatusFilter(event.target.value);
            const next = new URLSearchParams(searchParams);
            if (event.target.value) next.set("status", event.target.value);
            else next.delete("status");
            setSearchParams(next, { replace: true });
          }}
          aria-label="按状态筛选房间"
          style={{ maxWidth: "200px" }}
          data-testid="room-status-filter"
        >
          <option value="">全部状态</option>
          {STATUS_OPTIONS.map((status) => (
            <option key={status} value={status}>
              {ROOM_STATUS_LABELS[status]}
            </option>
          ))}
        </select>
        <span className="admin-hint">共 {rooms.length} 个房间</span>
      </div>

      {loading ? (
        <LoadingBlock rows={7} label="正在加载房间" />
      ) : rooms.length === 0 ? (
        <EmptyState
          icon={CalendarDays}
          title="暂无房间"
          description="创建 Room 并发布后，参与者就可以报名。"
          action={
            <button type="button" className="admin-btn admin-btn-primary" onClick={openCreate}>
              创建 Room
            </button>
          }
        />
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>内部名称</th>
                <th>开始时间</th>
                <th>条件</th>
                <th>状态</th>
                <th>报名人数</th>
                <th>问卷</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {rooms.map((room) => (
                <tr key={room.id}>
                  <td>
                    <Link className="admin-row-link" to={`/admin/rooms/${room.id}`}>
                      {room.internalLabel}
                    </Link>
                  </td>
                  <td>{formatDateTime(room.startsAt)}</td>
                  <td>
                    <div>{room.condition.name}</div>
                    <div className="admin-hint">v{room.condition.version}</div>
                  </td>
                  <td>
                    <RoomStatusChip status={room.status} />
                    {room.archiveReason ? (
                      <div className="admin-hint" style={{ marginTop: "2px" }}>
                        {room.archiveReason}
                      </div>
                    ) : null}
                  </td>
                  <td>
                    {room.bookedCount}/{room.capacity}
                  </td>
                  <td>
                    <div>{room.questionnaire.name}</div>
                    <div className="admin-hint">v{room.questionnaire.version}</div>
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
                        disabled={busyId === room.id}
                        data-testid="room-publish"
                        data-room-id={room.id}
                      >
                        发布
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className="admin-btn admin-btn-ghost admin-btn-sm"
                      onClick={() => openCopy(room)}
                    >
                      <Copy size={13} />
                      复制
                    </button>
                    {["draft", "open", "full"].includes(room.status) ? (
                      <button
                        type="button"
                        className="admin-btn admin-btn-ghost admin-btn-sm"
                        onClick={() => void cancelRoom(room)}
                        disabled={busyId === room.id}
                      >
                        取消
                      </button>
                    ) : null}
                    {["waiting", "instructions", "playing", "questionnaire"].includes(room.status) ? (
                      <button
                        type="button"
                        className="admin-btn admin-btn-ghost admin-btn-sm"
                        onClick={() => void archiveRoom(room)}
                        disabled={busyId === room.id}
                      >
                        归档
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
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
              所有 Room 使用相同的开始时间和模板配置。内部名称会按数量追加序号，条件按下方勾选顺序循环分配。
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
              <div className="admin-form-row">
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
                <Field label="条件分配" hint="至少勾选一个条件。未勾选时使用模板中的条件。">
                  <div className="admin-checklist">
                    {options.conditions.length === 0 ? (
                      <div className="admin-hint">暂无可选条件。</div>
                    ) : (
                      options.conditions.map((condition) => (
                        <label key={condition.id} className="admin-check-item">
                          <input
                            type="checkbox"
                            checked={batchConditionIds.includes(condition.id)}
                            onChange={(event) => toggleBatchCondition(condition.id, event.target.checked)}
                            data-testid={`room-batch-condition-${condition.id}`}
                          />
                          <span>
                            {condition.name} v{condition.version}
                          </span>
                        </label>
                      ))
                    )}
                  </div>
                </Field>
              </div>
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
              复制会保留条件、指导语、问卷、费用和窗口配置，不复制预约和运行数据。
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
              {modal.room.condition.name} v{modal.room.condition.version}，基础费{" "}
              {formatMoney(modal.room.basePayCents)}）
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
