import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { formatDateTime } from "../shared/format";
import { api } from "../shared/api";
import type { ConsentDocument } from "../shared/types";
import { formatUnknownError, isUnauthorized } from "./apiTypes";
import type { ConsentSubmitResponse } from "./apiTypes";
import { PageFrame, useSession } from "./session";

export default function ConsentPage() {
  const navigate = useNavigate();
  const session = useSession();
  const [document, setDocument] = useState<ConsentDocument | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [submitting, setSubmitting] = useState<"agree" | "decline" | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setLoadError("");
    session
      .request<ConsentDocument>("/api/consent")
      .then((response) => {
        if (alive) setDocument(response);
      })
      .catch((error: unknown) => {
        if (!alive || isUnauthorized(error)) return;
        setLoadError(formatUnknownError(error, "无法加载知情同意书，请稍后重试。"));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [session, reloadToken]);

  const submitConsent = async (agree: boolean) => {
    if (document === null || submitting !== null) return;
    setActionError("");
    setSubmitting(agree ? "agree" : "decline");
    try {
      const response = await session.request<ConsentSubmitResponse>("/api/consent", {
        method: "POST",
        body: JSON.stringify({ versionId: document.versionId, agree }),
      });
      if (!agree) {
        navigate("/login", {
          replace: true,
          state: { notice: "你已拒绝知情同意并退出登录。" },
        });
        return;
      }
      if (response.me) {
        session.updateMe(response.me);
      } else {
        await session.refreshMe();
      }
      navigate("/", { replace: true });
    } catch (error: unknown) {
      if (isUnauthorized(error)) return;
      setActionError(formatUnknownError(error, "提交知情同意失败，请稍后重试。"));
    } finally {
      setSubmitting(null);
    }
  };

  return (
    <PageFrame narrow>
      <header className="p-consent-header">
        <p className="p-login-logo">Moyo 实验平台</p>
        <h1 className="p-title">知情同意</h1>
        {document !== null ? (
          <p className="p-muted">
            版本 {document.version} · 更新时间 {formatDateTime(document.publishedAt)}
          </p>
        ) : null}
      </header>

      {actionError !== "" ? (
        <div className="p-banner p-banner-error" role="alert">
          {actionError}
        </div>
      ) : null}

      {loading ? (
        <div className="p-card p-empty" role="status">
          正在加载知情同意书…
        </div>
      ) : loadError !== "" ? (
        <div className="p-card">
          <div className="p-banner p-banner-error" role="alert">
            {loadError}
          </div>
          <button
            type="button"
            className="p-btn p-btn-secondary"
            onClick={() => setReloadToken((token) => token + 1)}
          >
            重新加载
          </button>
        </div>
      ) : document === null ? (
        <div className="p-card">
          <div className="p-banner p-banner-warning" role="alert">
            平台尚未发布知情同意书。请联系实验主试后再试。
          </div>
          <button
            type="button"
            className="p-btn p-btn-secondary"
            onClick={() => navigate("/contact")}
          >
            联系主试
          </button>
        </div>
      ) : (
        <>
          <article className="p-card">
            <div
              className="p-consent-body"
              dangerouslySetInnerHTML={{ __html: document.html }}
            />
          </article>
          <div className="p-btn-row p-consent-actions">
            <button
              type="button"
              data-testid="consent-agree"
              className="p-btn p-btn-primary"
              disabled={submitting !== null}
              onClick={() => void submitConsent(true)}
            >
              {submitting === "agree" ? "正在提交…" : "同意并继续"}
            </button>
            <button
              type="button"
              data-testid="consent-decline"
              className="p-btn p-btn-secondary"
              disabled={submitting !== null}
              onClick={() => void submitConsent(false)}
            >
              {submitting === "decline" ? "正在退出…" : "不同意并退出"}
            </button>
          </div>
        </>
      )}

      {session.me.consentRequired ? (
        <p className="p-muted p-consent-note">
          同意后，你的同意时间会记录在实验系统中。拒绝将退出登录，不创建预约。
        </p>
      ) : null}
    </PageFrame>
  );
}
