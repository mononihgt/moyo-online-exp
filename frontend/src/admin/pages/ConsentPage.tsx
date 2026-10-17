import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, FileText, Lock, Plus, Save } from "lucide-react";
import { formatDateTime } from "../../shared/format";
import { adminApi, errorMessage } from "../api";
import type { ConsentVersionAdmin, ConsentVersionListResponse } from "../types";
import { MarkdownPreview } from "../MarkdownPreview";
import {
  EmptyState,
  ErrorNotice,
  InlineNotice,
  LoadingBlock,
  PageHeader,
  StatusChip,
  VersionStatusChip,
  useUi,
} from "../ui";

type Selection = string | "new" | null;

export function ConsentPage() {
  const { notify, confirm } = useUi();
  const [versions, setVersions] = useState<ConsentVersionAdmin[]>([]);
  const [selection, setSelection] = useState<Selection>(null);
  const [markdown, setMarkdown] = useState("");
  const [savedMarkdown, setSavedMarkdown] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);

  const selected = selection !== "new" && selection !== null
    ? versions.find((version) => version.id === selection) ?? null
    : null;
  const isNew = selection === "new";
  const readOnly = selected !== null && selected.status !== "draft";
  const dirty = markdown !== savedMarkdown;

  const applySelection = useCallback((version: ConsentVersionAdmin | null) => {
    if (version === null) {
      setSelection(null);
      setMarkdown("");
      setSavedMarkdown("");
      return;
    }
    setSelection(version.id);
    setMarkdown(version.markdown);
    setSavedMarkdown(version.markdown);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await adminApi.get<ConsentVersionListResponse>("/consent-versions");
      setVersions(response.versions);
      if (selection === null) {
        const preferred =
          response.versions.find((version) => version.status === "published") ?? response.versions[0] ?? null;
        applySelection(preferred);
      } else if (selection !== "new") {
        const current = response.versions.find((version) => version.id === selection);
        if (current === undefined) {
          applySelection(response.versions[0] ?? null);
        }
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [selection, applySelection]);

  useEffect(() => {
    void load();
    // 只在首次挂载时加载；后续通过显式操作刷新
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function refreshKeeping(id: string) {
    const response = await adminApi.get<ConsentVersionListResponse>("/consent-versions");
    setVersions(response.versions);
    const current = response.versions.find((version) => version.id === id);
    if (current) {
      setSelection(current.id);
      setMarkdown(current.markdown);
      setSavedMarkdown(current.markdown);
    }
  }

  async function saveDraft(): Promise<string | null> {
    if (!markdown.trim()) {
      notify("同意书正文不能为空", "error");
      return null;
    }
    if (isNew) {
      const created = await adminApi.post<{ id: string; version: number }>("/consent-versions", {
        markdown,
      });
      await refreshKeeping(created.id);
      notify(`已创建第 ${created.version} 版草稿`);
      return created.id;
    }
    if (selected) {
      if (!dirty) {
        notify("内容没有修改");
        return selected.id;
      }
      await adminApi.patch(`/consent-versions/${selected.id}`, { markdown });
      await refreshKeeping(selected.id);
      notify("草稿已保存");
      return selected.id;
    }
    notify("请先新建草稿", "error");
    return null;
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      await saveDraft();
    } catch (err) {
      setError(errorMessage(err));
      notify(errorMessage(err), "error");
    } finally {
      setSaving(false);
    }
  }

  async function handlePublish() {
    if (!markdown.trim()) {
      notify("同意书正文不能为空", "error");
      return;
    }
    const ok = await confirm({
      title: "发布知情同意书",
      message:
        "发布后当前已发布的版本会归档，新登录的参与者将看到这一版本。已有同意记录会保留。发布后本版本不可再修改。",
      confirmLabel: "发布",
    });
    if (!ok) return;
    setPublishing(true);
    setError(null);
    try {
      let id: string | null = selected?.id ?? null;
      if (isNew) {
        const created = await adminApi.post<{ id: string; version: number }>("/consent-versions", {
          markdown,
        });
        id = created.id;
      } else if (selected && dirty) {
        await adminApi.patch(`/consent-versions/${selected.id}`, { markdown });
        id = selected.id;
      }
      if (!id) {
        notify("请先新建草稿", "error");
        return;
      }
      await adminApi.post(`/consent-versions/${id}/publish`);
      await refreshKeeping(id);
      notify("知情同意书已发布");
    } catch (err) {
      setError(errorMessage(err));
      notify(errorMessage(err), "error");
    } finally {
      setPublishing(false);
    }
  }

  function startNew() {
    setSelection("new");
    setMarkdown("");
    setSavedMarkdown("");
  }

  return (
    <div>
      <PageHeader
        title="知情同意"
        subtitle="编辑并发布参与者登录后阅读的知情同意书。"
        actions={
          <button
            type="button"
            className="admin-btn admin-btn-primary"
            onClick={startNew}
            data-testid="consent-create"
          >
            <Plus size={16} />
            新建草稿
          </button>
        }
      />

      {error ? <ErrorNotice message={error} onRetry={() => void load()} /> : null}
      {loading ? (
        <LoadingBlock rows={5} label="正在加载同意书版本" />
      ) : versions.length === 0 && selection !== "new" ? (
        <EmptyState
          icon={FileText}
          title="尚未创建知情同意书"
          description="创建草稿并发布后，参与者在首次登录时会被要求阅读并同意。"
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
            {versions.length === 0 ? (
              <p className="admin-hint">暂无历史版本。</p>
            ) : (
              <div className="admin-version-list">
                {versions.map((version) => (
                  <button
                    type="button"
                    key={version.id}
                    className={`admin-version-item${selection === version.id ? " active" : ""}`}
                    onClick={() => applySelection(version)}
                  >
                    <div className="admin-version-item-head">
                      <span>第 {version.version} 版</span>
                      <VersionStatusChip status={version.status} />
                    </div>
                    <div className="admin-version-item-meta">
                      创建：{formatDateTime(version.createdAt)}
                    </div>
                    <div className="admin-version-item-meta">
                      发布：{formatDateTime(version.publishedAt)}
                    </div>
                  </button>
                ))}
              </div>
            )}
            {selection === "new" ? (
              <div className="admin-version-item active" style={{ marginTop: "8px", cursor: "default" }}>
                <div className="admin-version-item-head">
                  <span>新草稿</span>
                  <StatusChip>未保存</StatusChip>
                </div>
                <div className="admin-version-item-meta">保存后生成版本号</div>
              </div>
            ) : null}
          </aside>

          <section className="admin-card">
            <div className="admin-questionnaire-editor-head">
              <div>
                <h2 className="admin-section-title" style={{ marginBottom: "4px" }}>
                  {isNew
                    ? "新建知情同意书"
                    : selected
                      ? `第 ${selected.version} 版`
                      : "知情同意书"}
                </h2>
                {selected ? (
                  <div className="admin-chip-list">
                    <VersionStatusChip status={selected.status} />
                    {selected.publishedAt ? (
                      <span className="admin-hint">发布于 {formatDateTime(selected.publishedAt)}</span>
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
                      data-testid="consent-save"
                    >
                      <Save size={15} />
                      {saving ? "保存中" : "保存草稿"}
                    </button>
                    <button
                      type="button"
                      className="admin-btn admin-btn-primary"
                      onClick={() => void handlePublish()}
                      disabled={saving || publishing}
                      data-testid="consent-publish"
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
                  已发布的同意书不可修改。如需调整内容，请新建草稿并发布新版本。
                </InlineNotice>
                <div className="admin-preview" style={{ border: "1px solid var(--admin-border)" }}>
                  <MarkdownPreview markdown={markdown} />
                </div>
              </>
            ) : (
              <>
                {dirty ? <InlineNotice tone="warning">有未保存的修改。</InlineNotice> : null}
                {isNew ? (
                  <InlineNotice tone="info">
                    这是尚未保存的新草稿。保存后可以继续编辑或发布。
                  </InlineNotice>
                ) : null}
                <div className="admin-split-editor">
                  <div>
                    <div className="admin-editor-toolbar">
                      <span className="admin-label" style={{ marginBottom: 0 }}>
                        Markdown 正文
                      </span>
                      <span className="admin-hint">支持标题、列表、表格和图片链接。</span>
                    </div>
                    <textarea
                      className="admin-textarea"
                      value={markdown}
                      onChange={(event) => setMarkdown(event.target.value)}
                      aria-label="知情同意 Markdown 正文"
                      data-testid="consent-markdown"
                      style={{ minHeight: "420px" }}
                    />
                  </div>
                  <div>
                    <div className="admin-editor-toolbar">
                      <span className="admin-label" style={{ marginBottom: 0 }}>
                        预览
                      </span>
                    </div>
                    <MarkdownPreview markdown={markdown} />
                  </div>
                </div>
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
