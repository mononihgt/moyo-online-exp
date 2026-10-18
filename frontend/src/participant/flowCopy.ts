import type { ArchiveReason } from "../shared/types";

export const BOOKING_SUCCESS = "预约成功。请在开始时间前进入等待。";
export const CANCEL_SUCCESS = "已取消预约。你可以重新选择场次。";

export const PENDING_QUESTIONNAIRE_TITLE = "待完成问卷";
export const PENDING_QUESTIONNAIRE_DETAIL =
  "你已完成本次正式实验，但后测问卷尚未提交。本次实验尚未完成，继续填写问卷是获得报酬的唯一方式。完成问卷前，你无法预约新的实验。";
export const PENDING_QUESTIONNAIRE_ARCHIVED_DETAIL =
  "本次实验已归档。你已完成本次正式实验，但后测问卷尚未提交。本次实验未完成，不产生报酬；继续填写问卷是获得报酬的唯一方式。完成问卷前，你无法预约新的实验。";
export const CONTINUE_QUESTIONNAIRE = "继续填写问卷";
export const BOOKABLE_HIDDEN_NOTE =
  "可预约场次已隐藏：完成并提交后测问卷前，你不能预约新的实验。";
export const SELF_SUBMITTED_TITLE = "实验已完成";
export const SELF_SUBMITTED_DETAIL =
  "你已提交后测问卷，本次实验已完成，无法再预约新的场次。房间将在双方问卷均完成后归档。你可以查看报酬信息。";
export const AFTER_START_BOOKING_NOTE =
  "开始时间到达后不能取消预约，也不能改报其他场次；如未进入实验，等待时间结束后将按归档规则处理。";
export const ACCOUNT_COMPLETED = "你已完成全部实验，无法再预约新的场次。";
export const ACCOUNT_DISABLED =
  "你的账号当前已停用，无法预约新的场次。如有疑问，请联系实验主试。";
export const ACCOUNT_PENDING_QUESTIONNAIRE =
  "你已完成正式实验但尚未提交后测问卷。完成问卷后才能结束本次实验；不能预约新的场次。";
export const VIEW_REWARD_INFO = "查看报酬信息";
export const REBOOK = "重新预约";
export const CONTACT_EXPERIMENTER = "联系主试";

export const WAIT_SINGLE_DETAIL =
  "只有你一人报名。本次实验需要两名参与者。等待时间结束后若仍未达到两名参与者，本次实验将结束，本次实验未完成，不产生报酬。你可以继续等待，或点击下方“退出本次实验”返回首页并重新预约其他时间。实验开始后无法取消预约。";
export const WAIT_PARTNER_NOT_ENTERED_DETAIL =
  "另一名参与者尚未进入实验。本次实验需要两名参与者。等待时间结束后若仍未到齐，本次实验将结束，本次实验未完成，不产生报酬。你可以继续等待，或点击下方“退出本次实验”返回首页并重新预约其他时间。实验开始后无法取消预约。";
export const WAIT_BOTH_ENTERED_DETAIL =
  "双方均已到场后不能退出；如果等待时间结束时仍未开始，本次实验将自动结束，不产生报酬。";
export const WAIT_SELF_CLICKED = "你已点击开始匹配，等待另一名参与者点击。";
export const WAIT_PARTNER_CLICKED = "另一名参与者已点击开始匹配，请点击开始匹配。";
export const WAIT_BOTH_CLICKED = "双方均已点击开始匹配，正在进入实验…";
export const WAIT_PARTNER_OFFLINE_DETAIL =
  "另一名参与者已进入但当前离线，请等待其重新连接。双方均已到场后不能退出；如果等待时间结束时仍未开始，本次实验将自动结束，不产生报酬。";
export const WAIT_ERROR_PARTNER_MISSING = "另一名参与者尚未进入实验。";
export const WAIT_ERROR_PARTNER_ABSENT = "另一名参与者当前不在线，请等待其重新连接。";
export const WAIT_EXIT_SINGLE = "退出本次实验";
export const WAIT_EXIT_PARTNER = "另一名被试可能放鸽子了，我退出本次实验";
export const WAIT_EXIT_TITLE = "确认退出本次实验？";
export const WAIT_EXIT_DETAIL =
  "退出后本次实验将结束，本次实验未完成，不产生报酬。你可以返回首页重新预约其他时间段。";
export const WAIT_EXIT_CONTINUE = "继续等待";
export const WAIT_EXIT_CONFIRM = "确认退出";

export const EXIT_BUTTON = "退出实验";
export const EXIT_TITLE = "确认退出实验？";
export const EXIT_DETAIL =
  "退出后本次实验未完成，无实验报酬，另一名参与者也会结束实验。";
export const EXIT_CONTINUE = "继续实验";
export const EXIT_CONFIRM = "确认退出";
export const SELF_EXIT_NOTICE =
  "你已主动退出本次实验，本次实验未完成，无实验报酬。你可以重新预约。";

export const INSTRUCTION_PARTNER_OFFLINE =
  "另一名参与者离线，正在等待重连。重连时间结束后，本次实验将中止。";
export const INSTRUCTION_SELF_DISCONNECTED =
  "连接中断，阅读计时已暂停；请在重连时间内恢复连接。重连时间结束后，本次实验将中止。";
export const TURN_SELF_DISCONNECTED =
  "连接中断，正在重新连接。请保持页面打开。重连时间结束后本次实验将中止。";
export const REST_SELF_DISCONNECTED =
  "连接中断，正在重新连接。倒计时已暂停。重连时间结束后本次实验将中止。";
export const PARTNER_OFFLINE_RECONNECTING =
  "另一名参与者离线，正在等待重连。重连时间结束后，本次实验将中止。";
export const RECONNECTING_NOTICE = "连接中断，正在重新连接。请保持页面打开。";

export const QUESTIONNAIRE_REQUIRED =
  "请完成实验后测问卷。完成实验并提交问卷后，才会计算实验报酬";
export const QUESTIONNAIRE_LOCK_NOTE =
  "未提交后测问卷前，你无法预约新的实验；继续填写问卷是获得报酬的唯一方式。";
export const QUESTIONNAIRE_HOME_NOTE =
  "返回首页不会结束实验，你可以稍后继续填写；未提交问卷无法获得报酬。";
export const QUESTIONNAIRE_SUBMITTED =
  "后测问卷已提交，感谢你的参与。你可以查看报酬信息与历史实验记录。";
export const QUESTIONNAIRE_BUTTON = "填写后测问卷";
export const QUESTIONNAIRE_LINK_FAILED =
  "暂时无法生成问卷链接。请联系实验主试获取问卷地址。";
export const QUESTIONNAIRE_DUPLICATE =
  "该实验的问卷已提交，无需重复填写。";

export const COMPLETE_PAGE_TITLE = "报酬信息";
export const COMPLETE_PAGE_DESCRIPTION =
  "本次实验的记录与报酬结算信息。";
export const NO_REWARD = "本次实验未完成，不产生报酬";
export const COMPLETE_PENDING_DETAIL =
  "你已完成本次正式实验，但后测问卷尚未提交。继续填写问卷是获得报酬的唯一方式；提交后将按完成实验结算基础费与绩效费。完成问卷前，你无法预约新的实验。";
export const COMPLETE_PENDING_ARCHIVED_DETAIL =
  "你已完成本次正式实验，但后测问卷尚未提交，本次实验未完成，不产生报酬。房间已归档，你仍可以继续填写并提交问卷；提交后将按完成实验结算基础费与绩效费。完成问卷前，你无法预约新的实验。";
export const COMPLETE_TRANSFER_NOTE =
  "报酬将在提交后测问卷所在周的周日 24:00 前通过支付宝完成转账。如逾期未收到，请通过“联系主试”与实验组织者核对。";
export const COMPLETE_ARCHIVED_SUBMITTED_NOTE =
  "你已提交后测问卷，归档不影响你的完成状态与报酬。";
export const COMPLETE_TECH_SHOWUP_NOTE =
  "本次实验未完成，不产生基础费与绩效费。到场费将在中止日期所在周的周日 24:00 前通过支付宝完成转账。";
export const COMPLETE_TECH_ZERO_NOTE =
  "因断线重连超时或系统故障，本次实验未完成，不产生报酬。本次也没有到场费，且无法计算基础费与绩效费。你可以重新预约其他时间段参与实验。";
export const COMPLETE_REBOOK_NOTE = "你可以重新预约其他时间段参与实验。";
export const COMPLETE_QUESTIONNAIRE_ARCHIVE_NOTE =
  "房间归档原因：问卷未完成。房间归档后仍可继续填写并提交问卷。";
export const HISTORY_QUESTIONNAIRE_LOCK_NOTE =
  "完成问卷前，你无法预约新的实验。";
export const HISTORY_ARCHIVED_SUBMITTED_NOTE =
  "归档不影响你的完成状态与报酬。";
export const HISTORY_TECH_NOTE = "本次实验未完成，不产生基础费与绩效费。";
export const HISTORY_LABEL_NO_REWARD = NO_REWARD;
export const HISTORY_VIEW_REWARD = VIEW_REWARD_INFO;

export const ARCHIVE_REASON_LABELS: Record<ArchiveReason, string> = {
  completed: "正常完成",
  not_full: "人数不足",
  no_show: "未按时到齐",
  no_start: "双方到场未开始",
  abandoned: "参与者主动退出",
  technical_abort: "技术中止",
  questionnaire_incomplete: "问卷未完成",
  admin_aborted: "主试中止",
  admin_cancelled: "主试取消",
};

export interface ArchiveCopy {
  title: string;
  detail: string;
  showContact: boolean;
}

export function archiveCopyFor(
  reason: ArchiveReason | null,
  state: {
    selfExited: boolean;
    questionnaireCompleted: boolean;
    hasShowupPay: boolean;
  },
): ArchiveCopy {
  switch (reason) {
    case "completed":
      return {
        title: "实验已完成",
        detail:
          "双方已完成全部实验并提交后测问卷。你可以查看报酬信息，确认金额、支付状态和支付截止日期。",
        showContact: false,
      };
    case "not_full":
      return {
        title: "实验未能开始",
        detail:
          "等待时间结束时未达到两名参与者，本次实验未能开始，本次实验未完成，不产生报酬。你可以重新预约其他时间段参与实验。",
        showContact: false,
      };
    case "no_show":
      return {
        title: "实验未能开始",
        detail:
          "本次实验因参与者未按时到齐而未能开始，本次实验未完成，不产生报酬。你可以重新预约其他时间段参与实验。",
        showContact: false,
      };
    case "no_start":
      return {
        title: "实验未能开始",
        detail:
          "双方均已进入，但等待时间结束时仍未开始实验，本次实验未完成，不产生报酬。你可以重新预约其他时间段参与实验。",
        showContact: false,
      };
    case "abandoned":
      return state.selfExited
        ? {
            title: "你已退出实验",
            detail:
              "你已主动退出本次实验，本次实验未完成，无实验报酬。你可以重新预约。",
            showContact: false,
          }
        : {
            title: "实验已中止",
            detail:
              "另一名参与者已主动退出，实验被迫中止，无法计算报酬。你可以重新预约其他时间段参与实验",
            showContact: false,
          };
    case "technical_abort":
      return {
        title: "因技术原因中止",
        detail: state.hasShowupPay
          ? "因断线重连超时或系统故障，本次实验未完成，不产生基础费与绩效费。到场费按到场规则结算，你可以在报酬信息中查看金额、支付状态和支付截止日期。你可以重新预约其他时间段参与实验。"
          : "因断线重连超时或系统故障，本次实验未完成，不产生报酬。本次也没有到场费，且无法计算基础费与绩效费。你可以重新预约其他时间段参与实验。",
        showContact: true,
      };
    case "questionnaire_incomplete":
      return state.questionnaireCompleted
        ? {
            title: "实验已完成",
            detail:
              "你已提交后测问卷，房间归档原因为问卷未完成。归档不影响你的完成状态与报酬，你可以查看报酬信息。",
            showContact: true,
          }
        : {
            title: "待补交后测问卷",
            detail:
              "房间已归档，你的后测问卷尚未提交。本次实验未完成，不产生报酬。完成问卷前，你无法预约新的实验。继续填写问卷是获得报酬的唯一方式。",
            showContact: true,
          };
    case "admin_aborted":
      return {
        title: "实验已中止",
        detail:
          "本次实验由主试中止，实验未完成，不产生报酬。你可以重新预约其他时间段参与实验。",
        showContact: false,
      };
    case "admin_cancelled":
      return {
        title: "实验已取消",
        detail:
          "本次实验在开始前已取消，实验未完成，不产生报酬。你可以重新预约其他时间段参与实验。",
        showContact: false,
      };
    default:
      return {
        title: "房间已结束",
        detail:
          "本次实验已结束。你可以查看报酬信息，或联系实验主试了解详细情况。",
        showContact: true,
      };
  }
}
