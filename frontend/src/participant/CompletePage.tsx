import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { formatDateTime, formatMoney } from "../shared/format";
import type { ExperimentRecord, Payment } from "../shared/types";
import type {
  MyExperimentsResponse,
  MyPaymentsResponse,
  QuestionnaireContextResponse,
} from "./apiTypes";
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
  const [questionnaireLoading, setQuestionnaireLoading] = useState(false);
  const [questionnaireError, setQuestionnaireError] = useState("");

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
  const questionnaireCompleted =
    experiment?.questionnaireStatus === "completed";
  const awaitingQuestionnaire =
    experiment !== null &&
    !questionnaireCompleted &&
    (experiment.roomStatus === "questionnaire" ||
      (experiment.roomStatus === "archived" &&
        experiment.archiveReason === "questionnaire_incomplete"));
  const abortedRoom =
    experiment !== null &&
    experiment.roomStatus === "archived" &&
    experiment.archiveReason !== null &&
    experiment.archiveReason !== "completed" &&
    experiment.archiveReason !== "questionnaire_incomplete";
  const completionChip: {
    label: string;
    tone: "neutral" | "success" | "warning" | "error";
  } = awaitingQuestionnaire
    ? { label: "待填写问卷", tone: "warning" }
    : questionnaireCompleted
      ? { label: "实验已完成", tone: "success" }
      : experiment?.roomStatus === "archived"
        ? { label: "实验已中止", tone: "error" }
        : { label: "实验进行中", tone: "neutral" };

  const openQuestionnaire = async () => {
    if (experiment === null || questionnaireLoading) return;
    setQuestionnaireLoading(true);
    setQuestionnaireError("");
    try {
      const context = await session.request<QuestionnaireContextResponse>(
        `/api/questionnaire/context?roomId=${encodeURIComponent(experiment.roomId)}`,
      );
      if (context.submitted) {
        setQuestionnaireError("该实验的问卷已提交，无需重复填写。");
        return;
      }
      if (context.url === null) {
        setQuestionnaireError("暂时无法生成问卷链接，请联系实验主试。");
        return;
      }
      window.location.href = context.url;
    } catch (error: unknown) {
      if (isUnauthorized(error)) return;
      setQuestionnaireError(
        formatUnknownError(
          error,
          "无法继续填写问卷，请稍后重试或联系实验主试。",
        ),
      );
    } finally {
      setQuestionnaireLoading(false);
    }
  };

  return (
    <PageFrame narrow>
      <SubpageHeader
        title="实验完成信息"
        description="本次实验的记录与报酬结算信息。"
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
              <StatusChip tone={completionChip.tone}>
                {completionChip.label}
              </StatusChip>
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
                报酬结算
              </h2>
              <span data-testid="payment-status">
                <StatusChip
                  tone={
                    awaitingQuestionnaire
                      ? "warning"
                      : payment === null
                        ? "warning"
                        : payment.status === "paid"
                          ? "success"
                          : "warning"
                  }
                >
                  {awaitingQuestionnaire
                    ? "待问卷完成"
                    : payment === null
                      ? "待处理"
                      : payment.status === "paid"
                        ? "已支付"
                        : "待支付"}
                </StatusChip>
              </span>
            </div>

            {awaitingQuestionnaire ? (
              <>
                <div className="p-banner p-banner-info" role="status">
                  后测问卷尚未填写，当前状态为未完成。填写后测问卷后，这里会显示具体金额与支付时间。
                </div>
                <div className="p-btn-row">
                  <button
                    type="button"
                    className="p-btn p-btn-primary"
                    data-testid="complete-questionnaire"
                    disabled={questionnaireLoading}
                    onClick={() => void openQuestionnaire()}
                  >
                    {questionnaireLoading ? "正在打开问卷…" : "填写后测问卷"}
                  </button>
                </div>
                {questionnaireError !== "" ? (
                  <div className="p-banner p-banner-error" role="alert">
                    {questionnaireError}
                  </div>
                ) : null}
              </>
            ) : (
              <>
                <div className="p-payment-row">
                  <span>基础</span>
                  <span className="p-mono">
                    {payment === null ? "待处理" : formatMoney(payment.basePayCents)}
                  </span>
                </div>
                <div className="p-payment-row">
                  <span>绩效</span>
                  <span className="p-mono">
                    {payment === null
                      ? "待处理"
                      : formatMoney(payment.performancePayCents)}
                  </span>
                </div>
                {payment !== null && payment.showupPayCents > 0 ? (
                  <div className="p-payment-row">
                    <span>到场费</span>
                    <span className="p-mono">
                      {formatMoney(payment.showupPayCents)}
                    </span>
                  </div>
                ) : null}
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
                  {abortedRoom
                    ? "到场费由主试核对后通过支付宝统一转账。如逾期未收到，请通过“联系主试”与实验组织者核对。"
                    : "报酬将在提交后测问卷的当周周日通过支付宝统一完成转账。如逾期未收到，请通过“联系主试”与实验组织者核对。"}
                </p>
                {payment === null ? (
                  <div className="p-banner p-banner-info" role="status">
                    报酬记录尚未生成，当前状态为待处理。主试完成结算后，这里会显示具体金额与支付时间。
                  </div>
                ) : null}
              </>
            )}
          </section>

          <PageLinks items={["home", "history", "contact"]} />
        </>
      )}
    </PageFrame>
  );
}
