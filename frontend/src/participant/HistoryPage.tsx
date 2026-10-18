import { useEffect, useState } from "react";

import { formatDateTime, formatMoney } from "../shared/format";
import type { ExperimentRecord } from "../shared/types";
import type {
  MyExperimentsResponse,
  QuestionnaireContextResponse,
} from "./apiTypes";
import {
  ROOM_STATUS_LABELS,
  formatUnknownError,
  isUnauthorized,
} from "./apiTypes";
import { LoadingCard, PageLinks, StatusChip, SubpageHeader } from "./common";
import { PageFrame, useSession } from "./session";

function completionState(item: ExperimentRecord): {
  label: string;
  tone: "neutral" | "success" | "warning" | "error";
} {
  if (item.bookingStatus === "no_show" || item.archiveReason === "no_show") {
    return { label: "未到场", tone: "error" };
  }
  if (
    item.questionnaireStatus !== "completed" &&
    (item.roomStatus === "questionnaire" ||
      item.archiveReason === "questionnaire_incomplete")
  ) {
    return { label: "待填写问卷", tone: "warning" };
  }
  if (item.archiveReason === "completed") {
    return { label: "已完成", tone: "success" };
  }
  if (item.archiveReason !== null) {
    return { label: "已中止", tone: "error" };
  }
  return { label: ROOM_STATUS_LABELS[item.roomStatus], tone: "neutral" };
}

function questionnaireLabel(item: ExperimentRecord): string {
  if (item.questionnaireStatus === "completed") return "已完成";
  if (item.questionnaireStatus === "in_progress") return "填写中";
  if (item.questionnaireStatus === "not_started") return "未开始";
  return "—";
}

export default function HistoryPage() {
  const session = useSession();
  const [experiments, setExperiments] = useState<ExperimentRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [continuingRoomId, setContinuingRoomId] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setLoadError("");
    session
      .request<MyExperimentsResponse>("/api/my-experiments")
      .then((response) => {
        if (alive) setExperiments(response.experiments);
      })
      .catch((error: unknown) => {
        if (!alive || isUnauthorized(error)) return;
        setLoadError(formatUnknownError(error, "无法加载历史实验，请稍后重试。"));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [session, reloadToken]);

  const continueQuestionnaire = async (record: ExperimentRecord) => {
    if (continuingRoomId !== null) return;
    setActionError("");
    setContinuingRoomId(record.roomId);
    try {
      const context = await session.request<QuestionnaireContextResponse>(
        `/api/questionnaire/context?roomId=${encodeURIComponent(record.roomId)}`,
      );
      if (context.roomId !== record.roomId) {
        setActionError(
          "当前进行中的问卷与该实验不一致。请返回首页，从当前预约继续填写。",
        );
        return;
      }
      if (context.submitted) {
        setActionError("该实验的问卷已提交，无需重复填写。");
        return;
      }
      if (context.url === null) {
        setActionError("暂时无法生成问卷链接，请联系实验主试。");
        return;
      }
      window.location.href = context.url;
    } catch (error: unknown) {
      if (isUnauthorized(error)) return;
      setActionError(
        formatUnknownError(
          error,
          "无法继续填写问卷。请确认实验仍在问卷阶段，或联系实验主试。",
        ),
      );
    } finally {
      setContinuingRoomId(null);
    }
  };

  return (
    <PageFrame>
      <SubpageHeader
        title="历史实验"
        description="你参与过的实验记录与报酬状态。"
      />

      {actionError !== "" ? (
        <div className="p-banner p-banner-error" role="alert">
          {actionError}
        </div>
      ) : null}

      {loading ? (
        <LoadingCard text="正在加载历史实验…" />
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
      ) : experiments.length === 0 ? (
        <div className="p-card p-empty">还没有实验记录。</div>
      ) : (
        <section className="p-card" aria-labelledby="history-title">
          <h2 className="p-section-title" id="history-title">
            全部记录
          </h2>
          <ul className="p-list history-list" data-testid="history-list">
            {experiments.map((item) => {
              const completion = completionState(item);
              const paymentStatus =
                item.payment === null
                  ? "待处理"
                  : item.payment.status === "paid"
                    ? "已支付"
                    : "待支付";
              const awaitingQuestionnaire =
                item.questionnaireStatus !== "completed" &&
                (item.roomStatus === "questionnaire" ||
                  item.archiveReason === "questionnaire_incomplete");
              const canContinueQuestionnaire = awaitingQuestionnaire;
              return (
                <li key={item.roomId} className="history-item">
                  <div className="history-item-head">
                    <div>
                      <p className="history-item-time">
                        {formatDateTime(item.startsAt)}
                      </p>
                      <p className="p-muted">
                        {item.role === 1
                          ? "圆形玩家"
                          : item.role === 2
                            ? "菱形玩家"
                            : "角色未分配"}
                      </p>
                    </div>
                    <StatusChip tone={completion.tone}>
                      {completion.label}
                    </StatusChip>
                  </div>
                  <dl className="p-detail-list history-details">
                    <div className="p-detail-row">
                      <dt>完成情况</dt>
                      <dd>{completion.label}</dd>
                    </div>
                    <div className="p-detail-row">
                      <dt>后测问卷</dt>
                      <dd>{questionnaireLabel(item)}</dd>
                    </div>
                    <div className="p-detail-row">
                      <dt>报酬</dt>
                      <dd className="p-mono">
                        {awaitingQuestionnaire
                          ? "待问卷完成"
                          : item.payment === null
                            ? "待处理"
                            : formatMoney(item.payment.totalCents)}
                      </dd>
                    </div>
                    <div className="p-detail-row">
                      <dt>支付状态</dt>
                      <dd data-testid="payment-status">
                        <StatusChip
                          tone={
                            awaitingQuestionnaire
                              ? "warning"
                              : item.payment?.status === "paid"
                                ? "success"
                                : "warning"
                          }
                        >
                          {awaitingQuestionnaire ? "待问卷完成" : paymentStatus}
                        </StatusChip>
                      </dd>
                    </div>
                  </dl>
                  {canContinueQuestionnaire ? (
                    <div className="p-btn-row history-actions">
                      <button
                        type="button"
                        className="p-btn p-btn-secondary"
                        disabled={continuingRoomId !== null}
                        onClick={() => void continueQuestionnaire(item)}
                      >
                        {continuingRoomId === item.roomId
                          ? "正在打开问卷…"
                          : "继续填写问卷"}
                      </button>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <PageLinks items={["home", "contact"]} />
    </PageFrame>
  );
}
