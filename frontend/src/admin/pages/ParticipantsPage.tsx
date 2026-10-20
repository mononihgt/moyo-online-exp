import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { DragEvent as ReactDragEvent, FormEvent } from "react";
import { Pencil, Search, UserCheck, UserX, Users } from "lucide-react";
import type { AdminParticipant, ParticipantStatus } from "../../shared/types";
import { formatDateTime } from "../../shared/format";
import { adminApi, errorMessage, fileUploadForm } from "../api";
import type { CompletedImportReport, ParticipantListResponse } from "../types";
import {
  EmptyState,
  ErrorNotice,
  Field,
  InlineNotice,
  LoadingBlock,
  Modal,
  PageHeader,
  Pagination,
  ParticipantStatusChip,
  useUi,
} from "../ui";
import { PARTICIPANT_STATUS_LABELS } from "../labels";

const PAGE_SIZE = 50;

export function ParticipantsPage() {
  const { notify, confirm } = useUi();
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const [participants, setParticipants] = useState<AdminParticipant[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);

  const [completedFile, setCompletedFile] = useState<File | null>(null);
  const [completedReport, setCompletedReport] = useState<CompletedImportReport | null>(null);
  const [completedError, setCompletedError] = useState<string | null>(null);
  const [completedUploading, setCompletedUploading] = useState(false);
  const [completedDragging, setCompletedDragging] = useState(false);
  const completedInputRef = useRef<HTMLInputElement | null>(null);

  const [editing, setEditing] = useState<AdminParticipant | null>(null);
  const [editName, setEditName] = useState("");
  const [editStatus, setEditStatus] = useState<ParticipantStatus>("eligible");
  const [editNotes, setEditNotes] = useState("");
  const [editError, setEditError] = useState<string | null>(null);
  const [savingEdit, setSavingEdit] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (appliedQuery) params.set("query", appliedQuery);
      if (statusFilter) params.set("status", statusFilter);
      params.set("limit", String(PAGE_SIZE));
      params.set("offset", String(offset));
      const response = await adminApi.get<ParticipantListResponse>(`/participants?${params.toString()}`);
      setParticipants(response.participants);
      setTotal(response.total);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [appliedQuery, statusFilter, offset]);

  useEffect(() => {
    void load();
  }, [load, reloadNonce]);

  const refresh = useCallback(() => {
    setReloadNonce((value) => value + 1);
  }, []);

  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setOffset(0);
    setAppliedQuery(query.trim());
  }

  function openEdit(participant: AdminParticipant) {
    setEditing(participant);
    setEditName(participant.name);
    setEditStatus(participant.status);
    setEditNotes(participant.notes ?? "");
    setEditError(null);
  }

  async function handleCompletedImport() {
    if (!completedFile) {
      setCompletedError("请先选择 CSV 或 XLSX 文件");
      return;
    }
    setCompletedUploading(true);
    setCompletedError(null);
    setCompletedReport(null);
    try {
      const report = await adminApi.upload<CompletedImportReport>(
        "/participants/import-completed",
        fileUploadForm(completedFile),
      );
      setCompletedReport(report);
      notify(
        `导入完成：新建 ${report.created} 行，匹配 ${report.matched} 行，未匹配 ${report.unmatched} 行`,
      );
      setCompletedFile(null);
      if (completedInputRef.current) completedInputRef.current.value = "";
      refresh();
    } catch (err) {
      setCompletedError(errorMessage(err));
    } finally {
      setCompletedUploading(false);
    }
  }

  function acceptDroppedFile(
    event: ReactDragEvent<HTMLDivElement>,
    setFile: (file: File | null) => void,
    setDragging: (value: boolean) => void,
  ): void {
    event.preventDefault();
    event.stopPropagation();
    setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) setFile(file);
  }

  async function toggleDisabled(participant: AdminParticipant) {
    if (participant.status === "disabled") {
      setBusyId(participant.id);
      try {
        await adminApi.patch(`/participants/${participant.id}`, { status: "eligible" });
        notify(`已启用 ${participant.name}`);
        refresh();
      } catch (err) {
        notify(errorMessage(err), "error");
      } finally {
        setBusyId(null);
      }
      return;
    }
    const ok = await confirm({
      title: "停用被试",
      message: `确认停用 ${participant.name}？停用后该被试仍可登录，但不能预约新的场次。已有的实验记录、预约和付款数据不会被删除。`,
      confirmLabel: "停用",
      danger: true,
    });
    if (!ok) return;
    setBusyId(participant.id);
    try {
      await adminApi.patch(`/participants/${participant.id}`, { status: "disabled" });
      notify(`已停用 ${participant.name}`);
      refresh();
    } catch (err) {
      notify(errorMessage(err), "error");
    } finally {
      setBusyId(null);
    }
  }

  async function saveEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editing) return;
    if (!editName.trim()) {
      setEditError("姓名不能为空");
      return;
    }
    if (editStatus === "disabled" && editing.status !== "disabled") {
      const ok = await confirm({
        title: "停用被试",
        message: `保存后 ${editName.trim()} 将被停用，仍可登录，但不能预约新的场次。已有记录会保留。`,
        confirmLabel: "停用并保存",
        danger: true,
      });
      if (!ok) return;
    }
    setSavingEdit(true);
    setEditError(null);
    try {
      await adminApi.patch(`/participants/${editing.id}`, {
        name: editName.trim(),
        status: editStatus,
        notes: editNotes.trim(),
      });
      notify("被试信息已更新");
      setEditing(null);
      refresh();
    } catch (err) {
      setEditError(errorMessage(err));
    } finally {
      setSavingEdit(false);
    }
  }

  const statusOptions = useMemo(
    () =>
      (Object.keys(PARTICIPANT_STATUS_LABELS) as ParticipantStatus[]).map((value) => ({
        value,
        label: PARTICIPANT_STATUS_LABELS[value],
      })),
    [],
  );

  return (
    <div>
      <PageHeader
        title="被试名单"
        subtitle="查看已注册参与者、维护状态，并上传历史已完成名单。"
      />

      <div className="admin-grid">
        <section className="admin-card" aria-labelledby="completed-import-title">
          <h2 className="admin-section-title" id="completed-import-title">
            导入历史已完成名单
          </h2>
          <p className="admin-hint">
            接受 CSV 或 XLSX。文件需要包含姓名和手机号列，可选备注列。手机号不存在时新建参与者并标记为已完成；姓名与已有记录不一致时列为未匹配。
          </p>
          <div
            className={`admin-file-drop${completedDragging ? " is-dragover" : ""}`}
            onDragOver={(event) => {
              event.preventDefault();
              event.dataTransfer.dropEffect = "copy";
              setCompletedDragging(true);
            }}
            onDragLeave={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                setCompletedDragging(false);
              }
            }}
            onDrop={(event) => acceptDroppedFile(event, setCompletedFile, setCompletedDragging)}
          >
            <input
              ref={completedInputRef}
              type="file"
              accept=".csv,.xlsx,.xlsm"
              data-testid="participants-import-completed"
              onChange={(event) => setCompletedFile(event.target.files?.[0] ?? null)}
              aria-label="选择历史已完成名单文件"
            />
            <p className="admin-drop-hint">也可以将 CSV 或 XLSX 文件拖拽到此处。</p>
            <div className="admin-submit-row">
              <button
                type="button"
                className="admin-btn admin-btn-primary"
                onClick={() => void handleCompletedImport()}
                disabled={completedUploading || !completedFile}
                data-testid="participants-import-completed-submit"
              >
                <UserCheck size={16} />
                {completedUploading ? "导入中" : "上传并导入"}
              </button>
              <span className="admin-hint">{completedFile ? completedFile.name : "尚未选择文件"}</span>
            </div>
          </div>
          {completedError ? <div className="admin-error" role="alert">{completedError}</div> : null}
          {completedReport ? (
            <div className="admin-import-report" data-testid="participants-import-completed-report">
              <h3>导入报告</h3>
              <div className="admin-import-summary">
                <span>读取 {completedReport.total} 行</span>
                <span>新建 {completedReport.created} 行</span>
                <span>匹配 {completedReport.matched} 行</span>
                <span>未匹配 {completedReport.unmatched} 行</span>
              </div>
              {completedReport.rows.length > 0 ? (
                <div className="admin-import-errors" style={{ maxHeight: "180px" }}>
                  {completedReport.rows.map((item, index) => (
                    <div
                      key={`${item.row}-${index}`}
                      className="admin-import-error-row"
                      style={
                        item.status === "unmatched"
                          ? undefined
                          : { color: "var(--admin-success)" }
                      }
                    >
                      第 {item.row} 行 {item.name}（{item.phoneMasked}）：
                      {item.status === "created"
                        ? "新建成功"
                        : item.status === "matched"
                          ? "匹配成功"
                          : item.error ?? "未匹配"}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </section>
      </div>

      <section className="admin-card" aria-labelledby="participant-list-title" style={{ marginTop: "20px" }}>
        <div className="admin-stat-row" style={{ marginBottom: "16px" }}>
          <h2 className="admin-section-title" id="participant-list-title" style={{ marginBottom: 0 }}>
            参与者列表
          </h2>
          <span className="admin-hint">共 {total} 人</span>
        </div>
        <form className="admin-toolbar" onSubmit={handleSearch}>
          <input
            className="admin-input admin-search"
            placeholder="按姓名或备注搜索"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="搜索参与者"
            data-testid="participants-search"
          />
          <button type="submit" className="admin-btn admin-btn-secondary">
            <Search size={15} />
            搜索
          </button>
          <select
            className="admin-select"
            value={statusFilter}
            onChange={(event) => {
              setStatusFilter(event.target.value);
              setOffset(0);
            }}
            aria-label="按状态筛选"
            style={{ maxWidth: "180px" }}
            data-testid="participants-status-filter"
          >
            <option value="">全部状态</option>
            {statusOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          {(appliedQuery || statusFilter) && (
            <button
              type="button"
              className="admin-btn admin-btn-ghost"
              onClick={() => {
                setQuery("");
                setAppliedQuery("");
                setStatusFilter("");
                setOffset(0);
              }}
            >
              清除筛选
            </button>
          )}
        </form>

        {error ? <ErrorNotice message={error} onRetry={() => void load()} /> : null}
        {loading ? (
          <LoadingBlock rows={6} label="正在加载参与者" />
        ) : participants.length === 0 ? (
          <EmptyState
            icon={Users}
            title="暂无匹配的参与者"
            description="参与者首次登录后会自动出现在这里。也可以调整搜索条件。"
          />
        ) : (
          <>
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>姓名</th>
                    <th>手机号</th>
                    <th>状态</th>
                    <th>同意时间</th>
                    <th>创建时间</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {participants.map((participant) => (
                    <tr key={participant.id}>
                      <td>
                        <div>{participant.name}</div>
                        {participant.notes ? (
                          <div className="admin-hint" style={{ marginTop: "2px" }}>
                            {participant.notes}
                          </div>
                        ) : null}
                      </td>
                      <td className="admin-mono">{participant.phoneMasked}</td>
                      <td>
                        <ParticipantStatusChip status={participant.status} />
                      </td>
                      <td>{formatDateTime(participant.consentedAt)}</td>
                      <td>{formatDateTime(participant.createdAt)}</td>
                      <td className="admin-actions-cell">
                        <button
                          type="button"
                          className="admin-btn admin-btn-ghost admin-btn-sm"
                          onClick={() => openEdit(participant)}
                          data-testid={`participant-edit-${participant.id}`}
                        >
                          <Pencil size={13} />
                          编辑
                        </button>
                        <button
                          type="button"
                          className={`admin-btn admin-btn-sm ${
                            participant.status === "disabled" ? "admin-btn-secondary" : "admin-btn-ghost"
                          }`}
                          onClick={() => void toggleDisabled(participant)}
                          disabled={busyId === participant.id}
                          data-testid={`participant-toggle-${participant.id}`}
                        >
                          {participant.status === "disabled" ? <UserCheck size={13} /> : <UserX size={13} />}
                          {participant.status === "disabled" ? "启用" : "停用"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination total={total} offset={offset} limit={PAGE_SIZE} onChange={setOffset} />
          </>
        )}
      </section>

      {editing ? (
        <Modal title="编辑被试" onClose={() => setEditing(null)}>
          <form onSubmit={saveEdit}>
            <Field label="姓名" htmlFor="participant-name">
              <input
                id="participant-name"
                className="admin-input"
                value={editName}
                onChange={(event) => setEditName(event.target.value)}
                data-testid="participant-edit-name"
              />
            </Field>
            <Field label="手机号">
              <input className="admin-input" value={editing.phoneMasked} readOnly disabled />
            </Field>
            <Field
              label="状态"
              htmlFor="participant-status"
              hint="停用不会删除实验记录。已完成表示不再参与新的实验。"
            >
              <select
                id="participant-status"
                className="admin-select"
                value={editStatus}
                onChange={(event) => setEditStatus(event.target.value as ParticipantStatus)}
              >
                {statusOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="备注" htmlFor="participant-notes">
              <textarea
                id="participant-notes"
                className="admin-textarea"
                value={editNotes}
                onChange={(event) => setEditNotes(event.target.value)}
                style={{ minHeight: "90px" }}
              />
            </Field>
            {editError ? <InlineNotice tone="error">{editError}</InlineNotice> : null}
            <div className="admin-modal-actions">
              <button type="button" className="admin-btn admin-btn-secondary" onClick={() => setEditing(null)}>
                取消
              </button>
              <button
                type="submit"
                className="admin-btn admin-btn-primary"
                disabled={savingEdit}
                data-testid="participant-edit-save"
              >
                {savingEdit ? "保存中" : "保存"}
              </button>
            </div>
          </form>
        </Modal>
      ) : null}
    </div>
  );
}
