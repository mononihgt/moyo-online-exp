import type {
  AdminParticipant,
  BulkPaymentRecord,
  InstructionVersion,
  MapGroupPayment,
  MapGroupVersion,
  MapSlot,
  MediaAsset,
  QuestionnaireVersion,
  RoomSection,
  RoomSummary,
  TroopProfile,
  TroopProfileRow,
  TroopProfileVersion,
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
  pendingShowupQuestionnaireCount: number;
  pendingShowupQuestionnaireRooms: RoomSummary[];
  upcomingCount: number;
  upcomingRooms: RoomSummary[];
  attentionRooms: RoomSummary[];
}

export interface ParticipantListResponse {
  participants: AdminParticipant[];
  total: number;
}

export interface CompletedImportRow {
  row: number;
  name: string;
  phoneMasked: string;
  status: "created" | "matched" | "unmatched";
  error: string | null;
}

export interface CompletedImportReport {
  total: number;
  created: number;
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

export interface TroopProfileListResponse {
  profiles: TroopProfile[];
}

export interface TroopProfileResponse {
  troopProfile: TroopProfileVersion;
}

export interface TroopProfileDraftPayload {
  name: string;
  rows: TroopProfileRow[];
}

export interface MapGroupListResponse {
  mapGroups: MapGroupVersion[];
}

export interface MapGroupResponse {
  mapGroup: MapGroupVersion;
}

export interface MapGroupMapPayload {
  slot: MapSlot;
  description: string;
  factorLevel: string;
  cells: (string | null)[];
  colors: (string | null)[];
}

export interface MapGroupDraftPayload {
  mode: "both" | "ab";
  rows: number;
  cols: number;
  spawns: { A: number; B: number };
  troopProfileVersionId: string;
  practiceTrials: number;
  formalTrials: number;
  practiceTurnCap: number;
  practiceTurnSeconds: number;
  formalTurnCap: number;
  formalTurnSeconds: number;
  restSeconds: number;
  randomizeFormal: boolean;
  payment: MapGroupPayment;
  maps: MapGroupMapPayload[];
}

export interface InstructionListResponse {
  instructions: InstructionVersion[];
}

export interface InstructionResponse {
  instruction: InstructionVersion;
}

export interface QuestionnaireListResponse {
  questionnaires: QuestionnaireVersion[];
}

export interface QuestionnaireResponse {
  questionnaire: QuestionnaireVersion;
}

export interface RoomListResponse {
  rooms: RoomSummary[];
  counts: Record<RoomSection, number>;
}

export interface RoomResponse {
  room: RoomSummary;
}

export interface RoomCopyPayload {
  startsAt?: string;
  internalLabel?: string;
}

export interface RoomDraftPayload {
  internalLabel: string;
  startsAt: string;
  mapGroupVersionId: string;
  instructionVersionP1Id: string;
  instructionVersionP2Id: string;
  questionnaireVersionId: string;
  waitWindowSeconds: number;
  reconnectWindowSeconds: number;
}

export interface RoomBatchPayload {
  template: RoomDraftPayload;
  count: number;
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

export interface BulkPaymentsResponse {
  payments: BulkPaymentRecord[];
  from: string;
  to: string;
}

export interface BulkMarkPaidResponse {
  updated: number;
  skipped: number;
  payments: BulkPaymentRecord[];
}

export interface AuditResponse {
  entries: import("../shared/types").AuditEntry[];
  total: number;
}

export interface RoomActionPayload {
  action: string;
  reason?: string;
  note?: string;
  expectedCurrentReason?: string;
  minutes?: number;
  participantId?: string;
  bookingId?: string;
  jatosWorkerId?: string;
  jatosStudyResultId?: string;
  jatosComponentResultId?: string;
  answers?: Record<string, unknown>;
}

export interface IdentityRecord {
  realName: string;
  alipayPhone: string;
  documentType: "id_card" | "passport";
  documentNumber: string;
}

export interface IdentityResponse {
  identity: IdentityRecord | null;
}

export interface ManualPaymentPayload {
  roomId: string;
  participantId: string;
  bookingId: string;
  kind: "manual_showup" | "manual_completion" | "manual_compensation";
  amountCents: number;
  adminNote: string;
  identity?: IdentityRecord | null;
}
