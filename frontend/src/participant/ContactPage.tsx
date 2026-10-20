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
        title="联系实验工作人员"
        description="遇到实验、问卷或付款问题时，请通过以下方式联系实验工作人员。"
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
          <h3 className="p-label">建议联系实验工作人员的情况</h3>
          <ul className="contact-topics">
            <li>另一名参与者缺席、断线后无法重新连接，或实验被意外提前结束。</li>
            <li>你主动退出后发现状态或报酬记录不正确。</li>
            <li>后测问卷无法打开、提交失败，或提交后仍显示待填写。</li>
            <li>到场费、报酬金额、支付状态或支付截止日期与预期不符。</li>
            <li>无法登录、预约、取消预约，或无法重新预约。</li>
          </ul>
          <p className="p-muted contact-note">
            因网络或系统故障提前结束的到场费支付截止日期为提交后测问卷后的第一个周日
            24:00（北京时间）；如逾期未收到，请通过以上方式联系实验工作人员。
          </p>
        </section>
      )}

      <PageLinks items={["home", "history"]} />
    </PageFrame>
  );
}
