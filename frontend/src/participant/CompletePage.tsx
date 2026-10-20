import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { formatDateTime, formatMoney } from "../shared/format";
import type { ExperimentRecord, Payment } from "../shared/types";
import type {
  MyExperimentsResponse,
  MyPaymentsResponse,
} from "./apiTypes";
import { formatUnknownError, isUnauthorized } from "./apiTypes";
import { LoadingCard, PageLinks, StatusChip, SubpageHeader } from "./common";
import { ContinueQuestionnaireButton } from "./ContinueQuestionnaireButton";
import {
  ARCHIVE_REASON_LABELS,
  COMPLETE_ARCHIVED_SUBMITTED_NOTE,
  COMPLETE_PAGE_DESCRIPTION,
  COMPLETE_PAGE_TITLE,
  COMPLETE_PENDING_ARCHIVED_DETAIL,
  COMPLETE_PENDING_DETAIL,
  COMPLETE_QUESTIONNAIRE_ARCHIVE_NOTE,
  COMPLETE_TECH_SHOWUP_NOTE,
  COMPLETE_TECH_SHOWUP_PENDING_NOTE,
  COMPLETE_TECH_ZERO_NOTE,
  COMPLETE_TRANSFER_NOTE,
  NO_REWARD,
  REBOOK,
  archiveCopyFor,
} from "./flowCopy";
import { PageFrame, useSession } from "./session";

type ChipTone = "neutral" | "success" | "warning" | "error";

function stateLabel(experiment: ExperimentRecord | null, awaiting: boolean, completed: boolean): {
  label: string;
  tone: ChipTone;
} {
  if (awaiting) return { label: "待填写问卷", tone: "warning" };
  const reason = experiment?.archiveReason ?? null;
  if (reason === "technical_abort") {
    return { label: "提前结束", tone: "warning" };
  }
  if (completed) return { label: "已完成", tone: "success" };
  switch (reason) {
    case "abandoned":
      if (experiment?.selfExited === true) {
        return experiment.selfExitReason === "inactivity"
          ? { label: "自动结束", tone: "neutral" }
          : { label: "已退出", tone: "neutral" };
      }
      return { label: "已结束", tone: "error" };
    case "admin_cancelled":
      return { label: "已取消", tone: "neutral" };
    case "admin_aborted":
      return { label: "已结束", tone: "error" };
    case "not_full":
    case "no_show":
    case "no_start":
      return { label: "未开始", tone: "neutral" };
    default:
      break;
  }
  if (experiment?.roomStatus === "archived") {
    return { label: "已结束", tone: "error" };
  }
  if (experiment?.roomStatus === "questionnaire") {
    return { label: "待填写问卷", tone: "warning" };
  }
  return { label: "实验进行中", tone: "neutral" };
}

function questionnaireLabel(
  status: ExperimentRecord["questionnaireStatus"] | undefined,
): string {
  if (status === "completed") return "已完成";
  if (status === "in_progress") return "填写中";
  return "未提交";
}

function rewardStatusLabel(payment: Payment): string {
  return payment.status === "paid" ? "已支付" : "待支付";
}

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
        setLoadError(formatUnknownError(error, "无法加载报酬信息，请稍后重试。"));
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
  const archiveReason = experiment?.archiveReason ?? null;
  const technicalAbort = archiveReason === "technical_abort";
  const questionnaireCompleted =
    experiment?.questionnaireStatus === "completed";
  const awaitingQuestionnaire =
    experiment !== null &&
    !questionnaireCompleted &&
    (experiment.roomStatus === "questionnaire" ||
      experiment.archiveReason === "questionnaire_incomplete");
  const hasCompletion = questionnaireCompleted && !technicalAbort;
  const needsTechnicalQuestionnaire =
    technicalAbort &&
    experiment?.selfAttended === true &&
    (experiment?.showupPayCents ?? 0) > 0 &&
    !questionnaireCompleted;
  const hasShowup =
    technicalAbort &&
    (payment?.showupPayCents ?? 0) > 0;
  const hasManual =
    payment !== null && (payment.source ?? "computed") !== "computed";
  const hasReward = hasCompletion || hasShowup || hasManual;
  const state = stateLabel(experiment, awaitingQuestionnaire, hasCompletion);
  const archivedQuestionnaire = archiveReason === "questionnaire_incomplete";
  const canRebook = experiment?.canRebook === true;
  const formalCompleted =
    hasCompletion ||
    (!technicalAbort &&
      (awaitingQuestionnaire || experiment?.roomStatus === "questionnaire"));

  let noRewardDetail = "";
  if (experiment !== null) {
    if (archiveReason === "technical_abort") {
      noRewardDetail = COMPLETE_TECH_ZERO_NOTE;
    } else if (archiveReason !== null) {
      noRewardDetail = archiveCopyFor(archiveReason, {
        selfExited: experiment.selfExited,
        selfExitReason: experiment.selfExitReason,
        partnerExitReason: null,
        questionnaireCompleted,
        questionnaireRequired: false,
        hasShowupPay: false,
        canRebook,
      }).detail;
    } else {
      noRewardDetail = "本次实验尚未结束，报酬将在实验结束后结算。";
    }
  }

  return (
    <PageFrame narrow>
      <SubpageHeader
        title={COMPLETE_PAGE_TITLE}
        description={COMPLETE_PAGE_DESCRIPTION}
      />

      {loading ? (
        <LoadingCard text="正在加载报酬信息…" />
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
          <section
            className="p-card"
            data-testid="reward-info"
            aria-labelledby="complete-summary-title"
          >
            <div className="p-row">
              <h2 className="p-section-title" id="complete-summary-title">
                实验记录
              </h2>
              <StatusChip tone={state.tone}>{state.label}</StatusChip>
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
                <dt>正式实验</dt>
                <dd>{formalCompleted ? "已完成" : "未完成"}</dd>
              </div>
              <div className="p-detail-row">
                <dt>后测问卷</dt>
                <dd>{questionnaireLabel(experiment?.questionnaireStatus)}</dd>
              </div>
              {archiveReason !== null ? (
                <div className="p-detail-row">
                  <dt>实验结束原因</dt>
                  <dd>{ARCHIVE_REASON_LABELS[archiveReason]}</dd>
                </div>
              ) : null}
            </dl>
          </section>

          <section className="p-card" aria-labelledby="complete-pay-title">
            <div className="p-row">
              <h2 className="p-section-title" id="complete-pay-title">
                报酬结算
              </h2>
              {hasReward && payment !== null ? (
                <span data-testid="payment-status">
                  <StatusChip tone={payment.status === "paid" ? "success" : "warning"}>
                    {rewardStatusLabel(payment)}
                  </StatusChip>
                </span>
              ) : null}
            </div>

            {hasManual && payment !== null ? (
              <>
                {payment.showupPayCents > 0 ? (
                  <div className="p-payment-row">
                    <span>到场费</span>
                    <span className="p-mono">
                      {formatMoney(payment.showupPayCents)}
                    </span>
                  </div>
                ) : null}
                {payment.basePayCents > 0 ? (
                  <div className="p-payment-row">
                    <span>完成报酬补偿</span>
                    <span className="p-mono">
                      {formatMoney(payment.basePayCents)}
                    </span>
                  </div>
                ) : null}
                {payment.performancePayCents > 0 ? (
                  <div className="p-payment-row">
                    <span>绩效费</span>
                    <span className="p-mono">
                      {formatMoney(payment.performancePayCents)}
                    </span>
                  </div>
                ) : null}
                {payment.showupPayCents === 0 &&
                payment.basePayCents === 0 &&
                payment.performancePayCents === 0 ? (
                  <div className="p-payment-row">
                    <span>补偿金额</span>
                    <span className="p-mono">
                      {formatMoney(payment.totalCents)}
                    </span>
                  </div>
                ) : null}
                <div className="p-payment-row p-payment-total">
                  <span>合计</span>
                  <span className="p-mono" data-testid="complete-total">
                    {formatMoney(payment.totalCents)}
                  </span>
                </div>
                <dl className="p-detail-list p-payment-details">
                  <div className="p-detail-row">
                    <dt>支付截止日期</dt>
                    <dd>{formatDateTime(payment.deadlineAt)}</dd>
                  </div>
                  {payment.status === "paid" && payment.paidAt ? (
                    <div className="p-detail-row">
                      <dt>支付时间</dt>
                      <dd>{formatDateTime(payment.paidAt)}</dd>
                    </div>
                  ) : null}
                </dl>
                <p className="p-muted">
                  本场补偿由实验工作人员发放，支付状态和截止日期以上方为准。
                </p>
                {awaitingQuestionnaire || needsTechnicalQuestionnaire ? (
                  <div className="p-btn-row">
                    <ContinueQuestionnaireButton roomId={roomId} />
                  </div>
                ) : null}
              </>
            ) : awaitingQuestionnaire ? (
              <>
                <div className="p-banner p-banner-warning" role="status">
                  {NO_REWARD}
                </div>
                <p className="p-muted">
                  {archivedQuestionnaire
                    ? COMPLETE_PENDING_ARCHIVED_DETAIL
                    : COMPLETE_PENDING_DETAIL}
                </p>
                {archivedQuestionnaire ? (
                  <p className="p-detail-row p-archive-reason-line">
                    {COMPLETE_QUESTIONNAIRE_ARCHIVE_NOTE}
                  </p>
                ) : null}
                <div className="p-btn-row">
                  <ContinueQuestionnaireButton roomId={roomId} />
                </div>
              </>
            ) : technicalAbort ? (
              <>
                {hasShowup ? (
                  <>
                    <div className="p-payment-row">
                      <span>到场费</span>
                      <span className="p-mono">
                        {formatMoney(payment?.showupPayCents ?? 0)}
                      </span>
                    </div>
                    <div className="p-payment-row p-payment-total">
                      <span>合计</span>
                      <span className="p-mono" data-testid="complete-total">
                        {formatMoney(payment?.totalCents ?? 0)}
                      </span>
                    </div>
                    {payment !== null ? (
                      <dl className="p-detail-list p-payment-details">
                        <div className="p-detail-row">
                          <dt>支付截止日期</dt>
                          <dd>{formatDateTime(payment.deadlineAt)}</dd>
                        </div>
                        {payment.status === "paid" && payment.paidAt ? (
                          <div className="p-detail-row">
                            <dt>支付时间</dt>
                            <dd>{formatDateTime(payment.paidAt)}</dd>
                          </div>
                        ) : null}
                      </dl>
                    ) : null}
                    <p className="p-muted">{COMPLETE_TECH_SHOWUP_NOTE}</p>
                  </>
                ) : needsTechnicalQuestionnaire ? (
                  <>
                    <div className="p-banner p-banner-warning" role="status">
                      {COMPLETE_TECH_SHOWUP_PENDING_NOTE}
                    </div>
                    <div className="p-btn-row">
                      <ContinueQuestionnaireButton roomId={roomId} />
                    </div>
                  </>
                ) : questionnaireCompleted ? (
                  <div className="p-banner p-banner-warning" role="status">
                    报酬记录尚未同步。请联系实验工作人员核对。
                  </div>
                ) : (
                  <>
                    <div className="p-banner p-banner-warning" role="status">
                      {NO_REWARD}
                    </div>
                    <p className="p-muted">{COMPLETE_TECH_ZERO_NOTE}</p>
                  </>
                )}
              </>
            ) : hasCompletion ? (
              <>
                {payment !== null ? (
                  <>
                    <div className="p-payment-row">
                      <span>基础费</span>
                      <span className="p-mono">{formatMoney(payment.basePayCents)}</span>
                    </div>
                    <div className="p-payment-row">
                      <span>绩效费</span>
                      <span className="p-mono">
                        {formatMoney(payment.performancePayCents)}
                      </span>
                    </div>
                    <div className="p-payment-row p-payment-total">
                      <span>合计</span>
                      <span className="p-mono" data-testid="complete-total">
                        {formatMoney(payment.totalCents)}
                      </span>
                    </div>
                    <dl className="p-detail-list p-payment-details">
                      <div className="p-detail-row">
                        <dt>支付截止日期</dt>
                        <dd>{formatDateTime(payment.deadlineAt)}</dd>
                      </div>
                      {payment.status === "paid" && payment.paidAt ? (
                        <div className="p-detail-row">
                          <dt>支付时间</dt>
                          <dd>{formatDateTime(payment.paidAt)}</dd>
                        </div>
                      ) : null}
                    </dl>
                  </>
                ) : (
                  <div className="p-banner p-banner-warning" role="status">
                    报酬记录尚未同步。请联系实验工作人员核对。
                  </div>
                )}
                <p className="p-muted">
                  {archivedQuestionnaire
                    ? COMPLETE_ARCHIVED_SUBMITTED_NOTE
                    : COMPLETE_TRANSFER_NOTE}
                </p>
              </>
            ) : (
              <>
                <div className="p-banner p-banner-warning" role="status">
                  {NO_REWARD}
                </div>
                {noRewardDetail !== "" ? (
                  <p className="p-muted">{noRewardDetail}</p>
                ) : null}
              </>
            )}

            {!awaitingQuestionnaire && canRebook ? (
              <div className="p-btn-row">
                <Link
                  className="p-btn p-btn-primary"
                  data-testid="rebook"
                  to="/"
                >
                  {REBOOK}
                </Link>
              </div>
            ) : null}
          </section>

          <PageLinks items={["home", "history", "contact"]} />
        </>
      )}
    </PageFrame>
  );
}
