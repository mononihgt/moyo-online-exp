import { useEffect, useState } from "react";
import { Mail } from "lucide-react";

import type { ContactResponse } from "./apiTypes";
import { formatUnknownError, isUnauthorized } from "./apiTypes";
import { LoadingCard, PageLinks, SubpageHeader } from "./common";
import { PageFrame, useSession } from "./session";

export default function ContactPage() {
  const session = useSession();
  const [contact, setContact] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setLoadError("");
    session
      .request<ContactResponse>("/api/contact")
      .then((response) => {
        if (alive) setContact(response.contact);
      })
      .catch((error: unknown) => {
        if (!alive || isUnauthorized(error)) return;
        setLoadError(formatUnknownError(error, "无法加载联系方式，请稍后重试。"));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [session, reloadToken]);

  const contactText =
    contact !== null && contact.trim() !== ""
      ? contact
      : "向实验组织者获取";

  return (
    <PageFrame narrow>
      <SubpageHeader
        title="联系实验主试"
        description="遇到实验、问卷或付款问题时，请通过以下方式联系实验组织者。"
      />

      {loading ? (
        <LoadingCard text="正在加载联系方式…" />
      ) : loadError !== "" ? (
        <div className="p-card">
          <div className="p-banner p-banner-error" role="alert">
            {loadError}
          </div>
          <button
            type="button"
            className="p-btn p-btn-secondary"
            onClick={() => {
              setLoading(true);
              setReloadToken((token) => token + 1);
            }}
          >
            重新加载
          </button>
        </div>
      ) : (
        <section className="p-card" aria-labelledby="contact-title">
          <div className="p-row">
            <h2 className="p-section-title" id="contact-title">
              联系方式
            </h2>
            <Mail size={20} aria-hidden="true" className="p-muted-icon" />
          </div>
          <p className="contact-value" data-testid="contact-value">
            {contactText}
          </p>
          <div className="p-divider" />
          <h3 className="p-label">建议联系主试的情况</h3>
          <ul className="contact-topics">
            <li>搭档缺席、离线后无法重新连接，或实验被意外中止。</li>
            <li>后测问卷无法打开或提交失败。</li>
            <li>报酬金额或支付状态与预期不符。</li>
            <li>无法登录、预约或取消预约。</li>
          </ul>
        </section>
      )}

      <PageLinks items={["home", "history"]} />
    </PageFrame>
  );
}
