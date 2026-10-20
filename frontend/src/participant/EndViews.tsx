import { ClipboardCheck, Home, Mail, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";

import type {
  ArchiveReason,
  QuestionnaireStatus,
  RewardKind,
} from "../shared/types";
import { QUESTIONNAIRE_STATUS_LABELS } from "./apiTypes";
import { ContinueQuestionnaireButton } from "./ContinueQuestionnaireButton";
import {
  CONTINUE_QUESTIONNAIRE,
  QUESTIONNAIRE_BUTTON,
  QUESTIONNAIRE_LINK_FAILED,
  QUESTIONNAIRE_REQUIRED,
  QUESTIONNAIRE_SUBMITTED,
  REBOOK,
  VIEW_REWARD_INFO,
  archiveCopyFor,
} from "./flowCopy";

export interface QuestionnaireViewInfo {
  url: string | null;
  status: QuestionnaireStatus;
  submitted: boolean;
}

export function QuestionnaireView({
  roomId,
  info,
}: {
  roomId: string;
  info: QuestionnaireViewInfo | null;
}) {
  const submitted = info?.submitted === true;
  const url = info?.url ?? null;

  return (
    <div className="exp-centered exp-questionnaire">
      <div className="exp-end-card">
        <p className="exp-kicker">全部对局已完成</p>
        <h1 className="exp-rest-title">
          {submitted ? "问卷已提交" : "请填写后测问卷"}
        </h1>
        {submitted ? (
          <>
            <p className="exp-rest-info">{QUESTIONNAIRE_SUBMITTED}</p>
            <div className="p-btn-row exp-end-actions exp-end-actions-stacked">
              <Link
                className="p-btn p-btn-primary"
                data-testid="reward-info"
                to={`/complete?room=${encodeURIComponent(roomId)}`}
              >
                <ClipboardCheck size={18} aria-hidden="true" />
                {VIEW_REWARD_INFO}
              </Link>
              <div className="exp-end-actions-secondary">
                <Link className="p-btn p-btn-secondary" to="/history">
                  历史实验
                </Link>
                <Link className="p-btn p-btn-secondary" to="/">
                  <Home size={18} aria-hidden="true" />
                  返回首页
                </Link>
              </div>
            </div>
          </>
        ) : (
          <>
            <p className="exp-rest-info">{QUESTIONNAIRE_REQUIRED}</p>
            {info !== null ? (
              <p className="p-muted">
                问卷状态：{QUESTIONNAIRE_STATUS_LABELS[info.status]}
              </p>
            ) : null}
            <div className="p-btn-row exp-end-actions">
              <button
                type="button"
                className="p-btn p-btn-primary"
                data-testid="questionnaire-button"
                disabled={url === null}
                onClick={() => {
                  if (url !== null) window.location.href = url;
                }}
              >
                {QUESTIONNAIRE_BUTTON}
              </button>
              <Link
                className="p-btn p-btn-secondary"
                data-testid="reward-info"
                to={`/complete?room=${encodeURIComponent(roomId)}`}
              >
                <ClipboardCheck size={18} aria-hidden="true" />
                {VIEW_REWARD_INFO}
              </Link>
              <Link className="p-btn p-btn-secondary" to="/">
                <Home size={18} aria-hidden="true" />
                返回首页
              </Link>
            </div>
            {url === null ? (
              <div className="p-banner p-banner-warning" role="status">
                {QUESTIONNAIRE_LINK_FAILED}
                <div className="exp-end-links">
                  <Link to="/contact">
                    <Mail size={14} aria-hidden="true" />
                    联系主试
                  </Link>
                </div>
              </div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}

export function ArchiveView({
  roomId,
  reason,
  canRebook,
  selfExited,
  questionnaireCompleted,
  rewardKind,
}: {
  roomId: string;
  reason: ArchiveReason | null;
  canRebook: boolean;
  selfExited: boolean;
  questionnaireCompleted: boolean;
  rewardKind: RewardKind;
}) {
  const copy = archiveCopyFor(reason, {
    selfExited,
    questionnaireCompleted,
    hasShowupPay: rewardKind === "showup",
    canRebook,
  });
  const needsQuestionnaire =
    reason === "questionnaire_incomplete" && !questionnaireCompleted;
  const rebookAllowed =
    canRebook &&
    reason !== "completed" &&
    reason !== "questionnaire_incomplete";

  return (
    <div className="exp-centered exp-archive">
      <div className="exp-end-card">
        <p className="exp-kicker">实验房间已关闭</p>
        <h1 className="exp-rest-title">{copy.title}</h1>
        <p className="exp-rest-info">{copy.detail}</p>
        <div className="p-btn-row exp-end-actions">
          {needsQuestionnaire ? (
            <ContinueQuestionnaireButton
              roomId={roomId}
              className="p-btn p-btn-primary"
              label={CONTINUE_QUESTIONNAIRE}
            />
          ) : null}
          <Link
            className={
              needsQuestionnaire
                ? "p-btn p-btn-secondary"
                : "p-btn p-btn-primary"
            }
            data-testid="reward-info"
            to={`/complete?room=${encodeURIComponent(roomId)}`}
          >
            <ClipboardCheck size={18} aria-hidden="true" />
            {VIEW_REWARD_INFO}
          </Link>
          <Link className="p-btn p-btn-secondary" to="/">
            <Home size={18} aria-hidden="true" />
            返回首页
          </Link>
          {rebookAllowed ? (
            <Link
              className="p-btn p-btn-secondary"
              data-testid="rebook"
              to="/"
            >
              <RefreshCw size={18} aria-hidden="true" />
              {REBOOK}
            </Link>
          ) : null}
          {copy.showContact ? (
            <Link className="p-btn p-btn-secondary" to="/contact">
              <Mail size={18} aria-hidden="true" />
              联系主试
            </Link>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function NoRoomView() {
  return (
    <div className="exp-centered">
      <div className="exp-end-card">
        <p className="exp-kicker">无法进入实验</p>
        <h1 className="exp-rest-title">当前没有可进入的房间</h1>
        <p className="exp-rest-info">
          本次预约可能已结束或已被取消。你可以返回首页查看预约状态并重新选择场次。
        </p>
        <div className="p-btn-row exp-end-actions">
          <Link className="p-btn p-btn-primary" to="/">
            <Home size={18} aria-hidden="true" />
            返回首页
          </Link>
          <Link className="p-btn p-btn-secondary" to="/contact">
            <Mail size={18} aria-hidden="true" />
            联系主试
          </Link>
        </div>
      </div>
    </div>
  );
}
