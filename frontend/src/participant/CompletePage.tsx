import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { formatDateTime, formatMoney } from "../shared/format";
import type { ExperimentRecord, Payment } from "../shared/types";
import type { MyExperimentsResponse, MyPaymentsResponse } from "./apiTypes";
import { formatUnknownError, isUnauthorized } from "./apiTypes";
import { LoadingCard, PageLinks, StatusChip, SubpageHeader } from "./common";
import { PageFrame, useSession } from "./session";

export default function CompletePage() {
  const session = useSession();
  const [searchParams] = useSearchParams();
  const roomId = searchParams.get("room") ?? "";
  const [payments, setPayments] = useState<Payment[]>([]);
  const [experiments, setExperiments] = useState<ExperimentRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setLoadError("");
    Promise.all([
      session.request<MyPaymentsResponse>("/api/my-payments"),
      session.request<MyExperimentsResponse>("/api/my-experiments"),
    ])
      .then(([paymentResponse, experimentResponse]) => {
        if (!alive) return;
        setPayments(paymentResponse.payments);
        setExperiments(experimentResponse.experiments);
      })
      .catch((error: unknown) => {
        if (!alive || isUnauthorized(error)) return;
        setLoadError(formatUnknownError(error, "无法加载完成信息，请稍后重试。"));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [session, reloadToken]);

  const experiment =
    experiments.find((item) => item.roomId === roomId) ?? null;
  const payment =
    payments.find((item) => item.roomId === roomId) ??
    experiment?.payment ??
    null;
  const startsAt = payment?.roomStartsAt ?? experiment?.startsAt ?? null;

  return (
    <PageFrame narrow>
      <SubpageHeader
        title="实验完成信息"
        description="本次实验的记录与费用结算信息。"
      />

      {loading ? (
        <LoadingCard text="正在加载完成信息…" />
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
      ) : roomId === "" ? (
        <div className="p-card">
          <div className="p-banner p-banner-warning" role="status">
            缺少实验编号。请从实验结束页面或历史实验记录进入。
          </div>
          <PageLinks items={["home", "history", "contact"]} />
        </div>
      ) : experiment === null && payment === null ? (
        <div className="p-card">
          <div className="p-banner p-banner-warning" role="status">
            未找到该实验的记录。请确认链接是否完整，或查看历史实验。
          </div>
          <PageLinks items={["home", "history", "contact"]} />
        </div>
      ) : (
        <>
          <section className="p-card" aria-labelledby="complete-summary-title">
            <div className="p-row">
              <h2 className="p-section-title" id="complete-summary-title">
                实验记录
              </h2>
              <StatusChip tone="success">实验已完成</StatusChip>
            </div>
            <dl className="p-detail-list">
              <div className="p-detail-row">
                <dt>实验时间</dt>
                <dd>{formatDateTime(startsAt)}</dd>
              </div>
              <div className="p-detail-row">
                <dt>角色</dt>
                <dd>
                  {experiment?.role === 1
                    ? "圆形玩家"
                    : experiment?.role === 2
                      ? "菱形玩家"
                      : "—"}
                </dd>
              </div>
              <div className="p-detail-row">
                <dt>后测问卷</dt>
                <dd>
                  {experiment?.questionnaireStatus === "completed"
                    ? "已完成"
                    : experiment?.questionnaireStatus === "in_progress"
                      ? "填写中"
                      : experiment?.questionnaireStatus === "not_started"
                        ? "未开始"
                        : "—"}
                </dd>
              </div>
            </dl>
          </section>

          <section className="p-card" aria-labelledby="complete-pay-title">
            <div className="p-row">
              <h2 className="p-section-title" id="complete-pay-title">
                费用结算
              </h2>
              <span data-testid="payment-status">
                <StatusChip
                  tone={
                    payment === null
                      ? "warning"
                      : payment.status === "paid"
                        ? "success"
                        : "warning"
                  }
                >
                  {payment === null
                    ? "待处理"
                    : payment.status === "paid"
                      ? "已支付"
                      : "待支付"}
                </StatusChip>
              </span>
            </div>

            <div className="p-payment-row">
              <span>基础费</span>
              <span className="p-mono">
                {payment === null ? "待处理" : formatMoney(payment.basePayCents)}
              </span>
            </div>
            <div className="p-payment-row">
              <span>绩效费</span>
              <span className="p-mono">
                {payment === null
                  ? "待处理"
                  : formatMoney(payment.performancePayCents)}
              </span>
            </div>
            <div className="p-payment-row p-payment-total">
              <span>合计</span>
              <span className="p-mono" data-testid="complete-total">
                {payment === null ? "待处理" : formatMoney(payment.totalCents)}
              </span>
            </div>

            <dl className="p-detail-list p-payment-details">
              <div className="p-detail-row">
                <dt>支付截止日期</dt>
                <dd>
                  {payment === null ? "待结算" : formatDateTime(payment.deadlineAt)}
                </dd>
              </div>
              {payment?.status === "paid" && payment.paidAt ? (
                <div className="p-detail-row">
                  <dt>支付时间</dt>
                  <dd>{formatDateTime(payment.paidAt)}</dd>
                </div>
              ) : null}
            </dl>

            <p className="p-muted">
              款项将在当周周日 24:00 前完成转账。如逾期未收到，请通过“联系主试”与实验组织者核对。
            </p>
            {payment === null ? (
              <div className="p-banner p-banner-info" role="status">
                费用记录尚未生成，当前状态为待处理。主试完成结算后，这里会显示具体金额与支付截止时间。
              </div>
            ) : null}
          </section>

          <PageLinks items={["home", "history", "contact"]} />
        </>
      )}
    </PageFrame>
  );
}
