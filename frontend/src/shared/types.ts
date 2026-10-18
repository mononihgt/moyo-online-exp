export type ParticipantStatus = "eligible" | "completed" | "disabled";
export type RoomStatus =
  | "draft"
  | "open"
  | "full"
  | "waiting"
  | "instructions"
  | "playing"
  | "questionnaire"
  | "archived";
export type ArchiveReason =
  | "completed"
  | "not_full"
  | "no_show"
  | "abandoned"
  | "technical_abort"
  | "questionnaire_incomplete"
  | "admin_cancelled";
export type BookingStatus = "booked" | "canceled" | "attended" | "no_show";
export type QuestionnaireStatus = "not_started" | "in_progress" | "completed";
export type VersionStatus = "draft" | "published" | "archived";
export type PaymentStatus = "pending" | "paid";

export interface ParticipantMe {
  id: string;
  name: string;
  phoneMasked: string;
  status: ParticipantStatus;
  canBook: boolean;
  consentRequired: boolean;
  consentVersion: { id: string; version: number; publishedAt: string | null } | null;
  completedExperiments: number;
  isDisabled: boolean;
  isCompleted: boolean;
}

export interface ConsentDocument {
  versionId: string;
  version: number;
  markdown: string;
  html: string;
  publishedAt: string | null;
}

export interface BookableRoom {
  id: string;
  startsAt: string;
  bookedCount: number;
  capacity: number;
  full: boolean;
  canBook: boolean;
  alreadyBooked: boolean;
}

export interface CurrentRoom {
  roomId: string;
  startsAt: string;
  bookedCount: number;
  capacity: number;
  status: RoomStatus;
  archiveReason: ArchiveReason | null;
  canEnter: boolean;
  role: 1 | 2 | null;
  instructionCompleted: boolean;
  questionnaireStatus: QuestionnaireStatus | null;
  completedAt: string | null;
}

export interface Payment {
  id?: string;
  analysisCode: string | null;
  roomId?: string;
  roomStartsAt?: string;
  roomStatus?: RoomStatus;
  roomArchiveReason?: ArchiveReason | null;
  basePayCents: number;
  performancePayCents: number;
  showupPayCents: number;
  overrideAmountCents: number | null;
  totalCents: number;
  status: PaymentStatus;
  computedAt: string | null;
  deadlineAt: string;
  paidAt: string | null;
  note: string | null;
}

export interface ExperimentRecord {
  roomId: string;
  startsAt: string;
  roomStatus: RoomStatus;
  archiveReason: ArchiveReason | null;
  bookingStatus: BookingStatus;
  role: 1 | 2 | null;
  instructionCompleted: boolean;
  questionnaireStatus: QuestionnaireStatus | null;
  completedAt: string | null;
  payment: Payment | null;
}

export interface MediaAsset {
  assetId: string;
  id: string;
  kind: string;
  filename: string;
  contentType: string;
  sha256: string;
  sizeBytes: number;
  width: number;
  height: number;
  url: string;
}

export interface ConditionCell {
  row: number;
  col: number;
  initialOwner: 0 | 1 | 2;
  initialSoldiers: number;
  reinforcementA: number;
  reinforcementB: number;
}

export interface ConditionVisual {
  color: string | null;
  backgroundAssetId: string | null;
}

export interface ReinforcementOverrideEntry {
  cellIndex: number;
  value: number;
}

export interface ReinforcementOverrides {
  player1?: ReinforcementOverrideEntry[];
  player2?: ReinforcementOverrideEntry[];
}

export interface TrialParam {
  sourceIndex: number;
  isPractice: boolean;
  formalTrial: number;
  baseSoldiersA: number;
  baseSoldiersB: number;
  reinforcementOverrides: ReinforcementOverrides | null;
}

export interface ConditionVersion {
  id: string;
  name: string;
  version: number;
  schemaVersion: number;
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
  status: VersionStatus;
  contentHash: string | null;
  publishedAt: string | null;
  createdAt: string;
}

export interface InstructionVersion {
  id: string;
  versionId: string;
  name: string;
  version: number;
  role: 1 | 2;
  minReadingSeconds: number;
  contentMarkdown: string;
  contentHtml: string;
  contentHash: string | null;
  status: VersionStatus;
  publishedAt: string | null;
  createdAt: string;
}

export type QuestionType = "single_choice" | "multiple_choice" | "likert" | "text" | "number";

export interface QuestionnaireOption {
  value: string;
  label: string;
}

export interface QuestionnaireQuestion {
  id: string;
  type: QuestionType;
  label: string;
  required: boolean;
  options?: QuestionnaireOption[];
  min?: number;
  max?: number;
  minLabel?: string;
  maxLabel?: string;
  help?: string;
}

export interface QuestionnairePage {
  id: string;
  questions: QuestionnaireQuestion[];
}

export interface QuestionnaireSchema {
  title: string;
  description?: string;
  pages: QuestionnairePage[];
}

export interface QuestionnaireVersion {
  id: string;
  versionId: string;
  name: string;
  version: number;
  contentHash: string | null;
  status: VersionStatus;
  publishedAt: string | null;
  createdAt: string;
  schema: QuestionnaireSchema;
}

export interface RoomSummary {
  id: string;
  internalLabel: string;
  startsAt: string;
  status: RoomStatus;
  archiveReason: ArchiveReason | null;
  bookedCount: number;
  capacity: number;
  condition: { id: string; name: string; version: number };
  instructions: {
    player1: { id: string; name: string; version: number };
    player2: { id: string; name: string; version: number };
  };
  questionnaire: { id: string; name: string; version: number };
  basePayCents: number;
  performanceRateCents: number;
  showupPayCents: number;
  waitWindowSeconds: number;
  reconnectWindowSeconds: number;
  configLockedAt: string | null;
  publishedAt: string | null;
  archivedAt: string | null;
  createdAt: string;
}

export interface AdminParticipant {
  id: string;
  name: string;
  phoneMasked: string;
  status: ParticipantStatus;
  consentedAt: string | null;
  notes: string | null;
  createdAt: string;
}

export interface AdminBooking {
  id: string;
  participantId: string;
  name: string;
  phoneMasked: string;
  participantStatus: ParticipantStatus;
  status: BookingStatus;
  createdAt: string;
  canceledAt: string | null;
  attendedAt: string | null;
}

export interface AdminRoomParticipant {
  id: string;
  role: 1 | 2;
  analysisCode: string;
  name: string;
  phoneMasked: string;
  participantStatus: ParticipantStatus;
  instructionStartedAt: string | null;
  instructionCompletedAt: string | null;
  instructionConnectedSeconds: number;
  questionnaireStatus: QuestionnaireStatus;
  completedAt: string | null;
  online: boolean;
}

export interface RoomDetail {
  room: RoomSummary;
  config: Record<string, unknown>;
  configRevisions: { revision: number; createdAt: string; config: Record<string, unknown> }[];
  configSnapshot: Record<string, unknown> | null;
  bookings: AdminBooking[];
  participants: AdminRoomParticipant[];
  payments: Payment[];
  jatosAdminUrl: string | null;
  jatosStudyCode: string | null;
}

export interface RoomMonitor {
  room: RoomSummary;
  phase: string | null;
  trialIndex: number | null;
  round: number | null;
  turnDeadline: string | null;
  restDeadline: string | null;
  participants: {
    role: 1 | 2;
    name: string;
    online: boolean;
    instructionCompleted: boolean;
    questionnaireStatus: QuestionnaireStatus;
    disconnectedUntil: string | null;
  }[];
  trials: {
    trialIndex: number;
    isPractice: boolean;
    formalTrial: number;
    startedAt: string | null;
    endedAt: string | null;
    winner: number | null;
    endReason: string | null;
  }[];
  events: { type: string; createdAt: string; payload: Record<string, unknown> | null }[];
  timers: { kind: string; dueAt: string; status: string; firedAt: string | null }[];
}

export interface PaymentAdmin extends Payment {
  participantId: string;
  name: string;
  phoneMasked: string;
  roomStartsAt: string;
}

export interface AuditEntry {
  id: string;
  adminUserId: string | null;
  action: string;
  targetType: string | null;
  targetId: string | null;
  payload: Record<string, unknown> | null;
  createdAt: string;
}

export interface AdminSettings {
  jatosBaseUrl: string;
  jatosStudyCode: string;
  contactInfo: string | null;
  timezone: string;
  hasJatosToken: boolean;
  publicBaseUrl: string;
}

export interface QuestionnaireContext {
  roomId: string;
  analysisCode: string;
  completed: boolean;
  questionnaire: QuestionnaireVersion;
  draftAnswers: Record<string, unknown> | null;
  existingAnswers: Record<string, unknown> | null;
  redirectUrl: string;
  platformBaseUrl: string;
}

export interface BoardState {
  rows: number;
  cols: number;
  owners: number[];
  soldiers: number[];
}

export interface PartnerState {
  online: boolean;
  entered: boolean;
  startRequested: boolean;
  instructionCompleted: boolean;
  submitted?: boolean;
  ready?: boolean;
  disconnectedUntil: string | null;
}

export interface InstructionState {
  role: 1 | 2;
  contentMarkdown: string;
  contentHtml: string;
  minReadingSeconds: number;
  connectedSeconds: number;
  completed: boolean;
  partnerCompleted: boolean;
  bothCompleted: boolean;
  canEnterGame: boolean;
  enterRequested: boolean;
  bothEnterRequested: boolean;
}

export interface GameState {
  phase: "turn" | "rest" | "questionnaire" | string;
  trialIndex: number;
  gameNumber: number;
  totalTrials: number;
  isPractice: boolean | null;
  formalTrial: number | null;
  round: number;
  turnCount: number;
  turnSeconds: number;
  restSeconds: number;
  board: BoardState | null;
  visuals: ConditionVisual[];
  turnDeadline: string | null;
  restDeadline: string | null;
  submitted: boolean;
  partnerSubmitted: boolean;
  restReady: Record<string, boolean>;
}

export interface RoomStateMessage {
  type: "room_state";
  roomId: string;
  status: RoomStatus;
  archiveReason: ArchiveReason | null;
  serverNow: string;
  startsAt: string;
  waitDeadline: string;
  bookedCount: number;
  capacity: number;
  phase: string | null;
  role: 1 | 2 | null;
  enterRequests: string[];
  self: {
    startRequested: boolean;
    instructionCompleted: boolean;
    questionnaireStatus: QuestionnaireStatus | null;
    completedAt: string | null;
  };
  partner: PartnerState;
  instruction?: InstructionState;
  game?: GameState;
  questionnaire?: { url: string | null; status: QuestionnaireStatus; submitted: boolean };
  archive?: { reason: ArchiveReason; canRebook: boolean };
}

export interface TurnMessage {
  type: "turn";
  roomId: string;
  trialIndex: number;
  round: number;
  turnCount: number | null;
  turnSeconds: number | null;
  deadline: string | null;
  board: BoardState;
  submitted: boolean;
  partnerSubmitted: boolean;
}

export interface TurnResultMessage {
  type: "turn_result";
  roomId: string;
  trialIndex: number;
  round: number;
  selections: { player1: number[]; player2: number[] };
  selectionSources: { player1: string | null; player2: string | null };
  autoSelected: { player1: boolean; player2: boolean };
  warLocation: number[];
  warLost: { player1: number[]; player2: number[] };
  logistics: { player1: number; player2: number };
  board: BoardState;
  trialEnded: boolean;
  nextRound?: number;
  deadline?: string;
}

export interface RestMessage {
  type: "rest";
  roomId: string;
  completedTrialIndex: number;
  completedIsPractice: boolean;
  completedFormalTrial: number;
  nextTrialIndex: number | null;
  nextIsPractice: boolean | null;
  nextFormalTrial: number | null;
  restSeconds: number;
  deadline: string | null;
  ready: Record<string, boolean>;
}

export interface TrialStartMessage {
  type: "trial_start";
  roomId: string;
  trialIndex: number;
  gameNumber: number;
  totalTrials: number;
  isPractice: boolean;
  formalTrial: number;
  round: number;
  turnCount: number;
  turnSeconds: number;
  board: BoardState;
  visuals: ConditionVisual[];
}

export type ServerMessage =
  | RoomStateMessage
  | TurnMessage
  | TurnResultMessage
  | RestMessage
  | TrialStartMessage
  | { type: "game_start"; roomId: string; totalTrials: number }
  | { type: "partner_state"; roomId: string; partner: PartnerState }
  | { type: "instruction_state"; roomId: string; instruction: InstructionState }
  | { type: "rest_complete"; roomId: string }
  | { type: "game_over"; roomId: string; trialsCompleted: number; questionnaireUrl: string | null }
  | { type: "questionnaire_required"; roomId: string; url: string | null; status: QuestionnaireStatus }
  | { type: "room_archived"; roomId: string; reason: ArchiveReason | null; canRebook?: boolean }
  | { type: "trial_start"; roomId: string }
  | { type: "error"; code: string; message: string }
  | { type: "pong"; serverNow: string };
