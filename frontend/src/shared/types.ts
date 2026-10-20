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
export type RoomSection = "draft" | "open" | "in_progress" | "unpaid" | "archived";
export type ArchiveReason =
  | "completed"
  | "not_full"
  | "no_show"
  | "no_start"
  | "abandoned"
  | "technical_abort"
  | "questionnaire_incomplete"
  | "admin_aborted"
  | "admin_cancelled";
export type ExitReason = "manual" | "inactivity";
export type RewardKind = "completion" | "showup" | "none";
export type BookingStatus = "booked" | "canceled" | "attended" | "no_show";
export type QuestionnaireStatus = "not_started" | "in_progress" | "completed";
export type VersionStatus = "draft" | "published" | "archived";
export type PaymentStatus = "pending" | "paid";
export type MapGroupMode = "both" | "ab";
export type MapSlot = "Both" | "A" | "B";
export type DocumentType = "id_card" | "passport";
export type Role = 1 | 2;

export interface ParticipantMe {
  id: string;
  name: string;
  phoneMasked: string;
  status: ParticipantStatus;
  canBook: boolean;
  hasPendingQuestionnaire: boolean;
  hasShowupQuestionnaire: boolean;
  hasPayment: boolean;
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
  canCancel: boolean;
  bookingStatus: BookingStatus;
  role: Role | null;
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
  role: Role | null;
  instructionCompleted: boolean;
  questionnaireStatus: QuestionnaireStatus | null;
  completedAt: string | null;
  payment: Payment | null;
  selfAttended: boolean;
  selfExited: boolean;
  selfExitReason: ExitReason | null;
  canRebook: boolean;
  questionnaireRequired: boolean;
  showupPayCents: number;
  rewardKind: RewardKind;
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

export interface TroopProfileRow {
  soldiersA: number;
  soldiersB: number;
}

export interface TroopProfileVersion {
  id: string;
  profileId: string;
  name: string;
  builtIn: boolean;
  version: number;
  rows: TroopProfileRow[];
  practiceTrials: number;
  formalTrials: number;
  status: VersionStatus;
  contentHash: string | null;
  publishedAt: string | null;
  createdAt: string;
}

export interface TroopProfile {
  id: string;
  name: string;
  builtIn: boolean;
  createdAt: string;
  versions: TroopProfileVersion[];
}

export interface MapGroupPayment {
  basePayCents: number;
  performanceRateCents: number;
  performanceFloorCents: number;
  performanceCapCents: number;
  showupPayCents: number;
}

export interface TroopProfileRef {
  profileId: string;
  versionId: string;
  name: string;
  version: number;
  builtIn: boolean;
  rows: TroopProfileRow[];
}

export interface MapInfo {
  slot: MapSlot;
  name: string;
  description: string;
  sizeToken: string;
  factorLevel: string;
  playerSuffix: MapSlot;
  cells: (string | null)[];
  colors: (string | null)[];
}

export interface MapGroupVersion {
  id: string;
  versionId: string;
  name: string;
  version: number;
  mode: MapGroupMode;
  rows: number;
  cols: number;
  spawns: { A: number; B: number };
  practiceTrials: number;
  formalTrials: number;
  practiceTurnCap: number;
  practiceTurnSeconds: number;
  formalTurnCap: number;
  formalTurnSeconds: number;
  restSeconds: number;
  randomizeFormal: boolean;
  payment: MapGroupPayment;
  profile: TroopProfileRef;
  maps: MapInfo[];
  status: VersionStatus;
  contentHash: string | null;
  publishedAt: string | null;
  createdAt: string;
}

export interface MapGroupSummary {
  id: string;
  versionId: string;
  name: string;
  version: number;
  mode: MapGroupMode;
  rows: number;
  cols: number;
  practiceTrials: number;
  formalTrials: number;
  maps: { slot: MapSlot; name: string; description: string; factorLevel: string }[];
  troopProfile: {
    id: string;
    versionId: string;
    name: string;
    version: number;
    builtIn: boolean;
  };
  payment: MapGroupPayment;
}

export interface InstructionVersion {
  id: string;
  versionId: string;
  name: string;
  version: number;
  role: Role;
  mapGroupPrefix: string;
  minReadingSeconds: number;
  contentMarkdown: string;
  contentHtml: string;
  contentHash: string | null;
  status: VersionStatus;
  publishedAt: string | null;
  createdAt: string;
}

export type QuestionType =
  | "single_choice"
  | "multiple_choice"
  | "likert"
  | "text"
  | "short_text"
  | "number"
  | "real_name"
  | "alipay_phone"
  | "identity_document";

export type ProtectedQuestionType = "real_name" | "alipay_phone" | "identity_document";

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
  maxLength?: number;
  help?: string;
}

export interface IdentityDocumentAnswer {
  documentType: DocumentType;
  number: string;
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
  protectedQuestionIds: string[];
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
  mapGroup: MapGroupSummary;
  instructions: {
    player1: { id: string; name: string; version: number };
    player2: { id: string; name: string; version: number };
  };
  questionnaire: { id: string; name: string; version: number };
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
  role: Role;
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
    role: Role;
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

export interface BulkPaymentRecord {
  paymentId: string;
  participantId: string;
  analysisCode: string | null;
  name: string;
  phone: string;
  roomId: string;
  roomStartsAt: string;
  archiveReason: ArchiveReason | null;
  totalCents: number;
  status: PaymentStatus;
  paidAt: string | null;
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

export interface ConditionVisual {
  color: string | null;
  backgroundAssetId: string | null;
}

export interface TrialParameters {
  initialSoldiersA: number;
  initialSoldiersB: number;
  reinforcementA: number;
  reinforcementB: number;
  sourceIndex: number | null;
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
  role: Role;
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

export interface TrialScores {
  player1: number;
  player2: number;
}

export interface GameState extends TrialParameters {
  phase: "turn" | "rest" | "questionnaire" | string;
  trialIndex: number;
  gameNumber: number;
  totalTrials: number;
  practiceTrials: number;
  formalTrials: number;
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
  finalSoldiers: TrialScores | null;
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
  role: Role | null;
  self: {
    startRequested: boolean;
    instructionCompleted: boolean;
    questionnaireStatus: QuestionnaireStatus | null;
    completedAt: string | null;
    canExit: boolean;
  };
  partner: PartnerState;
  instruction?: InstructionState;
  game?: GameState;
  questionnaire?: { url: string | null; status: QuestionnaireStatus; submitted: boolean };
  archive?: {
    reason: ArchiveReason;
    canRebook: boolean;
    selfExited: boolean;
    selfExitReason: ExitReason | null;
    partnerExitReason: ExitReason | null;
    selfAttended: boolean;
    questionnaireRequired: boolean;
    showupPayCents: number;
    rewardKind: RewardKind;
  };
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
  initialSoldiersA?: number;
  initialSoldiersB?: number;
  reinforcementA?: number;
  reinforcementB?: number;
  sourceIndex?: number | null;
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
  resultDisplayMs?: number;
  nextRound?: number;
  deadline?: string;
  initialSoldiersA?: number;
  initialSoldiersB?: number;
  reinforcementA?: number;
  reinforcementB?: number;
  sourceIndex?: number | null;
}

export interface RestMessage {
  type: "rest";
  roomId: string;
  trialIndex: number;
  round: number;
  completedTrialIndex: number;
  completedIsPractice: boolean;
  completedFormalTrial: number;
  nextTrialIndex: number | null;
  nextIsPractice: boolean | null;
  nextFormalTrial: number | null;
  restSeconds: number;
  formalTrials: number;
  finalSoldiers: TrialScores | null;
  deadline: string | null;
  ready: Record<string, boolean>;
}

export interface TrialStartMessage extends TrialParameters {
  type: "trial_start";
  roomId: string;
  trialIndex: number;
  gameNumber: number;
  totalTrials: number;
  practiceTrials: number;
  formalTrials: number;
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
  | { type: "rest_complete"; roomId: string; trialIndex: number; round: number }
  | { type: "game_over"; roomId: string; trialsCompleted: number; questionnaireUrl: string | null }
  | { type: "questionnaire_required"; roomId: string; url: string | null; status: QuestionnaireStatus }
  | {
      type: "room_archived";
      roomId: string;
      reason: ArchiveReason | null;
      selfExited: boolean;
      selfExitReason: ExitReason | null;
      partnerExitReason: ExitReason | null;
      selfAttended: boolean;
      selfQuestionnaireStatus: QuestionnaireStatus | null;
      selfCompleted: boolean;
      questionnaireRequired: boolean;
      showupPayCents: number;
      canRebook: boolean;
      rewardKind: RewardKind;
    }
  | {
      type: "inactivity_warning";
      roomId: string;
      remainingSeconds: number;
    }
  | { type: "error"; code: string; message: string }
  | { type: "pong"; serverNow: string };
