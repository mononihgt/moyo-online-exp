import type {
  AdminParticipant,
  ConditionCell,
  ConditionVersion,
  ConditionVisual,
  InstructionVersion,
  MediaAsset,
  QuestionnaireVersion,
  RoomSummary,
  TrialParam,
  VersionStatus,
} from "../shared/types";

export interface AdminIdentity {
  id: string;
  username: string;
  lastLoginAt?: string | null;
}

export interface AdminMeResponse {
  admin: AdminIdentity;
  csrfToken: string;
}

export interface DashboardData {
  roomCounts: Record<string, number>;
  pendingPayments: number;
  pendingQuestionnaireRooms: number;
  pendingQuestionnaireCount?: number;
  upcomingRooms: RoomSummary[];
  attentionRooms: RoomSummary[];
}

export interface ParticipantListResponse {
  participants: AdminParticipant[];
  total: number;
}

export interface RosterImportError {
  row: number;
  name: string;
  phoneMasked: string;
  error: string;
}

export interface RosterImportReport {
  total: number;
  imported: number;
  skipped: number;
  errors: RosterImportError[];
}

export interface CompletedImportRow {
  row: number;
  name: string;
  phoneMasked: string;
  status: "matched" | "unmatched";
  error: string | null;
}

export interface CompletedImportReport {
  total: number;
  matched: number;
  unmatched: number;
  rows: CompletedImportRow[];
}

export interface ConsentVersionAdmin {
  id: string;
  version: number;
  markdown: string;
  status: VersionStatus;
  publishedAt: string | null;
  createdAt: string;
}

export interface ConsentVersionListResponse {
  versions: ConsentVersionAdmin[];
}

export interface MediaListResponse {
  media: MediaAsset[];
}

export interface MediaUploadResponse {
  asset: MediaAsset;
}

export interface ConditionListResponse {
  conditions: ConditionVersion[];
}

export interface ConditionResponse {
  condition: ConditionVersion;
}

export interface InstructionListResponse {
  instructions: InstructionVersion[];
}

export interface QuestionnaireListResponse {
  questionnaires: QuestionnaireVersion[];
}

export interface RoomListResponse {
  rooms: RoomSummary[];
}

export interface RoomResponse {
  room: RoomSummary;
}

export interface RoomCopyPayload {
  startsAt?: string;
  internalLabel?: string;
}

export interface ConditionDraftPayload {
  name: string;
  description: string | null;
  rows: number;
  cols: number;
  cells: ConditionCell[];
  visuals: { player1: ConditionVisual[]; player2: ConditionVisual[] };
  baseAIndex: number;
  baseBIndex: number;
  practiceTrials: number;
  formalTrials: number;
  turnCount: number;
  turnSeconds: number;
  restSeconds: number;
  randomizeFormal: boolean;
  trialParams: TrialParam[];
  metadata: Record<string, unknown>;
}

export interface RoomDraftPayload {
  internalLabel: string;
  startsAt: string;
  conditionVersionId: string;
  instructionVersionP1Id: string;
  instructionVersionP2Id: string;
  questionnaireVersionId: string;
  basePayCents: number;
  performanceRateCents: number;
  showupPayCents: number;
  waitWindowSeconds: number;
  reconnectWindowSeconds: number;
}

export interface QuestionnaireLink {
  participantId: string;
  url: string;
}

export interface ResendQuestionnaireResponse {
  links: QuestionnaireLink[];
}

export interface PaymentsResponse {
  payments: import("../shared/types").PaymentAdmin[];
}

export interface AuditResponse {
  entries: import("../shared/types").AuditEntry[];
  total: number;
}

export interface RoomActionPayload {
  action: string;
  reason?: string;
  minutes?: number;
  participantId?: string;
  jatosWorkerId?: string;
  jatosStudyResultId?: string;
  jatosComponentResultId?: string;
  answers?: Record<string, unknown>;
}
