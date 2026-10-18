import type {
  ArchiveReason,
  BookingStatus,
  ParticipantStatus,
  PaymentStatus,
  QuestionnaireStatus,
  RoomStatus,
  VersionStatus,
} from "../shared/types";

export type ChipTone = "neutral" | "success" | "warning" | "error" | "info";

export const ROOM_STATUS_LABELS: Record<RoomStatus, string> = {
  draft: "草稿",
  open: "可报名",
  full: "已满",
  waiting: "等待中",
  instructions: "指导语",
  playing: "对局中",
  questionnaire: "问卷中",
  archived: "已归档",
};

export function roomStatusTone(status: RoomStatus): ChipTone {
  switch (status) {
    case "open":
      return "info";
    case "full":
      return "warning";
    case "waiting":
      return "warning";
    case "instructions":
      return "info";
    case "playing":
      return "info";
    case "questionnaire":
      return "warning";
    case "archived":
      return "neutral";
    default:
      return "neutral";
  }
}

export const PARTICIPANT_STATUS_LABELS: Record<ParticipantStatus, string> = {
  eligible: "可参与",
  completed: "已完成",
  disabled: "已停用",
};

export function participantStatusTone(status: ParticipantStatus): ChipTone {
  switch (status) {
    case "eligible":
      return "info";
    case "completed":
      return "success";
    case "disabled":
      return "error";
    default:
      return "neutral";
  }
}

export const BOOKING_STATUS_LABELS: Record<BookingStatus, string> = {
  booked: "已预约",
  canceled: "已取消",
  attended: "已到场",
  no_show: "缺席",
};

export function bookingStatusTone(status: BookingStatus): ChipTone {
  switch (status) {
    case "booked":
      return "info";
    case "attended":
      return "success";
    case "no_show":
      return "error";
    case "canceled":
      return "neutral";
    default:
      return "neutral";
  }
}

export const PAYMENT_STATUS_LABELS: Record<PaymentStatus, string> = {
  pending: "待支付",
  paid: "已支付",
};

export function paymentStatusTone(status: PaymentStatus): ChipTone {
  return status === "paid" ? "success" : "warning";
}

export const VERSION_STATUS_LABELS: Record<VersionStatus, string> = {
  draft: "草稿",
  published: "已发布",
  archived: "已归档",
};

export function versionStatusTone(status: VersionStatus): ChipTone {
  switch (status) {
    case "draft":
      return "neutral";
    case "published":
      return "success";
    case "archived":
      return "neutral";
    default:
      return "neutral";
  }
}

export const QUESTIONNAIRE_STATUS_LABELS: Record<QuestionnaireStatus, string> = {
  not_started: "未开始",
  in_progress: "填写中",
  completed: "已完成",
};

export function questionnaireStatusTone(status: QuestionnaireStatus): ChipTone {
  switch (status) {
    case "completed":
      return "success";
    case "in_progress":
      return "info";
    default:
      return "neutral";
  }
}

export const ARCHIVE_REASON_LABELS: Record<ArchiveReason, string> = {
  completed: "正常完成",
  not_full: "人数不足",
  no_show: "参与者缺席",
  no_start: "未开始",
  abandoned: "参与者离开",
  technical_abort: "技术中断",
  questionnaire_incomplete: "问卷未完成",
  admin_aborted: "主试中止",
  admin_cancelled: "主试取消",
};

export function archiveReasonOptionsForStatus(
  status: RoomStatus,
  started: boolean,
): ArchiveReason[] {
  switch (status) {
    case "draft":
    case "open":
    case "full":
      return [started ? "admin_aborted" : "admin_cancelled"];
    case "waiting":
    case "instructions":
    case "playing":
      return ["admin_aborted"];
    case "questionnaire":
      return ["questionnaire_incomplete"];
    default:
      return [];
  }
}

export function defaultArchiveReasonForStatus(
  status: RoomStatus,
  started: boolean,
): ArchiveReason {
  switch (status) {
    case "draft":
    case "open":
    case "full":
      return started ? "admin_aborted" : "admin_cancelled";
    case "questionnaire":
      return "questionnaire_incomplete";
    default:
      return "admin_aborted";
  }
}

export const QUESTION_TYPE_LABELS: Record<string, string> = {
  single_choice: "单选",
  multiple_choice: "多选",
  likert: "李克特量表",
  text: "文本",
  number: "数字",
};

export const PHASE_LABELS: Record<string, string> = {
  waiting: "等待开始",
  instructions: "指导语",
  turn: "回合进行中",
  rest: "休息",
  questionnaire: "问卷填写",
  archived: "已归档",
  bookable: "可报名",
  playing: "对局中",
};

export function phaseLabel(phase: string | null): string {
  if (!phase) return "无运行阶段";
  return PHASE_LABELS[phase] ?? phase;
}
