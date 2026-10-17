import { ClipboardCheck, Home, Mail, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";

import type { ArchiveReason, QuestionnaireStatus } from "../shared/types";
import { ARCHIVE_COPY, QUESTIONNAIRE_STATUS_LABELS } from "./apiTypes";

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
        <p className="exp-kicker">全部 trial 已完成</p>
        <h1 className="exp-rest-title">实验结束</h1>
        {submitted ? (
          <>
            <p className="exp-rest-info">
              后测问卷已提交，感谢你的参与。你可以查看完成信息与历史实验记录。
            </p>
            <div className="p-btn-row exp-end-actions">
              <Link className="p-btn p-btn-primary" to={`/complete?room=${encodeURIComponent(roomId)}`}>
                <ClipboardCheck size={18} aria-hidden="true" />
                查看完成信息
              </Link>
              <Link className="p-btn p-btn-secondary" to="/history">
                历史实验
              </Link>
            </div>
          </>
        ) : (
          <>
            <p className="exp-rest-info">
              请完成实验后测问卷。问卷会在新的页面中打开，完成后才能确认本次实验记录。
            </p>
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
                填写后测问卷
              </button>
              <Link className="p-btn p-btn-secondary" to="/">
                <Home size={18} aria-hidden="true" />
                返回首页
              </Link>
            </div>
            {url === null ? (
              <div className="p-banner p-banner-warning" role="status">
                暂时无法生成问卷链接。请联系实验主试获取问卷地址。
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
}: {
  roomId: string;
  reason: ArchiveReason | null;
  canRebook: boolean;
}) {
  const copy =
    reason === null
      ? {
          title: "房间已结束",
          detail: "本次实验已结束。你可以返回首页查看当前预约或联系实验主试。",
          showContact: true,
        }
      : ARCHIVE_COPY[reason];

  return (
    <div className="exp-centered exp-archive">
      <div className="exp-end-card">
        <p className="exp-kicker">实验房间已关闭</p>
        <h1 className="exp-rest-title">{copy.title}</h1>
        <p className="exp-rest-info">{copy.detail}</p>
        <div className="p-btn-row exp-end-actions">
          <Link className="p-btn p-btn-primary" to="/">
            <Home size={18} aria-hidden="true" />
            返回首页
          </Link>
          {canRebook ? (
            <Link className="p-btn p-btn-secondary" to="/">
              <RefreshCw size={18} aria-hidden="true" />
              重新预约
            </Link>
          ) : null}
          {reason === "completed" ? (
            <Link
              className="p-btn p-btn-secondary"
              to={`/complete?room=${encodeURIComponent(roomId)}`}
            >
              <ClipboardCheck size={18} aria-hidden="true" />
              查看完成信息
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
