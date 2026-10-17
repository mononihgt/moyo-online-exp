import { ApiError } from "../shared/api";
import type {
  ArchiveReason,
  BookableRoom,
  ConsentDocument,
  CurrentRoom,
  ExperimentRecord,
  ParticipantMe,
  Payment,
  QuestionnaireStatus,
  RoomStatus,
} from "../shared/types";

export interface MeResponse {
  me: ParticipantMe;
  csrfToken: string | null;
  serverNow?: string;
}

export interface LoginResponse {
  me: ParticipantMe;
  csrfToken: string;
}

export interface ConsentSubmitResponse {
  agreed: boolean;
  loggedOut?: boolean;
  me?: ParticipantMe;
}

export interface BookableRoomsResponse {
  rooms: BookableRoom[];
  serverNow: string;
  timezone: string;
  canBook: boolean;
}

export interface PendingQuestionnaire {
  roomId: string;
  startsAt: string;
  questionnaireStatus: QuestionnaireStatus;
}

export interface MyRoomResponse {
  room: CurrentRoom | null;
  bookingId?: string;
  pendingQuestionnaires?: PendingQuestionnaire[];
}

export interface MyExperimentsResponse {
  experiments: ExperimentRecord[];
}

export interface MyPaymentsResponse {
  payments: Payment[];
  timezone: string;
}

export interface QuestionnaireContextResponse {
  roomId: string;
  url: string | null;
  status: QuestionnaireStatus;
  submitted: boolean;
}

export interface ContactResponse {
  contact: string | null;
}

export type ConsentDocumentResponse = ConsentDocument;

export type ClientMessage =
  | { type: "enter_room"; roomId: string }
  | { type: "start_matching"; roomId: string }
  | { type: "exit_room"; roomId: string }
  | { type: "instruction_complete"; roomId: string }
  | { type: "enter_game"; roomId: string }
  | {
      type: "submit_selection";
      roomId: string;
      trialIndex: number;
      round: number;
      cells: number[];
      clientMsgId: string;
    }
  | { type: "rest_ready"; roomId: string }
  | { type: "ping"; roomId: string };

export const ROLE_LABELS: Record<1 | 2, string> = {
  1: "圆形玩家",
  2: "菱形玩家",
};

export const ROOM_STATUS_LABELS: Record<RoomStatus, string> = {
  draft: "未发布",
  open: "等待开始",
  full: "等待开始",
  waiting: "等待搭档",
  instructions: "阅读指导语",
  playing: "实验进行中",
  questionnaire: "待填写问卷",
  archived: "已结束",
};

export const QUESTIONNAIRE_STATUS_LABELS: Record<QuestionnaireStatus, string> = {
  not_started: "未开始",
  in_progress: "填写中",
  completed: "已完成",
};

export interface ArchiveCopy {
  title: string;
  detail: string;
  showContact?: boolean;
}

export const ARCHIVE_COPY: Record<ArchiveReason, ArchiveCopy> = {
  completed: {
    title: "实验已完成",
    detail: "本次实验已经结束。你可以在完成页面查看费用与支付状态。",
  },
  not_full: {
    title: "报名人数不足",
    detail: "等待窗口结束前未达到两名参与者，本次实验已关闭。你可以改报其他时间。",
  },
  no_show: {
    title: "搭档未到场",
    detail: "另一名参与者未按时到场，本次实验未能开始。你可以改报其他时间。",
  },
  abandoned: {
    title: "实验已中止",
    detail: "搭档已离开本次实验，本次实验已结束。你可以改报其他时间。",
  },
  technical_abort: {
    title: "因技术原因中止",
    detail: "连接未能按时恢复，本次实验已中止。费用会按照到场规则处理。如需帮助，请联系实验主试。",
    showContact: true,
  },
  questionnaire_incomplete: {
    title: "问卷未完成",
    detail: "后测问卷未完成，本次实验记录已归档。请联系实验主试确认后续安排。",
    showContact: true,
  },
  admin_cancelled: {
    title: "实验已取消",
    detail: "实验主试已取消本次实验。你可以改报其他时间。",
  },
};

export function formatUnknownError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return error.message || fallback;
  }
  return fallback;
}

export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}
