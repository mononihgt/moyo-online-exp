import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { formatDateTime, formatMoney } from "../shared/format";
import type { ExperimentRecord } from "../shared/types";
import type { MyExperimentsResponse } from "./apiTypes";
import {
  ROOM_STATUS_LABELS,
  formatUnknownError,
  isUnauthorized,
} from "./apiTypes";
import { LoadingCard, PageLinks, StatusChip, SubpageHeader } from "./common";
import { ContinueQuestionnaireButton } from "./ContinueQuestionnaireButton";
import {
  ARCHIVE_REASON_LABELS,
  HISTORY_ARCHIVED_SUBMITTED_NOTE,
  HISTORY_QUESTIONNAIRE_LOCK_NOTE,
  HISTORY_TECH_NOTE,
  HISTORY_VIEW_REWARD,
  NO_REWARD,
  REBOOK,
} from "./flowCopy";
import { PageFrame, useSession } from "./session";

type ChipTone = "neutral" | "success" | "warning" | "error";

interface HistoryEntryState {
  label: string;
  tone: ChipTone;
  formal: string;
  awaitingQuestionnaire: boolean;
  completion: boolean;
  techShowup: boolean;
}

function entryState(item: ExperimentRecord): HistoryEntryState {
  const completion = item.questionnaireStatus === "completed";
  const awaitingQuestionnaire =
    !completion &&
    (item.roomStatus === "questionnaire" ||
      item.archiveReason === "questionnaire_incomplete");
  if (awaitingQuestionnaire) {
    return {
      label: "待填写问卷",
      tone: "warning",
      formal: "正式实验已完成",
      awaitingQuestionnaire: true,
      completion: false,
      techShowup: false,
    };
  }
  if (completion) {
    return {
      label: "已完成",
      tone: "success",
      formal: "已完成",
      awaitingQuestionnaire: false,
      completion: true,
      techShowup: false,
    };
  }
  if (item.bookingStatus === "no_show") {
    return {
      label: "未到场",
      tone: "error",
      formal: "未完成",
      awaitingQuestionnaire: false,
      completion: false,
      techShowup: false,
    };
  }
  const techShowup =
    item.rewardKind === "showup" ||
    (item.archiveReason === "technical_abort" &&
      item.selfAttended &&
      (item.payment?.showupPayCents ?? 0) > 0);
  const base = {
    formal: "未完成",
    awaitingQuestionnaire: false,
    completion: false,
    techShowup,
  };
  switch (item.archiveReason) {
    case "technical_abort":
      return { ...base, label: "技术中止", tone: "warning" };
    case "abandoned":
      return item.selfExited
        ? { ...base, label: "已退出", tone: "neutral" }
        : { ...base, label: "已中止", tone: "error" };
    case "admin_cancelled":
      return { ...base, label: "已取消", tone: "neutral" };
    case "admin_aborted":
      return { ...base, label: "已中止", tone: "error" };
    case "not_full":
    case "no_show":
    case "no_start":
      return { ...base, label: "实验未开始", tone: "neutral" };
    case "completed":
      return { ...base, label: "已完成", tone: "success", formal: "已完成", completion: true };
    case "questionnaire_incomplete":
      return item.selfExited
        ? { ...base, label: "已退出", tone: "neutral" }
        : { ...base, label: "已中止", tone: "error" };
    default:
      break;
  }
  if (item.roomStatus === "archived") {
    return { ...base, label: "已中止", tone: "error" };
  }
  return {
    ...base,
    label: ROOM_STATUS_LABELS[item.roomStatus],
    tone: "neutral",
  };
}

function questionnaireLabel(item: ExperimentRecord): string {
  if (item.questionnaireStatus === "completed") return "已完成";
  if (item.questionnaireStatus === null) return "—";
  return "未提交";
}

export default function HistoryPage() {
  const session = useSession();
  const [experiments, setExperiments] = useState<ExperimentRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
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

  return (
    <PageFrame>
      <SubpageHeader
        title="历史实验"
        description="你参与过的实验记录与报酬状态。"
      />

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
            {experiments.map((item, index) => {
              const state = entryState(item);
              const archivedQuestionnaire =
                item.archiveReason === "questionnaire_incomplete";
              const showReward = state.completion || state.techShowup;
              const rebookAllowed =
                item.canRebook &&
                item.archiveReason !== "completed" &&
                item.archiveReason !== "questionnaire_incomplete";
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
                    <StatusChip tone={state.tone}>{state.label}</StatusChip>
                  </div>
                  <dl className="p-detail-list history-details">
                    <div className="p-detail-row">
                      <dt>完成情况</dt>
                      <dd>{state.formal}</dd>
                    </div>
                    <div className="p-detail-row">
                      <dt>后测问卷</dt>
                      <dd>{questionnaireLabel(item)}</dd>
                    </div>
                    <div className="p-detail-row">
                      <dt>报酬</dt>
                      <dd className="p-mono">
                        {state.completion
                          ? formatMoney(item.payment?.totalCents)
                          : state.techShowup
                            ? `到场费：${formatMoney(item.payment?.showupPayCents)}`
                            : NO_REWARD}
                      </dd>
                    </div>
                    {showReward && item.payment !== null ? (
                      <>
                        <div className="p-detail-row">
                          <dt>支付状态</dt>
                          <dd
                            data-testid={
                              index === 0
                                ? "payment-status"
                                : `payment-status-${item.roomId}`
                            }
                          >
                            <StatusChip
                              tone={
                                item.payment.status === "paid"
                                  ? "success"
                                  : "warning"
                              }
                            >
                              {item.payment.status === "paid"
                                ? "已支付"
                                : "待支付"}
                            </StatusChip>
                          </dd>
                        </div>
                        <div className="p-detail-row">
                          <dt>支付截止日期</dt>
                          <dd>{formatDateTime(item.payment.deadlineAt)}</dd>
                        </div>
                      </>
                    ) : null}
                    {item.archiveReason !== null ? (
                      <div className="p-detail-row">
                        <dt>房间归档原因</dt>
                        <dd>{ARCHIVE_REASON_LABELS[item.archiveReason]}</dd>
                      </div>
                    ) : null}
                  </dl>
                  {state.techShowup ? (
                    <p className="p-muted history-note">{HISTORY_TECH_NOTE}</p>
                  ) : null}
                  {archivedQuestionnaire && state.completion ? (
                    <p className="p-muted history-note">
                      {HISTORY_ARCHIVED_SUBMITTED_NOTE}
                    </p>
                  ) : null}
                  {archivedQuestionnaire && state.awaitingQuestionnaire ? (
                    <p className="p-muted history-note">
                      {HISTORY_QUESTIONNAIRE_LOCK_NOTE}
                    </p>
                  ) : null}
                  <div className="p-btn-row history-actions">
                    <Link
                      className="p-btn p-btn-secondary"
                      data-testid={
                        index === 0
                          ? "reward-info"
                          : `reward-info-${item.roomId}`
                      }
                      to={`/complete?room=${encodeURIComponent(item.roomId)}`}
                    >
                      {HISTORY_VIEW_REWARD}
                    </Link>
                    {state.awaitingQuestionnaire ? (
                      <ContinueQuestionnaireButton
                        roomId={item.roomId}
                        className="p-btn p-btn-secondary"
                        testId={
                          index === 0
                            ? "continue-questionnaire"
                            : `continue-questionnaire-${item.roomId}`
                        }
                      />
                    ) : null}
                    {rebookAllowed ? (
                      <Link
                        className="p-btn p-btn-secondary"
                        data-testid={
                          index === 0 ? "rebook" : `rebook-${item.roomId}`
                        }
                        to="/"
                      >
                        {REBOOK}
                      </Link>
                    ) : null}
                  </div>
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
