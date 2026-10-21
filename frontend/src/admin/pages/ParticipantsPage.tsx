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
  const [editPhone, setEditPhone] = useState("");
  const [editStatus, setEditStatus] = useState<ParticipantStatus>("eligible");
  const [editNotes, setEditNotes] = useState("");
  const [editError, setEditError] = useState<string | null>(null);
  const [savingEdit, setSavingEdit] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [mergeOpen, setMergeOpen] = useState(false);
  const [mergeSourceQuery, setMergeSourceQuery] = useState("");
  const [mergeTargetQuery, setMergeTargetQuery] = useState("");
  const [mergeSourceOptions, setMergeSourceOptions] = useState<AdminParticipant[]>([]);
  const [mergeTargetOptions, setMergeTargetOptions] = useState<AdminParticipant[]>([]);
  const [mergeSource, setMergeSource] = useState<AdminParticipant | null>(null);
  const [mergeTarget, setMergeTarget] = useState<AdminParticipant | null>(null);
  const [mergeKeepPhone, setMergeKeepPhone] = useState<"target" | "source">("target");
  const [mergeFinalName, setMergeFinalName] = useState("");
  const [mergeReason, setMergeReason] = useState("");
  const [mergeError, setMergeError] = useState<string | null>(null);
  const [merging, setMerging] = useState(false);

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
    setEditPhone("");
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
        phone: editPhone.trim() || undefined,
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

  async function searchMergeCandidates(
    query: string,
    setter: (items: AdminParticipant[]) => void,
  ) {
    if (!query.trim()) {
      setter([]);
      return;
    }
    try {
      const params = new URLSearchParams({
        query: query.trim(),
        limit: "10",
      });
      const response = await adminApi.get<ParticipantListResponse>(
        `/participants?${params.toString()}`,
      );
      setter(
        response.participants.filter(
          (item) => item.status !== "merged" && item.status !== "disabled",
        ),
      );
    } catch (err) {
      setMergeError(errorMessage(err));
    }
  }

  function openMerge() {
    setMergeSourceQuery("");
    setMergeTargetQuery("");
    setMergeSourceOptions([]);
    setMergeTargetOptions([]);
    setMergeSource(null);
    setMergeTarget(null);
    setMergeKeepPhone("target");
    setMergeFinalName("");
    setMergeReason("");
    setMergeError(null);
    setMergeOpen(true);
  }

  async function submitMerge(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMergeError(null);
    if (!mergeSource || !mergeTarget) {
      setMergeError("请选择来源账号和目标账号");
      return;
    }
    if (mergeSource.id === mergeTarget.id) {
      setMergeError("来源账号和目标账号不能相同");
      return;
    }
    if (!mergeReason.trim()) {
      setMergeError("必须填写合并原因");
      return;
    }
    const ok = await confirm({
      title: "合并账号",
      message: `确认把 ${mergeSource.name}（${mergeSource.phoneMasked}）合并到 ${mergeTarget.name}（${mergeTarget.phoneMasked}）？所有信息、实验数据、问卷记录和报酬记录会迁移到目标账号，来源账号会保留为已合并状态。`,
      confirmLabel: "确认合并",
      danger: true,
    });
    if (!ok) return;
    setMerging(true);
    try {
      await adminApi.post("/participants/merge", {
        sourceId: mergeSource.id,
        targetId: mergeTarget.id,
        keepPhoneFrom: mergeKeepPhone,
        finalName: mergeFinalName.trim() || undefined,
        reason: mergeReason.trim(),
      });
      notify("账号已合并");
      setMergeOpen(false);
      refresh();
    } catch (err) {
      setMergeError(errorMessage(err));
    } finally {
      setMerging(false);
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
            placeholder="按姓名、备注或完整手机号搜索"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="搜索参与者"
            data-testid="participants-search"
          />
          <button type="submit" className="admin-btn admin-btn-secondary">
            <Search size={15} />
            搜索
          </button>
          <button
            type="button"
            className="admin-btn admin-btn-secondary"
            onClick={openMerge}
            data-testid="participants-merge-open"
          >
            <Users size={15} />
            合并账号
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
                        {participant.status === "merged" ? (
                          <span className="admin-hint">
                            已合并到{" "}
                            {participant.mergedIntoName ??
                              participant.mergedIntoId ??
                              "目标账号"}
                          </span>
                        ) : (
                          <>
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
                          </>
                        )}
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
            <Field
              label="手机号"
              htmlFor="participant-phone"
              hint={`当前 ${editing.phoneMasked}。留空表示不修改；输入完整新手机号后保存。`}
            >
              <input
                id="participant-phone"
                className="admin-input"
                value={editPhone}
                onChange={(event) => setEditPhone(event.target.value)}
                placeholder="输入完整新手机号"
                data-testid="participant-edit-phone"
              />
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
                {statusOptions
                  .filter((option) => option.value !== "merged")
                  .map((option) => (
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

      {mergeOpen ? (
        <Modal title="合并账号" onClose={() => setMergeOpen(false)}>
          <form onSubmit={submitMerge}>
            <p className="admin-hint" style={{ margin: "0 0 16px", lineHeight: 1.7 }}>
              当同一名参与者因为更换手机号或姓名登记不一致而出现两个账号时，可以把其中一个账号合并到另一个账号。合并后，两个手机号都能登录，所有信息、实验数据、问卷记录和报酬记录都会归到目标账号，来源账号保留为已合并状态。两个账号存在进行中的预约或同一场实验记录时不能合并。
            </p>
            <Field
              label="来源账号"
              hint="所有信息、实验数据、问卷记录和报酬记录会从来源账号迁移到目标账号；来源账号保留为已合并状态。"
            >
              <div className="admin-toolbar">
                <input
                  className="admin-input admin-search"
                  value={mergeSourceQuery}
                  onChange={(event) => setMergeSourceQuery(event.target.value)}
                  placeholder="姓名或完整手机号"
                  data-testid="participants-merge-source-query"
                />
                <button
                  type="button"
                  className="admin-btn admin-btn-secondary"
                  onClick={() =>
                    void searchMergeCandidates(
                      mergeSourceQuery,
                      setMergeSourceOptions,
                    )
                  }
                >
                  查找
                </button>
              </div>
              {mergeSource ? (
                <InlineNotice tone="info">
                  来源：{mergeSource.name}（{mergeSource.phoneMasked}）
                </InlineNotice>
              ) : null}
              {mergeSourceOptions.length > 0 ? (
                <div className="admin-submit-row" style={{ flexWrap: "wrap" }}>
                  {mergeSourceOptions.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      className="admin-btn admin-btn-ghost admin-btn-sm"
                      onClick={() => {
                        setMergeSource(item);
                        setMergeSourceOptions([]);
                      }}
                    >
                      {item.name} {item.phoneMasked}
                    </button>
                  ))}
                </div>
              ) : null}
            </Field>

            <Field
              label="目标账号"
              hint="保留这个账号作为登录账号，所有信息、实验数据、问卷记录和报酬记录都归到这个账号。"
            >
              <div className="admin-toolbar">
                <input
                  className="admin-input admin-search"
                  value={mergeTargetQuery}
                  onChange={(event) => setMergeTargetQuery(event.target.value)}
                  placeholder="姓名或完整手机号"
                  data-testid="participants-merge-target-query"
                />
                <button
                  type="button"
                  className="admin-btn admin-btn-secondary"
                  onClick={() =>
                    void searchMergeCandidates(
                      mergeTargetQuery,
                      setMergeTargetOptions,
                    )
                  }
                >
                  查找
                </button>
              </div>
              {mergeTarget ? (
                <InlineNotice tone="info">
                  目标：{mergeTarget.name}（{mergeTarget.phoneMasked}）
                </InlineNotice>
              ) : null}
              {mergeTargetOptions.length > 0 ? (
                <div className="admin-submit-row" style={{ flexWrap: "wrap" }}>
                  {mergeTargetOptions.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      className="admin-btn admin-btn-ghost admin-btn-sm"
                      onClick={() => {
                        setMergeTarget(item);
                        setMergeTargetOptions([]);
                      }}
                    >
                      {item.name} {item.phoneMasked}
                    </button>
                  ))}
                </div>
              ) : null}
            </Field>

            <Field label="保留手机号">
              <select
                className="admin-select"
                value={mergeKeepPhone}
                onChange={(event) =>
                  setMergeKeepPhone(event.target.value as "target" | "source")
                }
              >
                <option value="target">
                  保留目标账号手机号
                  {mergeTarget ? `（${mergeTarget.phoneMasked}）` : ""}
                </option>
                <option value="source">
                  保留来源账号手机号
                  {mergeSource ? `（${mergeSource.phoneMasked}）` : ""}
                </option>
              </select>
            </Field>
            <Field
              label="最终姓名"
              hint="可选。留空保留目标账号姓名；合并后登录必须使用该姓名。"
            >
              <input
                className="admin-input"
                value={mergeFinalName}
                onChange={(event) => setMergeFinalName(event.target.value)}
              />
            </Field>
            <Field label="合并原因" hint="必填，会写入审计日志。">
              <textarea
                className="admin-textarea"
                value={mergeReason}
                onChange={(event) => setMergeReason(event.target.value)}
                style={{ minHeight: "80px" }}
                data-testid="participants-merge-reason"
              />
            </Field>
            {mergeError ? <InlineNotice tone="error">{mergeError}</InlineNotice> : null}
            <div className="admin-modal-actions">
              <button
                type="button"
                className="admin-btn admin-btn-secondary"
                onClick={() => setMergeOpen(false)}
              >
                取消
              </button>
              <button
                type="submit"
                className="admin-btn admin-btn-danger"
                disabled={merging}
                data-testid="participants-merge-submit"
              >
                {merging ? "合并中" : "确认合并"}
              </button>
            </div>
          </form>
        </Modal>
      ) : null}
    </div>
  );
}
