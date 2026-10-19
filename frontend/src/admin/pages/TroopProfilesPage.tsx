import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Copy, Lock, Plus, Save, SlidersHorizontal, Trash2 } from "lucide-react";
import type { TroopProfile, TroopProfileRow, TroopProfileVersion } from "../../shared/types";
import { formatDateTime } from "../../shared/format";
import { adminApi, errorMessage } from "../api";
import type {
  TroopProfileDraftPayload,
  TroopProfileListResponse,
  TroopProfileResponse,
} from "../types";
import {
  EmptyState,
  ErrorNotice,
  Field,
  InlineNotice,
  LoadingBlock,
  Modal,
  PageHeader,
  StatusChip,
  VersionStatusChip,
  useUi,
} from "../ui";

type Selection = string | "new" | null;

interface RowDraft {
  soldiersA: string;
  soldiersB: string;
}

const DEFAULT_ROWS: TroopProfileRow[] = [
  { soldiersA: 7, soldiersB: 7 },
  { soldiersA: 8, soldiersB: 8 },
  { soldiersA: 7, soldiersB: 7 },
  { soldiersA: 8, soldiersB: 9 },
  { soldiersA: 7, soldiersB: 8 },
  { soldiersA: 9, soldiersB: 8 },
  { soldiersA: 8, soldiersB: 7 },
];

function rowsFromVersion(version: TroopProfileVersion): RowDraft[] {
  return version.rows.map((row) => ({
    soldiersA: String(row.soldiersA),
    soldiersB: String(row.soldiersB),
  }));
}

function defaultRowDrafts(): RowDraft[] {
  return DEFAULT_ROWS.map((row) => ({
    soldiersA: String(row.soldiersA),
    soldiersB: String(row.soldiersB),
  }));
}

function parsePositiveInteger(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed);
  if (!Number.isInteger(parsed) || parsed < 1) return null;
  return parsed;
}

function rowLabel(index: number): string {
  return index === 0 ? "练习行" : `正式第 ${index} 行`;
}

function buildPayload(
  name: string,
  rows: RowDraft[],
): { payload: TroopProfileDraftPayload | null; errors: string[] } {
  const errors: string[] = [];
  const trimmedName = name.trim();
  if (!trimmedName) errors.push("请填写方案名称");
  if (rows.length < 2) errors.push("至少需要一行练习配置和一行正式配置");
  const parsedRows: TroopProfileRow[] = [];
  rows.forEach((row, index) => {
    const soldiersA = parsePositiveInteger(row.soldiersA);
    const soldiersB = parsePositiveInteger(row.soldiersB);
    if (soldiersA === null) {
      errors.push(`${rowLabel(index)}的玩家 A 兵力必须是正整数`);
    }
    if (soldiersB === null) {
      errors.push(`${rowLabel(index)}的玩家 B 兵力必须是正整数`);
    }
    if (soldiersA !== null && soldiersB !== null) {
      parsedRows.push({ soldiersA, soldiersB });
    }
  });
  if (errors.length > 0) return { payload: null, errors };
  return {
    payload: {
      name: trimmedName,
      rows: parsedRows,
    },
    errors: [],
  };
}

export function TroopProfilesPage() {
  const { notify, confirm } = useUi();
  const [profiles, setProfiles] = useState<TroopProfile[]>([]);
  const [selection, setSelection] = useState<Selection>(null);
  const [name, setName] = useState("");
  const [rows, setRows] = useState<RowDraft[]>(() => defaultRowDrafts());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [copySource, setCopySource] = useState<TroopProfileVersion | null>(null);
  const [copyName, setCopyName] = useState("");
  const [copyError, setCopyError] = useState<string | null>(null);
  const [copying, setCopying] = useState(false);

  const allVersions = profiles.flatMap((profile) =>
    profile.versions.map((version) => ({ profile, version })),
  );
  const selectedEntry =
    selection !== "new" && selection !== null
      ? allVersions.find((entry) => entry.version.id === selection) ?? null
      : null;
  const selectedVersion = selectedEntry?.version ?? null;
  const selectedProfile = selectedEntry?.profile ?? null;
  const isNew = selection === "new";
  const readOnly = selectedVersion !== null && selectedVersion.status !== "draft";
  const builtIn = selectedProfile?.builtIn ?? false;
  const formalTrials = Math.max(0, rows.length - 1);

  const applyVersion = useCallback((version: TroopProfileVersion) => {
    setSelection(version.id);
    setName(version.name);
    setRows(rowsFromVersion(version));
    setValidationErrors([]);
    setSaveError(null);
  }, []);

  const reload = useCallback(
    async (preferredId?: string): Promise<TroopProfileVersion[]> => {
      const response = await adminApi.get<TroopProfileListResponse>("/troop-profiles");
      setProfiles(response.profiles);
      const versions = response.profiles.flatMap((profile) =>
        profile.versions.map((version) => ({ profile, version })),
      );
      if (preferredId) {
        const target = versions.find((entry) => entry.version.id === preferredId);
        if (target) applyVersion(target.version);
      }
      return versions.map((entry) => entry.version);
    },
    [applyVersion],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const response = await adminApi.get<TroopProfileListResponse>("/troop-profiles");
        if (cancelled) return;
        setProfiles(response.profiles);
        const versions = response.profiles.flatMap((profile) =>
          profile.versions.map((version) => ({ profile, version })),
        );
        const preferred =
          versions.find(
            (entry) => entry.profile.builtIn && entry.version.status === "published",
          ) ??
          versions.find((entry) => entry.version.status === "published") ??
          versions[0] ??
          null;
        if (preferred) applyVersion(preferred.version);
        setError(null);
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [applyVersion]);

  function startNew() {
    setSelection("new");
    setName("");
    setRows(defaultRowDrafts());
    setValidationErrors([]);
    setSaveError(null);
  }

  function startNextVersion(version: TroopProfileVersion) {
    setSelection("new");
    setName(version.name);
    setRows(rowsFromVersion(version));
    setValidationErrors([]);
    setSaveError(null);
    notify("已基于当前版本载入新草稿，保存后生成下一版本");
  }

  function updateRow(index: number, field: "soldiersA" | "soldiersB", value: string) {
    if (readOnly) return;
    setRows((current) =>
      current.map((row, rowIndex) =>
        rowIndex === index ? { ...row, [field]: value } : row,
      ),
    );
  }

  function addFormalRow() {
    if (readOnly) return;
    setRows((current) => {
      const last = current[current.length - 1];
      return [
        ...current,
        {
          soldiersA: last?.soldiersA ?? "7",
          soldiersB: last?.soldiersB ?? "7",
        },
      ];
    });
  }

  function removeFormalRow(index: number) {
    if (readOnly || index === 0) return;
    if (rows.length <= 2) {
      notify("至少需要保留一行正式配置", "error");
      return;
    }
    setRows((current) => current.filter((_, rowIndex) => rowIndex !== index));
  }

  async function persistDraft(showNotice: boolean): Promise<string | null> {
    const result = buildPayload(name, rows);
    setValidationErrors(result.errors);
    if (!result.payload) {
      setSaveError(null);
      if (showNotice) notify("请先修正兵力配置方案错误", "error");
      return null;
    }
    setSaving(true);
    setSaveError(null);
    try {
      if (isNew || selection === null) {
        const response = await adminApi.post<TroopProfileResponse>(
          "/troop-profiles",
          result.payload,
        );
        await reload(response.troopProfile.id);
        if (showNotice) {
          notify(`方案草稿已创建，版本 ${response.troopProfile.version}`);
        }
        return response.troopProfile.id;
      }
      const response = await adminApi.patch<TroopProfileResponse>(
        `/troop-profiles/${selection}`,
        { rows: result.payload.rows },
      );
      await reload(response.troopProfile.id);
      if (showNotice) notify("兵力配置方案草稿已保存");
      return response.troopProfile.id;
    } catch (err) {
      setSaveError(errorMessage(err));
      if (showNotice) notify(errorMessage(err), "error");
      return null;
    } finally {
      setSaving(false);
    }
  }

  async function handleSave() {
    await persistDraft(true);
  }

  async function handlePublish() {
    const check = buildPayload(name, rows);
    setValidationErrors(check.errors);
    if (!check.payload) {
      notify("请先修正兵力配置方案错误", "error");
      return;
    }
    const ok = await confirm({
      title: "发布兵力配置方案",
      message:
        "发布后同名已发布的版本会归档。已使用旧版本创建的地图组不受影响。发布后本版本不可修改。",
      confirmLabel: "发布",
    });
    if (!ok) return;
    setPublishing(true);
    setSaveError(null);
    try {
      const id = await persistDraft(false);
      if (!id) return;
      await adminApi.post(`/troop-profiles/${id}/publish`);
      await reload(id);
      notify("兵力配置方案已发布");
    } catch (err) {
      setSaveError(errorMessage(err));
      notify(errorMessage(err), "error");
    } finally {
      setPublishing(false);
    }
  }

  function openCopy(version: TroopProfileVersion) {
    setCopySource(version);
    setCopyName(`${version.name}-copy`);
    setCopyError(null);
  }

  async function handleCopy() {
    if (!copySource) return;
    const trimmedName = copyName.trim();
    if (!trimmedName) {
      setCopyError("请填写方案名称");
      return;
    }
    setCopying(true);
    setCopyError(null);
    try {
      const response = await adminApi.post<TroopProfileResponse>(
        `/troop-profiles/${copySource.id}/copy`,
        { name: trimmedName },
      );
      setCopySource(null);
      await reload(response.troopProfile.id);
      notify(`已复制为草稿：${response.troopProfile.name} · 第 ${response.troopProfile.version} 版`);
    } catch (err) {
      setCopyError(errorMessage(err));
    } finally {
      setCopying(false);
    }
  }

  const editorTitle = isNew
    ? "新建兵力配置方案"
    : selectedVersion
      ? `${selectedVersion.name} · 第 ${selectedVersion.version} 版`
      : "兵力配置方案";

  return (
    <div>
      <PageHeader
        title="兵力方案"
        subtitle="维护练习与正式对局的 A/B 兵力。每行数值同时作为出生格初始兵力与每格每回合收益。发布后的版本不可修改。"
        actions={
          <button
            type="button"
            className="admin-btn admin-btn-primary"
            onClick={startNew}
            data-testid="troop-profile-create"
          >
            <Plus size={16} />
            新建方案
          </button>
        }
      />

      {error ? <ErrorNotice message={error} onRetry={() => void reload()} /> : null}

      {loading ? (
        <LoadingBlock rows={6} label="正在加载兵力配置方案" />
      ) : profiles.length === 0 && selection !== "new" ? (
        <EmptyState
          icon={SlidersHorizontal}
          title="暂无兵力配置方案"
          description="新建方案并发布后，才能在创建地图组时选择。"
          action={
            <button type="button" className="admin-btn admin-btn-primary" onClick={startNew}>
              新建方案
            </button>
          }
        />
      ) : (
        <div className="admin-layout-columns">
          <aside className="admin-card admin-sticky-side">
            <h2 className="admin-section-title">方案与版本</h2>
            <div className="admin-version-list">
              {profiles.map((profile) => (
                <div key={profile.id} className="admin-profile-group">
                  <div className="admin-profile-group-head">
                    <span>{profile.name}</span>
                    {profile.builtIn ? <StatusChip tone="info">内置</StatusChip> : null}
                  </div>
                  {[...profile.versions]
                    .sort((left, right) => right.version - left.version)
                    .map((version) => (
                      <button
                        type="button"
                        key={version.id}
                        className={`admin-version-item${
                          selection === version.id ? " active" : ""
                        }`}
                        onClick={() => applyVersion(version)}
                        data-testid={`troop-profile-version-${version.id}`}
                      >
                        <div className="admin-version-item-head">
                          <span>第 {version.version} 版</span>
                          <VersionStatusChip status={version.status} />
                        </div>
                        <div className="admin-version-item-meta">
                          练习 1 局 + 正式 {version.formalTrials} 局
                        </div>
                        <div className="admin-version-item-meta">
                          发布：{formatDateTime(version.publishedAt)}
                        </div>
                      </button>
                    ))}
                </div>
              ))}
              {isNew ? (
                <div className="admin-version-item active" style={{ cursor: "default" }}>
                  <div className="admin-version-item-head">
                    <span>新草稿</span>
                    <StatusChip>未保存</StatusChip>
                  </div>
                  <div className="admin-version-item-meta">保存后生成版本号</div>
                </div>
              ) : null}
            </div>
          </aside>

          <section className="admin-card">
            <div className="admin-questionnaire-editor-head">
              <div>
                <h2 className="admin-section-title" style={{ marginBottom: "4px" }}>
                  {editorTitle}
                </h2>
                <div className="admin-chip-list">
                  {selectedVersion ? (
                    <VersionStatusChip status={selectedVersion.status} />
                  ) : (
                    <StatusChip>未保存</StatusChip>
                  )}
                  {builtIn ? <StatusChip tone="info">内置方案</StatusChip> : null}
                  {readOnly ? <span className="admin-hint">只读</span> : null}
                </div>
              </div>
              <div className="admin-btn-row">
                {readOnly ? (
                  <>
                    <span className="admin-hint">
                      <Lock size={13} style={{ verticalAlign: "-2px", marginRight: "4px" }} />
                      已发布版本只读
                    </span>
                    {builtIn ? (
                      <button
                        type="button"
                        className="admin-btn admin-btn-secondary"
                        onClick={() => selectedVersion && openCopy(selectedVersion)}
                        data-testid="troop-profile-copy"
                      >
                        <Copy size={15} />
                        复制为自定义方案
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="admin-btn admin-btn-secondary"
                        onClick={() => selectedVersion && startNextVersion(selectedVersion)}
                        data-testid="troop-profile-new-version"
                      >
                        <Plus size={15} />
                        新建下一版本
                      </button>
                    )}
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      className="admin-btn admin-btn-secondary"
                      onClick={() => void handleSave()}
                      disabled={saving || publishing}
                      data-testid="troop-profile-save"
                    >
                      <Save size={15} />
                      {saving ? "保存中" : "保存草稿"}
                    </button>
                    <button
                      type="button"
                      className="admin-btn admin-btn-primary"
                      onClick={() => void handlePublish()}
                      disabled={saving || publishing}
                      data-testid="troop-profile-publish"
                    >
                      <CheckCircle2 size={15} />
                      {publishing ? "发布中" : "发布"}
                    </button>
                  </>
                )}
              </div>
            </div>

            {validationErrors.length > 0 ? (
              <InlineNotice tone="error">
                <ul className="admin-validation-list">
                  {validationErrors.map((message, index) => (
                    <li key={`${message}-${index}`}>{message}</li>
                  ))}
                </ul>
              </InlineNotice>
            ) : null}
            {saveError ? <InlineNotice tone="error">{saveError}</InlineNotice> : null}
            {readOnly ? (
              <div className="admin-readonly-banner">
                <Lock size={14} />
                该版本已发布或归档，所有配置只读。复制后可在新草稿中继续修改。
              </div>
            ) : null}

            <div className="admin-form-section">
              <h3 className="admin-section-title">方案信息</h3>
              <div className="admin-form-row">
                <Field
                  label="方案名称"
                  htmlFor="troop-profile-name"
                  hint={
                    isNew
                      ? "保存时若名称已存在，将在该方案下生成下一版本。"
                      : "方案名称在创建后不可修改。"
                  }
                >
                  <input
                    id="troop-profile-name"
                    className="admin-input"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    disabled={readOnly || !isNew}
                    placeholder="例如：默认兵力方案"
                    data-testid="troop-profile-name"
                  />
                </Field>
                <Field
                  label="对局结构"
                  hint="练习对局固定为 1 局，正式对局数等于正式行数。"
                >
                  <div className="admin-profile-summary">
                    <span className="admin-chip">练习 1 局</span>
                    <span className="admin-chip">正式 {formalTrials} 局</span>
                    <span className="admin-hint">共 {rows.length} 行配置</span>
                  </div>
                </Field>
              </div>
            </div>

            <div className="admin-form-section">
              <div className="admin-condition-toolbar">
                <h3 className="admin-section-title" style={{ marginBottom: 0 }}>
                  A/B 兵力行
                </h3>
                <span className="admin-hint">
                  A/B 数值同时用于出生格初始兵力与每格每回合收益。
                </span>
              </div>
              <div className="admin-table-wrap">
                <table className="admin-table admin-compact-table">
                  <thead>
                    <tr>
                      <th style={{ width: "88px" }}>行</th>
                      <th>阶段</th>
                      <th>玩家 A 兵力</th>
                      <th>玩家 B 兵力</th>
                      <th style={{ width: "88px" }}>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, index) => (
                      <tr key={index}>
                        <td className="admin-mono">{index}</td>
                        <td>
                          {index === 0 ? (
                            <span className="admin-inline-actions">
                              练习
                              <StatusChip tone="info">固定 1 局</StatusChip>
                            </span>
                          ) : (
                            <>正式 {index}</>
                          )}
                        </td>
                        <td>
                          <input
                            className="admin-input"
                            type="number"
                            min="1"
                            step="1"
                            value={row.soldiersA}
                            onChange={(event) =>
                              updateRow(index, "soldiersA", event.target.value)
                            }
                            disabled={readOnly}
                            aria-label={`${rowLabel(index)}玩家 A 兵力`}
                            data-testid={`troop-profile-row-${index}-a`}
                          />
                        </td>
                        <td>
                          <input
                            className="admin-input"
                            type="number"
                            min="1"
                            step="1"
                            value={row.soldiersB}
                            onChange={(event) =>
                              updateRow(index, "soldiersB", event.target.value)
                            }
                            disabled={readOnly}
                            aria-label={`${rowLabel(index)}玩家 B 兵力`}
                            data-testid={`troop-profile-row-${index}-b`}
                          />
                        </td>
                        <td>
                          {index === 0 ? (
                            <span className="admin-hint">不可删除</span>
                          ) : (
                            <button
                              type="button"
                              className="admin-btn admin-btn-ghost admin-btn-sm"
                              onClick={() => removeFormalRow(index)}
                              disabled={readOnly || rows.length <= 2}
                              aria-label={`删除正式第 ${index} 行`}
                              data-testid={`troop-profile-remove-row-${index}`}
                            >
                              <Trash2 size={14} />
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!readOnly ? (
                <div className="admin-add-button-row">
                  <button
                    type="button"
                    className="admin-btn admin-btn-secondary admin-btn-sm"
                    onClick={addFormalRow}
                    data-testid="troop-profile-add-row"
                  >
                    <Plus size={14} />
                    添加正式行
                  </button>
                </div>
              ) : null}
              <p className="admin-hint">
                第 0 行固定为练习。正式行按顺序用于地图组，正式对局数必须与地图组配置一致。A/B 数值必须是正整数。
              </p>
            </div>
          </section>
        </div>
      )}

      {copySource ? (
        <Modal
          title="复制为自定义方案"
          onClose={() => {
            if (!copying) setCopySource(null);
          }}
          footer={
            <>
              <button
                type="button"
                className="admin-btn admin-btn-secondary"
                onClick={() => setCopySource(null)}
                disabled={copying}
              >
                取消
              </button>
              <button
                type="button"
                className="admin-btn admin-btn-primary"
                onClick={() => void handleCopy()}
                disabled={copying}
                data-testid="troop-profile-copy-confirm"
              >
                <Copy size={15} />
                {copying ? "复制中" : "创建草稿"}
              </button>
            </>
          }
        >
          <p className="admin-hint">
            来源：{copySource.name} · 第 {copySource.version} 版。内置方案只读，复制后将创建可编辑的自定义方案草稿。
          </p>
          <Field
            label="方案名称"
            htmlFor="troop-profile-copy-name"
            hint="新方案名称不能与现有方案重复。"
          >
            <input
              id="troop-profile-copy-name"
              className="admin-input"
              value={copyName}
              onChange={(event) => setCopyName(event.target.value)}
              data-testid="troop-profile-copy-name"
            />
          </Field>
          {copyError ? <InlineNotice tone="error">{copyError}</InlineNotice> : null}
        </Modal>
      ) : null}
    </div>
  );
}
