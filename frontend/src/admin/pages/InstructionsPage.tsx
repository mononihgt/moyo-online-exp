import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, ImagePlus, Lock, Plus, Save, Upload } from "lucide-react";
import type {
  InstructionVersion,
  MapGroupVersion,
  MediaAsset,
} from "../../shared/types";
import { formatDateTime } from "../../shared/format";
import { adminApi, errorMessage, imageUploadForm } from "../api";
import type {
  InstructionListResponse,
  MapGroupListResponse,
  MediaListResponse,
  MediaUploadResponse,
} from "../types";
import { MarkdownPreview } from "../MarkdownPreview";
import {
  EmptyState,
  ErrorNotice,
  Field,
  InlineNotice,
  LoadingBlock,
  PageHeader,
  StatusChip,
  VersionStatusChip,
  formatBytes,
  useUi,
} from "../ui";
import { MAP_GROUP_MODE_LABELS } from "../labels";

type Selection = string | "new" | null;
type Role = 1 | 2;

interface DraftState {
  mapGroupVersionId: string;
  role: Role;
  markdown: string;
  minReadingSeconds: string;
}

const DEFAULT_MIN_SECONDS = "120";

function emptyDraft(mapGroupVersionId = ""): DraftState {
  return {
    mapGroupVersionId,
    role: 1,
    markdown: "",
    minReadingSeconds: DEFAULT_MIN_SECONDS,
  };
}

function draftFromVersion(version: InstructionVersion): DraftState {
  return {
    mapGroupVersionId: "",
    role: version.role,
    markdown: version.contentMarkdown,
    minReadingSeconds: String(version.minReadingSeconds),
  };
}

function derivedName(prefix: string, role: Role): string {
  return `${prefix}-${role === 1 ? "A" : "B"}`;
}

export function InstructionsPage() {
  const { notify, confirm } = useUi();
  const [versions, setVersions] = useState<InstructionVersion[]>([]);
  const [mapGroups, setMapGroups] = useState<MapGroupVersion[]>([]);
  const [selection, setSelection] = useState<Selection>(null);
  const [draft, setDraft] = useState<DraftState>(() => emptyDraft());
  const [savedMarkdown, setSavedMarkdown] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [media, setMedia] = useState<MediaAsset[]>([]);
  const [mediaError, setMediaError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const selected =
    selection !== "new" && selection !== null
      ? versions.find((version) => version.id === selection) ?? null
      : null;
  const isNew = selection === "new";
  const readOnly = selected !== null && selected.status !== "draft";

  const publishedGroups = mapGroups.filter((group) => group.status === "published");
  const selectedGroup =
    publishedGroups.find(
      (group) =>
        group.versionId === draft.mapGroupVersionId || group.id === draft.mapGroupVersionId,
    ) ?? null;
  const selectedGroupPrefix = selectedGroup?.name ?? null;
  const previewName =
    selectedGroupPrefix !== null ? derivedName(selectedGroupPrefix, draft.role) : null;

  const dirty =
    isNew ||
    (selected !== null &&
      (draft.markdown !== savedMarkdown ||
        draft.minReadingSeconds !== String(selected.minReadingSeconds)));

  const applyVersion = useCallback((version: InstructionVersion | null) => {
    if (version === null) {
      setSelection(null);
      setDraft(emptyDraft());
      setSavedMarkdown("");
      return;
    }
    setSelection(version.id);
    setDraft(draftFromVersion(version));
    setSavedMarkdown(version.contentMarkdown);
  }, []);

  const loadMedia = useCallback(async () => {
    try {
      const response = await adminApi.get<MediaListResponse>("/media?limit=100");
      setMedia(response.media.filter((asset) => asset.contentType.startsWith("image/")));
      setMediaError(null);
    } catch (err) {
      setMediaError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [instructionResponse, mapGroupResponse] = await Promise.all([
          adminApi.get<InstructionListResponse>("/instructions"),
          adminApi.get<MapGroupListResponse>("/map-groups"),
        ]);
        if (cancelled) return;
        setVersions(instructionResponse.instructions);
        setMapGroups(mapGroupResponse.mapGroups);
        const preferred =
          instructionResponse.instructions.find((item) => item.status === "published") ??
          instructionResponse.instructions[0] ??
          null;
        applyVersion(preferred);
        if (preferred === null) {
          const firstGroup =
            mapGroupResponse.mapGroups.find((group) => group.status === "published") ?? null;
          setDraft(emptyDraft(firstGroup?.versionId ?? ""));
        }
        setError(null);
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    void loadMedia();
    return () => {
      cancelled = true;
    };
  }, [applyVersion, loadMedia]);

  const loadVersions = useCallback(
    async (preferredId?: string) => {
      const response = await adminApi.get<InstructionListResponse>("/instructions");
      setVersions(response.instructions);
      const targetId = preferredId ?? (selection !== "new" ? selection : null);
      if (targetId) {
        const version = response.instructions.find((item) => item.id === targetId);
        applyVersion(version ?? null);
      } else if (selection === null) {
        const preferred =
          response.instructions.find((item) => item.status === "published") ??
          response.instructions[0] ??
          null;
        applyVersion(preferred);
      }
      return response.instructions;
    },
    [selection, applyVersion],
  );

  function startNew() {
    const firstGroup = publishedGroups[0] ?? null;
    setSelection("new");
    setDraft(emptyDraft(firstGroup?.versionId ?? ""));
    setSavedMarkdown("");
    setError(null);
  }

  function insertAsset(asset: MediaAsset) {
    const snippet = `![${asset.filename}](asset://${asset.id})`;
    const textarea = textareaRef.current;
    if (!textarea) {
      setDraft((current) => ({ ...current, markdown: `${current.markdown}\n${snippet}` }));
      notify("已追加图片引用");
      return;
    }
    const start = textarea.selectionStart ?? draft.markdown.length;
    const end = textarea.selectionEnd ?? start;
    const nextMarkdown =
      draft.markdown.slice(0, start) + snippet + draft.markdown.slice(end);
    setDraft((current) => ({ ...current, markdown: nextMarkdown }));
    const cursor = start + snippet.length;
    window.requestAnimationFrame(() => {
      textarea.focus();
      textarea.setSelectionRange(cursor, cursor);
    });
    notify(`已插入 ${asset.filename} 的图片引用`);
  }

  async function uploadImage(file: File) {
    setUploading(true);
    setMediaError(null);
    try {
      const response = await adminApi.upload<MediaUploadResponse>(
        "/media",
        imageUploadForm(file, "instruction-image"),
      );
      setMedia((current) => [response.asset, ...current]);
      insertAsset(response.asset);
    } catch (err) {
      setMediaError(errorMessage(err));
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  function validateDraft(): string | null {
    if (isNew) {
      if (!draft.mapGroupVersionId) return "请选择已发布的地图组";
      if (!selectedGroup) return "所选地图组不是已发布状态，请重新选择";
    }
    if (!draft.markdown.trim()) return "指导语正文不能为空";
    const seconds = Number(draft.minReadingSeconds);
    if (!Number.isInteger(seconds) || seconds < 0) {
      return "最短阅读时间必须是非负整数";
    }
    return null;
  }

  async function persistDraft(showNotice: boolean): Promise<string | null> {
    const validation = validateDraft();
    if (validation) {
      notify(validation, "error");
      return null;
    }
    const minReadingSeconds = Number(draft.minReadingSeconds);
    try {
      if (isNew) {
        const response = await adminApi.post<{ instruction: InstructionVersion }>(
          "/instructions",
          {
            mapGroupVersionId: selectedGroup?.versionId ?? draft.mapGroupVersionId,
            role: draft.role,
            markdown: draft.markdown,
            minReadingSeconds,
          },
        );
        await loadVersions(response.instruction.id);
        if (showNotice) {
          notify(`已创建 ${response.instruction.name} 第 ${response.instruction.version} 版草稿`);
        }
        return response.instruction.id;
      }
      if (selected) {
        if (!dirty) return selected.id;
        await adminApi.patch<{ instruction: InstructionVersion }>(
          `/instructions/${selected.id}`,
          {
            markdown: draft.markdown,
            minReadingSeconds,
          },
        );
        await loadVersions(selected.id);
        if (showNotice) notify("草稿已保存");
        return selected.id;
      }
    } catch (err) {
      setError(errorMessage(err));
      notify(errorMessage(err), "error");
      return null;
    }
    notify("请先新建草稿", "error");
    return null;
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      await persistDraft(true);
    } finally {
      setSaving(false);
    }
  }

  async function handlePublish() {
    const validation = validateDraft();
    if (validation) {
      notify(validation, "error");
      return;
    }
    const ok = await confirm({
      title: "发布指导语",
      message:
        "发布后同名已发布的指导语会归档，新进入房间的参与者将看到该版本。发布后本版本不可修改。",
      confirmLabel: "发布",
    });
    if (!ok) return;
    setPublishing(true);
    setError(null);
    try {
      const id = await persistDraft(false);
      if (!id) return;
      await adminApi.post(`/instructions/${id}/publish`);
      await loadVersions(id);
      notify("指导语已发布");
    } catch (err) {
      setError(errorMessage(err));
      notify(errorMessage(err), "error");
    } finally {
      setPublishing(false);
    }
  }

  const roleOne = versions.filter((version) => version.role === 1);
  const roleTwo = versions.filter((version) => version.role === 2);

  function renderVersionGroup(role: Role, items: InstructionVersion[]) {
    if (items.length === 0) return null;
    return (
      <>
        <h3 className="admin-version-group-title">玩家 {role}</h3>
        <div className="admin-version-list">
          {items.map((version) => (
            <button
              type="button"
              key={version.id}
              className={`admin-version-item${selection === version.id ? " active" : ""}`}
              onClick={() => applyVersion(version)}
              data-testid={`instruction-version-${version.id}`}
            >
              <div className="admin-version-item-head">
                <span>
                  {version.name} · 第 {version.version} 版
                </span>
                <VersionStatusChip status={version.status} />
              </div>
              <div className="admin-version-item-meta">
                前缀 {version.mapGroupPrefix}
              </div>
              <div className="admin-version-item-meta">
                最短阅读 {version.minReadingSeconds} 秒
              </div>
              {version.contentHash ? (
                <div
                  className="admin-version-item-meta admin-mono"
                  title={version.contentHash}
                >
                  哈希 {version.contentHash.slice(0, 19)}…
                </div>
              ) : null}
              <div className="admin-version-item-meta">
                发布：{formatDateTime(version.publishedAt)}
              </div>
            </button>
          ))}
        </div>
      </>
    );
  }

  return (
    <div>
      <PageHeader
        title="指导语"
        subtitle="指导语绑定已发布地图组，名称由组前缀与 A/B 角色自动生成。正文支持 Markdown，可插入已上传的图片资产。"
        actions={
          <button
            type="button"
            className="admin-btn admin-btn-primary"
            onClick={startNew}
            data-testid="instruction-create"
          >
            <Plus size={16} />
            新建草稿
          </button>
        }
      />

      {error ? <ErrorNotice message={error} onRetry={() => void loadVersions()} /> : null}

      {loading ? (
        <LoadingBlock rows={6} label="正在加载指导语版本" />
      ) : versions.length === 0 && selection !== "new" ? (
        <EmptyState
          icon={ImagePlus}
          title="尚未创建指导语"
          description="选择已发布地图组，为角色 A 与角色 B 分别创建指导语并发布后，才能创建 Room。"
          action={
            <button type="button" className="admin-btn admin-btn-primary" onClick={startNew}>
              新建草稿
            </button>
          }
        />
      ) : (
        <div className="admin-layout-columns">
          <aside className="admin-card admin-sticky-side">
            <h2 className="admin-section-title">版本列表</h2>
            {renderVersionGroup(1, roleOne)}
            {renderVersionGroup(2, roleTwo)}
            {versions.length === 0 ? <p className="admin-hint">暂无历史版本。</p> : null}
            {isNew ? (
              <div className="admin-version-item active" style={{ marginTop: "8px", cursor: "default" }}>
                <div className="admin-version-item-head">
                  <span>新草稿</span>
                  <StatusChip>未保存</StatusChip>
                </div>
                <div className="admin-version-item-meta">
                  {previewName ?? "选择地图组后生成名称"}
                </div>
              </div>
            ) : null}
          </aside>

          <section className="admin-card">
            <div className="admin-questionnaire-editor-head">
              <div>
                <h2 className="admin-section-title" style={{ marginBottom: "4px" }}>
                  {isNew
                    ? "新建指导语"
                    : selected
                      ? `${selected.name} · 第 ${selected.version} 版`
                      : "指导语"}
                </h2>
                {selected ? (
                  <div className="admin-chip-list">
                    <VersionStatusChip status={selected.status} />
                    <span className="admin-hint">{selected.name}</span>
                    <span className="admin-hint">
                      玩家 {selected.role === 1 ? "A" : "B"}
                    </span>
                    {selected.publishedAt ? (
                      <span className="admin-hint">
                        发布于 {formatDateTime(selected.publishedAt)}
                      </span>
                    ) : null}
                  </div>
                ) : null}
              </div>
              <div className="admin-btn-row">
                {readOnly ? (
                  <span className="admin-hint">
                    <Lock size={13} style={{ verticalAlign: "-2px", marginRight: "4px" }} />
                    已发布版本只读
                  </span>
                ) : (
                  <>
                    <button
                      type="button"
                      className="admin-btn admin-btn-secondary"
                      onClick={() => void handleSave()}
                      disabled={saving || publishing || (!dirty && !isNew)}
                      data-testid="instruction-save"
                    >
                      <Save size={15} />
                      {saving ? "保存中" : "保存草稿"}
                    </button>
                    <button
                      type="button"
                      className="admin-btn admin-btn-primary"
                      onClick={() => void handlePublish()}
                      disabled={saving || publishing}
                      data-testid="instruction-publish"
                    >
                      <CheckCircle2 size={15} />
                      {publishing ? "发布中" : "发布"}
                    </button>
                  </>
                )}
              </div>
            </div>

            {readOnly ? (
              <>
                <InlineNotice tone="info">
                  已发布的指导语不可修改。如需调整内容，请新建草稿并发布新版本。
                </InlineNotice>
                <dl className="admin-detail-list">
                  <div>
                    <dt>名称</dt>
                    <dd>{selected.name}</dd>
                  </div>
                  <div>
                    <dt>地图组前缀</dt>
                    <dd>{selected.mapGroupPrefix}</dd>
                  </div>
                  <div>
                    <dt>角色</dt>
                    <dd>玩家 {selected.role === 1 ? "A" : "B"}</dd>
                  </div>
                  <div>
                    <dt>最短阅读时间</dt>
                    <dd>{selected.minReadingSeconds} 秒</dd>
                  </div>
                  <div>
                    <dt>内容哈希</dt>
                    <dd className="admin-mono admin-url-cell">{selected.contentHash ?? "—"}</dd>
                  </div>
                </dl>
                <div className="admin-preview" style={{ border: "1px solid var(--admin-border)" }}>
                  <MarkdownPreview markdown={draft.markdown} />
                </div>
              </>
            ) : (
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void handleSave();
                }}
              >
                {isNew ? (
                  <>
                    <div className="admin-form-row">
                      <Field
                        label="地图组"
                        htmlFor="instruction-map-group"
                        hint="只列出已发布的地图组版本。"
                        error={
                          publishedGroups.length === 0
                            ? "还没有已发布的地图组，请先在地图组页发布版本。"
                            : null
                        }
                      >
                        <select
                          id="instruction-map-group"
                          className="admin-select"
                          value={draft.mapGroupVersionId}
                          onChange={(event) =>
                            setDraft({ ...draft, mapGroupVersionId: event.target.value })
                          }
                          data-testid="instruction-map-group"
                        >
                          {publishedGroups.length === 0 ? (
                            <option value="">请先发布地图组</option>
                          ) : null}
                          {publishedGroups.map((group) => (
                            <option key={group.versionId} value={group.versionId}>
                              {group.name} · 第 {group.version} 版 · {group.rows}×{group.cols}
                              （{MAP_GROUP_MODE_LABELS[group.mode]}）
                            </option>
                          ))}
                        </select>
                      </Field>
                      <Field label="角色" htmlFor="instruction-role" hint="角色决定自动生成 A 或 B 名称。">
                        <select
                          id="instruction-role"
                          className="admin-select"
                          value={draft.role}
                          onChange={(event) =>
                            setDraft({
                              ...draft,
                              role: Number(event.target.value) === 2 ? 2 : 1,
                            })
                          }
                          data-testid="instruction-role"
                        >
                          <option value={1}>玩家 A（角色 1）</option>
                          <option value={2}>玩家 B（角色 2）</option>
                        </select>
                      </Field>
                      <Field
                        label="最短阅读时间（秒）"
                        htmlFor="instruction-min-seconds"
                        hint="参与者在计满该时长后才能继续。默认 120 秒。"
                      >
                        <input
                          id="instruction-min-seconds"
                          className="admin-input"
                          type="number"
                          min="0"
                          step="1"
                          value={draft.minReadingSeconds}
                          onChange={(event) =>
                            setDraft({ ...draft, minReadingSeconds: event.target.value })
                          }
                          data-testid="instruction-min-seconds"
                        />
                      </Field>
                    </div>
                    <div className="admin-derived-name" data-testid="instruction-derived-name">
                      <div className="admin-label">自动生成名称</div>
                      <div className="admin-derived-name-row">
                        {selectedGroupPrefix ? (
                          <>
                            <span
                              className={`admin-chip${draft.role === 1 ? " admin-chip-info" : ""}`}
                            >
                              {derivedName(selectedGroupPrefix, 1)}
                            </span>
                            <span
                              className={`admin-chip${draft.role === 2 ? " admin-chip-info" : ""}`}
                            >
                              {derivedName(selectedGroupPrefix, 2)}
                            </span>
                          </>
                        ) : (
                          <span className="admin-hint">选择地图组后显示派生名称。</span>
                        )}
                      </div>
                      <div className="admin-hint">
                        名称由服务端生成：地图组组前缀加角色后缀，不能自由填写。
                      </div>
                    </div>
                  </>
                ) : (
                  <div className="admin-form-row">
                    <Field label="名称">
                      <div className="admin-profile-summary">
                        <span className="admin-chip">{selected?.name}</span>
                        <span className="admin-hint">
                          玩家 {selected?.role === 1 ? "A" : "B"} · 前缀{" "}
                          {selected?.mapGroupPrefix}
                        </span>
                      </div>
                    </Field>
                    <Field
                      label="最短阅读时间（秒）"
                      htmlFor="instruction-min-seconds"
                      hint="参与者在计满该时长后才能继续。"
                    >
                      <input
                        id="instruction-min-seconds"
                        className="admin-input"
                        type="number"
                        min="0"
                        step="1"
                        value={draft.minReadingSeconds}
                        onChange={(event) =>
                          setDraft({ ...draft, minReadingSeconds: event.target.value })
                        }
                        data-testid="instruction-min-seconds"
                      />
                    </Field>
                  </div>
                )}

                {dirty ? <InlineNotice tone="warning">有未保存的修改。</InlineNotice> : null}

                <div className="admin-split-editor">
                  <div>
                    <div className="admin-editor-toolbar">
                      <span className="admin-label" style={{ marginBottom: 0 }}>
                        Markdown 正文
                      </span>
                      <button
                        type="button"
                        className="admin-btn admin-btn-secondary admin-btn-sm"
                        onClick={() => fileInputRef.current?.click()}
                        disabled={uploading}
                        data-testid="instruction-upload"
                      >
                        <Upload size={14} />
                        {uploading ? "上传中" : "上传图片并插入"}
                      </button>
                    </div>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept="image/*"
                      hidden
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        if (file) void uploadImage(file);
                      }}
                    />
                    <textarea
                      ref={textareaRef}
                      className="admin-textarea"
                      value={draft.markdown}
                      onChange={(event) =>
                        setDraft({ ...draft, markdown: event.target.value })
                      }
                      aria-label="指导语 Markdown 正文"
                      data-testid="instruction-markdown"
                      style={{ minHeight: "440px" }}
                    />
                  </div>
                  <div>
                    <div className="admin-editor-toolbar">
                      <span className="admin-label" style={{ marginBottom: 0 }}>
                        预览
                      </span>
                    </div>
                    <MarkdownPreview markdown={draft.markdown} />
                  </div>
                </div>
              </form>
            )}

            <section className="admin-form-section">
              <div className="admin-editor-toolbar" style={{ marginBottom: "12px" }}>
                <h3 className="admin-section-title" style={{ marginBottom: 0 }}>
                  图片资产
                </h3>
                <span className="admin-hint">上传或选择图片后插入到光标位置。</span>
              </div>
              {mediaError ? <InlineNotice tone="error">{mediaError}</InlineNotice> : null}
              <div className="admin-media-strip">
                <button
                  type="button"
                  className="admin-media-upload"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={readOnly || uploading}
                >
                  <ImagePlus size={22} />
                  <span>{uploading ? "上传中" : "上传图片"}</span>
                </button>
                {media.slice(0, 24).map((asset) => (
                  <div key={asset.id} className="admin-media-card">
                    <img src={asset.url} alt={asset.filename} />
                    <div className="admin-media-card-info">
                      <div className="admin-media-card-name" title={asset.filename}>
                        {asset.filename}
                      </div>
                      <div className="admin-hint">
                        {asset.width}×{asset.height} · {formatBytes(asset.sizeBytes)}
                      </div>
                      <div className="admin-hint admin-mono" style={{ wordBreak: "break-all" }}>
                        {asset.id}
                      </div>
                      <div
                        className="admin-hint admin-mono admin-url-cell"
                        title={asset.sha256}
                      >
                        {asset.sha256}
                      </div>
                      <button
                        type="button"
                        className="admin-btn admin-btn-secondary admin-btn-sm"
                        onClick={() => insertAsset(asset)}
                        disabled={readOnly}
                        data-testid={`instruction-asset-${asset.id}`}
                      >
                        插入引用
                      </button>
                    </div>
                  </div>
                ))}
                {media.length === 0 && !mediaError ? (
                  <div className="admin-hint">暂无图片资产。上传后可以插入到指导语。</div>
                ) : null}
              </div>
            </section>
          </section>
        </div>
      )}
    </div>
  );
}
