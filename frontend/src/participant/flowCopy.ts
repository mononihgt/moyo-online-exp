import type { ArchiveReason, ExitReason } from "../shared/types";

export const BOOKING_SUCCESS = "预约成功。请在开始时间前进入等待。";
export const CANCEL_SUCCESS = "已取消预约。你可以重新选择场次。";

export const PENDING_QUESTIONNAIRE_TITLE = "待完成问卷";
export const PENDING_QUESTIONNAIRE_DETAIL =
  "你已完成本次正式实验，但后测问卷尚未提交。请提交后测问卷以完成本次实验并结算报酬；每位参与者只能参加一次正式实验，提交后也不能预约新的场次。";
export const PENDING_QUESTIONNAIRE_ARCHIVED_DETAIL =
  "本次实验已结束，你已完成正式实验，但后测问卷尚未提交。请继续填写并提交问卷，提交后按完成实验结算报酬；提交后也不能预约新的场次。";
export const CONTINUE_QUESTIONNAIRE = "继续填写问卷";
export const BOOKABLE_HIDDEN_NOTE =
  "你目前不能预约新的实验，因为每位参与者只能参加一次正式实验。";
export const SELF_SUBMITTED_TITLE = "实验已完成";
export const SELF_SUBMITTED_DETAIL =
  "你已提交后测问卷，本次实验已完成，无法再预约新的场次。双方都提交问卷后，本次实验将结束。你可以查看报酬信息。";
export const AFTER_START_BOOKING_NOTE =
  "开始时间到达后不能取消预约，也不能改报其他场次；如未进入实验，等待时间结束后本次实验将结束，不产生报酬。";
export const ACCOUNT_COMPLETED = "你已完成全部实验，无法再预约新的场次。";
export const ACCOUNT_DISABLED =
  "你的账号当前已停用，无法预约新的场次。如有疑问，请联系实验工作人员。";
export const ACCOUNT_PENDING_QUESTIONNAIRE =
  "你已完成正式实验但尚未提交后测问卷。提交问卷后本次实验完成；提交前后都不能预约新的场次。";
export const ACCOUNT_PAYMENT_LOCKED =
  "你已产生实验报酬，无法再预约新的场次。如有疑问，请联系实验工作人员。";
export const ACCOUNT_SHOWUP_QUESTIONNAIRE =
  "本次实验因网络或系统故障提前结束，你已到场。请先填写并提交后测问卷，提交后会生成到场费；本次实验结束后，你不能再预约新的实验。";
export const SHOWUP_QUESTIONNAIRE_TITLE = "实验提前结束：待填写问卷";
export const SHOWUP_QUESTIONNAIRE_PENDING_DETAIL =
  "本次实验因网络或系统故障提前结束，你已到场。填写并提交后测问卷后会生成到场费；本次实验结束后，你不能再预约新的实验。";
export const SHOWUP_QUESTIONNAIRE_SUBMITTED_DETAIL =
  "本次实验因网络或系统故障提前结束，后测问卷已提交。到场费按到场规则结算，本次实验不产生基础费与绩效费。";
export const SHOWUP_FEE_PENDING = "到场费待问卷提交后生成。";
export const BOOKABLE_HIDDEN_SHOWUP_NOTE =
  "你目前不能预约新的实验：本次实验因网络或系统故障提前结束。";
export const VIEW_REWARD_INFO = "查看报酬信息";
export const REBOOK = "重新预约";
export const CONTACT_EXPERIMENTER = "联系实验工作人员";

export const WAIT_SINGLE_DETAIL =
  "只有你一人报名。本次实验需要两名参与者。等待时间结束后若仍未达到两名参与者，本次实验将结束，不产生报酬。你可以继续等待，或点击下方“退出本次实验”返回首页并重新预约其他时间。实验开始后无法取消预约。";
export const WAIT_PARTNER_NOT_ENTERED_DETAIL =
  "另一名参与者尚未进入实验。本次实验需要两名参与者。等待时间结束后若仍未到齐，本次实验将结束，不产生报酬。你可以继续等待，或点击下方“退出本次实验”返回首页并重新预约其他时间。实验开始后无法取消预约。";
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
export const WAIT_EXIT_PARTNER = "另一名参与者尚未开始，我退出本次实验";
export const WAIT_EXIT_TITLE = "确认退出本次实验？";
export const WAIT_EXIT_DETAIL =
  "退出后本次实验将结束，不产生报酬。你可以返回首页重新预约其他时间段。";
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
  "另一名参与者离线，正在等待重连。重连时间结束后，本次实验将结束。";
export const INSTRUCTION_SELF_DISCONNECTED =
  "连接中断，阅读计时已暂停；请在重连时间内恢复连接。重连时间结束后，本次实验将结束。";
export const TURN_SELF_DISCONNECTED =
  "连接中断，正在重新连接。请保持页面打开。重连时间结束后本次实验将结束。";
export const REST_SELF_DISCONNECTED =
  "连接中断，正在重新连接。倒计时已暂停。重连时间结束后本次实验将结束。";
export const PARTNER_OFFLINE_RECONNECTING =
  "另一名参与者离线，正在等待重连。重连时间结束后，本次实验将结束。";
export const RECONNECTING_NOTICE = "连接中断，正在重新连接。请保持页面打开。";

export const QUESTIONNAIRE_REQUIRED =
  "请完成实验后测问卷。提交问卷后才会计算实验报酬。";
export const QUESTIONNAIRE_SUBMITTED =
  "后测问卷已提交，感谢你的参与。你可以查看报酬信息与历史实验记录。";
export const QUESTIONNAIRE_BUTTON = "填写后测问卷";
export const QUESTIONNAIRE_LINK_FAILED =
  "暂时无法生成问卷链接。请联系实验工作人员获取问卷地址。";
export const QUESTIONNAIRE_DUPLICATE =
  "该实验的问卷已提交，无需重复填写。";

export const COMPLETE_PAGE_TITLE = "报酬信息";
export const COMPLETE_PAGE_DESCRIPTION =
  "本次实验的记录与报酬结算信息。";
export const NO_REWARD = "本次实验未完成，不产生报酬";
export const COMPLETE_PENDING_DETAIL =
  "你已完成本次正式实验，但后测问卷尚未提交。请提交后测问卷以完成本次实验并结算基础费与绩效费；每位参与者只能参加一次正式实验，提交后也不能预约新的场次。";
export const COMPLETE_PENDING_ARCHIVED_DETAIL =
  "本次实验已结束，你已完成正式实验，但后测问卷尚未提交。你仍可以继续填写并提交问卷，提交后按完成实验结算基础费与绩效费；提交后也不能预约新的场次。";
export const COMPLETE_TRANSFER_NOTE =
  "报酬将在提交后测问卷后的第一个周日 24:00 前通过支付宝完成转账。如逾期未收到，请通过“联系实验工作人员”与实验组织者核对。";
export const COMPLETE_ARCHIVED_SUBMITTED_NOTE =
  "实验记录已保存，不影响你的完成状态与报酬。";
export const COMPLETE_TECH_SHOWUP_NOTE =
  "本次实验未完成，不产生基础费与绩效费。到场费将在提交后测问卷后的第一个周日 24:00 前通过支付宝完成转账。";
export const COMPLETE_TECH_SHOWUP_PENDING_NOTE =
  "本次实验未完成，不产生基础费与绩效费。填写并提交后测问卷后生成到场费。";
export const COMPLETE_TECH_ZERO_NOTE =
  "因断线重连超时或系统故障，本次实验未完成，不产生报酬，也没有到场费。";
export const COMPLETE_REBOOK_NOTE = "你可以重新预约其他时间段参与实验。";
export const COMPLETE_QUESTIONNAIRE_ARCHIVE_NOTE =
  "本次实验已结束，结束原因为后测问卷未完成。你仍可继续填写并提交问卷。";
export const HISTORY_QUESTIONNAIRE_LOCK_NOTE =
  "提交问卷前后，你都不能预约新的实验。";
export const HISTORY_ARCHIVED_SUBMITTED_NOTE =
  "实验记录已保存，不影响你的完成状态与报酬。";
export const HISTORY_TECH_NOTE = "本次实验未完成，不产生基础费与绩效费。";
export const HISTORY_LABEL_NO_REWARD = NO_REWARD;
export const HISTORY_VIEW_REWARD = VIEW_REWARD_INFO;

export const ARCHIVE_REASON_LABELS: Record<ArchiveReason, string> = {
  completed: "正常完成",
  not_full: "人数不足",
  no_show: "有参与者未到场",
  no_start: "双方到场但未开始",
  abandoned: "实验提前结束",
  technical_abort: "网络或系统故障",
  questionnaire_incomplete: "后测问卷未完成",
  admin_aborted: "实验工作人员提前结束",
  admin_cancelled: "实验开始前取消",
};

export interface ArchiveCopy {
  title: string;
  detail: string;
  showContact: boolean;
}

export interface ArchiveCopyState {
  selfExited: boolean;
  selfExitReason: ExitReason | null;
  partnerExitReason: ExitReason | null;
  questionnaireCompleted: boolean;
  questionnaireRequired: boolean;
  hasShowupPay: boolean;
  canRebook: boolean;
}

const REBOOK_DETAIL = "你可以重新预约其他时间段参与实验。";
const SHOWUP_LOCK_DETAIL = "你已获得本次实验的到场费，无法再预约新的场次。";

function withRebook(detail: string, canRebook: boolean): string {
  return canRebook ? `${detail}${REBOOK_DETAIL}` : detail;
}

export function archiveCopyFor(
  reason: ArchiveReason | null,
  state: ArchiveCopyState,
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
        detail: withRebook(
          "等待时间结束时未达到两名参与者，本次实验未能开始，不产生报酬。",
          state.canRebook,
        ),
        showContact: false,
      };
    case "no_show":
      return {
        title: "实验未能开始",
        detail: withRebook(
          "本次实验因有参与者未按时到齐而未能开始，不产生报酬。",
          state.canRebook,
        ),
        showContact: false,
      };
    case "no_start":
      return {
        title: "实验未能开始",
        detail: withRebook(
          "双方均已进入，但等待时间结束时仍未开始实验，本次实验未能开始，不产生报酬。",
          state.canRebook,
        ),
        showContact: false,
      };
    case "abandoned":
      if (state.selfExited) {
        if (state.selfExitReason === "inactivity") {
          return {
            title: "实验已自动结束",
            detail: withRebook(
              "你长时间没有操作，本次实验已自动结束，未完成，不产生报酬。",
              state.canRebook,
            ),
            showContact: false,
          };
        }
        return {
          title: "你已退出实验",
          detail: withRebook(
            "你已主动退出本次实验，本次实验未完成，无实验报酬。",
            state.canRebook,
          ),
          showContact: false,
        };
      }
      if (state.partnerExitReason === "inactivity") {
        return {
          title: "实验已自动结束",
          detail: withRebook(
            "另一名参与者长时间没有操作，本次实验已自动结束，未完成，不产生报酬。",
            state.canRebook,
          ),
          showContact: false,
        };
      }
      return {
        title: "实验已结束",
        detail: withRebook(
          "另一名参与者已退出本次实验，实验被迫结束，无法计算报酬。",
          state.canRebook,
        ),
        showContact: false,
      };
    case "technical_abort": {
      if (state.questionnaireRequired) {
        return {
          title: "实验提前结束",
          detail: SHOWUP_QUESTIONNAIRE_PENDING_DETAIL,
          showContact: true,
        };
      }
      const base = state.hasShowupPay
        ? "因网络或系统故障，本次实验未完成，不产生基础费与绩效费。到场费按到场规则结算，你可以在报酬信息中查看金额、支付状态和支付截止日期。"
        : "因网络或系统故障，本次实验未完成，不产生报酬，也没有到场费。";
      return {
        title: "实验提前结束",
        detail:
          state.hasShowupPay && !state.canRebook
            ? `${base}${SHOWUP_LOCK_DETAIL}`
            : withRebook(base, state.canRebook),
        showContact: true,
      };
    }
    case "questionnaire_incomplete":
      return state.questionnaireCompleted
        ? {
            title: "实验已完成",
            detail:
              "你已提交后测问卷，本次实验已结束。实验记录已保存，不影响你的完成状态与报酬，你可以查看报酬信息。",
            showContact: true,
          }
        : {
            title: "待补交后测问卷",
            detail:
              "本次实验已结束，你的后测问卷尚未提交。请继续填写并提交问卷，提交后按完成实验结算报酬；提交后也不能预约新的场次。",
            showContact: true,
          };
    case "admin_aborted":
      return {
        title: "实验已结束",
        detail: withRebook(
          "本次实验由实验工作人员提前结束，未完成，不产生报酬。",
          state.canRebook,
        ),
        showContact: false,
      };
    case "admin_cancelled":
      return {
        title: "实验已取消",
        detail: withRebook(
          "本次实验在开始前已取消，未完成，不产生报酬。",
          state.canRebook,
        ),
        showContact: false,
      };
    default:
      return {
        title: "实验已结束",
        detail:
          "本次实验已结束。你可以查看报酬信息，或联系实验工作人员了解详细情况。",
        showContact: true,
      };
  }
}
