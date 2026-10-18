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
  archiveReason: ArchiveReason | null;
  canContinue: boolean;
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
  archiveReason: ArchiveReason | null;
  roomStatus: RoomStatus;
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

export function formatUnknownError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return error.message || fallback;
  }
  return fallback;
}

export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}
