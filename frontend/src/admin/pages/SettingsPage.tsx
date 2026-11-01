import { useCallback, useEffect, useState } from "react";
import { KeyRound, RefreshCw, Save, ShieldCheck } from "lucide-react";
import { formatDateTime } from "../../shared/format";
import type { AdminSettings } from "../../shared/types";
import { adminApi, errorMessage } from "../api";
import {
  ErrorNotice,
  Field,
  InlineNotice,
  LoadingBlock,
  PageHeader,
  StatusChip,
  useUi,
} from "../ui";

interface SettingsFormState {
  jatosBaseUrl: string;
  jatosStudyCode: string;
  jatosStudyId: string;
  contactInfo: string;
  timezone: string;
}

function formFromSettings(settings: AdminSettings): SettingsFormState {
  return {
    jatosBaseUrl: settings.jatosBaseUrl,
    jatosStudyCode: settings.jatosStudyCode,
    jatosStudyId: settings.jatosStudyId,
    contactInfo: settings.contactInfo ?? "",
    timezone: settings.timezone,
  };
}

export function SettingsPage() {
  const { notify } = useUi();
  const [settings, setSettings] = useState<AdminSettings | null>(null);
  const [form, setForm] = useState<SettingsFormState>({
    jatosBaseUrl: "",
    jatosStudyCode: "",
    jatosStudyId: "",
    contactInfo: "",
    timezone: "",
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [formErrors, setFormErrors] = useState<Partial<Record<keyof SettingsFormState, string>>>({});
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await adminApi.get<AdminSettings>("/settings");
      setSettings(response);
      setForm(formFromSettings(response));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const dirty =
    settings !== null &&
    (form.jatosBaseUrl !== settings.jatosBaseUrl ||
      form.jatosStudyCode !== settings.jatosStudyCode ||
      form.jatosStudyId !== settings.jatosStudyId ||
      form.contactInfo !== (settings.contactInfo ?? "") ||
      form.timezone !== settings.timezone);

  function validate(): boolean {
    const errors: Partial<Record<keyof SettingsFormState, string>> = {};
    const baseUrl = form.jatosBaseUrl.trim();
    if (baseUrl && !/^https?:\/\/\S+$/i.test(baseUrl)) {
      errors.jatosBaseUrl = "JATOS 地址必须以 http:// 或 https:// 开头";
    }
    const studyId = form.jatosStudyId.trim();
    if (studyId && !/^\d+$/.test(studyId) && studyId.length !== 36) {
      errors.jatosStudyId = "JATOS study ID 必须是数字或 UUID";
    }
    if (!form.timezone.trim()) {
      errors.timezone = "请填写时区";
    }
    setFormErrors(errors);
    return Object.keys(errors).length === 0;
  }

  async function handleSave() {
    if (!validate()) return;
    setSaving(true);
    setSaveError(null);
    try {
      await adminApi.patch("/settings", {
        jatosBaseUrl: form.jatosBaseUrl.trim(),
        jatosStudyCode: form.jatosStudyCode.trim(),
        jatosStudyId: form.jatosStudyId.trim(),
        contactInfo: form.contactInfo.trim(),
        timezone: form.timezone.trim(),
      });
      notify("设置已保存");
      await load();
    } catch (err) {
      setSaveError(errorMessage(err));
      notify(errorMessage(err), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="设置"
        subtitle="配置 JATOS 集成、联系方式和时区。JATOS token 只从服务端环境变量读取，界面不显示明文。"
        actions={
          <button
            type="button"
            className="admin-btn admin-btn-primary"
            onClick={() => void handleSave()}
            disabled={saving || loading}
            data-testid="settings-save"
          >
            <Save size={16} />
            {saving ? "保存中" : "保存设置"}
          </button>
        }
      />

      {error ? <ErrorNotice message={error} onRetry={() => void load()} /> : null}

      {loading ? (
        <LoadingBlock rows={6} label="正在加载设置" />
      ) : (
        <div className="admin-stack">
          {dirty ? <InlineNotice tone="warning">有未保存的设置修改。</InlineNotice> : null}
          {saveError ? <InlineNotice tone="error">{saveError}</InlineNotice> : null}

          <section className="admin-card">
            <h2 className="admin-section-title">JATOS 集成</h2>
            <div className="admin-form-row">
              <Field
                label="JATOS 地址"
                htmlFor="settings-jatos-url"
                error={formErrors.jatosBaseUrl}
                hint="例如 https://jatos.example.com。修改地址后需要同步更新环境变量并重启服务实例，CORS 与问卷组件平台地址在启动或构建时确定。"
              >
                <input
                  id="settings-jatos-url"
                  className="admin-input"
                  value={form.jatosBaseUrl}
                  onChange={(event) => setForm({ ...form, jatosBaseUrl: event.target.value })}
                  placeholder="https://jatos.example.com"
                  data-testid="settings-jatos-url"
                />
              </Field>
              <Field label="Study Code" htmlFor="settings-jatos-study-code">
                <input
                  id="settings-jatos-study-code"
                  className="admin-input"
                  value={form.jatosStudyCode}
                  onChange={(event) =>
                    setForm({ ...form, jatosStudyCode: event.target.value })
                  }
                  data-testid="settings-jatos-study-code"
                />
              </Field>
            </div>
            <div className="admin-form-row">
              <Field
                label="JATOS study ID"
                htmlFor="settings-jatos-study-id"
                error={formErrors.jatosStudyId}
                hint="部署脚本输出的 studyId 或 studyUuid。自动同步使用该 study 的问卷结果。"
              >
                <input
                  id="settings-jatos-study-id"
                  className="admin-input"
                  value={form.jatosStudyId}
                  onChange={(event) =>
                    setForm({ ...form, jatosStudyId: event.target.value })
                  }
                  data-testid="settings-jatos-study-id"
                />
              </Field>
            </div>
            <div className="admin-settings-status" style={{ marginTop: "4px" }}>
              <KeyRound size={16} aria-hidden="true" />
              <span>JATOS API Token</span>
              <span data-testid="settings-token-status">
                {settings?.hasJatosToken ? (
                  <StatusChip tone="success">已配置</StatusChip>
                ) : (
                  <StatusChip tone="warning">未配置</StatusChip>
                )}
              </span>
            </div>
            <div className="admin-settings-status" style={{ marginTop: "4px" }}>
              <RefreshCw size={16} aria-hidden="true" />
              <span>自动同步</span>
              <span data-testid="settings-sync-status">
                {settings?.jatosSync.configured ? (
                  settings.jatosSync.status === "error" ? (
                    <StatusChip tone="error">异常</StatusChip>
                  ) : settings.jatosSync.status === "ok" ? (
                    settings.jatosSync.lastError ? (
                      <StatusChip tone="warning">有错误</StatusChip>
                    ) : (
                      <StatusChip tone="success">正常</StatusChip>
                    )
                  ) : (
                    <StatusChip tone="neutral">等待运行</StatusChip>
                  )
                ) : (
                  <StatusChip tone="warning">未启用</StatusChip>
                )}
              </span>
            </div>
            <p className="admin-hint" data-testid="settings-sync-last-run">
              {settings?.jatosSync.lastRunAt
                ? `最近运行 ${formatDateTime(settings.jatosSync.lastRunAt)}`
                : "尚未运行"}
              {settings?.jatosSync.lastSuccessAt
                ? `，最近成功 ${formatDateTime(settings.jatosSync.lastSuccessAt)}`
                : ""}
              {settings ? `，上次导入 ${settings.jatosSync.lastImported} 条` : ""}
            </p>
            {settings && !settings.jatosSync.configured ? (
              <p className="admin-hint">需要 JATOS study ID 和 API token 才会自动同步。</p>
            ) : null}
            {settings?.jatosSync.configured && settings.jatosSync.lastError ? (
              <InlineNotice tone="warning">{settings.jatosSync.lastError}</InlineNotice>
            ) : null}
            <p className="admin-hint">
              Token 仅在服务端通过环境变量配置，不会返回或显示明文。修改 token 需要重启服务实例。
            </p>
          </section>

          <section className="admin-card">
            <h2 className="admin-section-title">联系信息与时间</h2>
            <Field
              label="联系信息"
              htmlFor="settings-contact"
              hint="显示给参与者的联系方式，可包含邮箱、电话或办公地点。"
            >
              <textarea
                id="settings-contact"
                className="admin-textarea"
                value={form.contactInfo}
                onChange={(event) => setForm({ ...form, contactInfo: event.target.value })}
                style={{ minHeight: "110px" }}
                data-testid="settings-contact-info"
              />
            </Field>
            <div className="admin-form-row">
              <Field
                label="时区"
                htmlFor="settings-timezone"
                error={formErrors.timezone}
                hint="平台固定使用 Asia/Shanghai，所有展示和付款截止按该时区计算。"
              >
                <input
                  id="settings-timezone"
                  className="admin-input"
                  value="Asia/Shanghai"
                  readOnly
                  data-testid="settings-timezone"
                />
              </Field>
              <Field
                label="公开站点地址"
                htmlFor="settings-public-base-url"
                hint="来自服务端 PUBLIC_BASE_URL，只读。"
              >
                <input
                  id="settings-public-base-url"
                  className="admin-input"
                  value={settings?.publicBaseUrl ?? ""}
                  readOnly
                  style={{ backgroundColor: "var(--admin-surface)" }}
                />
              </Field>
            </div>
          </section>

          <div className="admin-card">
            <div className="admin-settings-status">
              <ShieldCheck size={18} aria-hidden="true" />
              <span>所有设置修改都会写入审计日志。</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
