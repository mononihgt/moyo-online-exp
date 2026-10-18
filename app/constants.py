SCHEMA_VERSION = 4
CONDITION_SCHEMA_VERSION = 1
TIMEZONE = "Asia/Shanghai"

PARTICIPANT_ELIGIBLE = "eligible"
PARTICIPANT_COMPLETED = "completed"
PARTICIPANT_DISABLED = "disabled"
PARTICIPANT_STATUSES = (PARTICIPANT_ELIGIBLE, PARTICIPANT_COMPLETED, PARTICIPANT_DISABLED)

ROOM_DRAFT = "draft"
ROOM_OPEN = "open"
ROOM_FULL = "full"
ROOM_WAITING = "waiting"
ROOM_INSTRUCTIONS = "instructions"
ROOM_PLAYING = "playing"
ROOM_QUESTIONNAIRE = "questionnaire"
ROOM_ARCHIVED = "archived"
ROOM_STATUSES = (
    ROOM_DRAFT,
    ROOM_OPEN,
    ROOM_FULL,
    ROOM_WAITING,
    ROOM_INSTRUCTIONS,
    ROOM_PLAYING,
    ROOM_QUESTIONNAIRE,
    ROOM_ARCHIVED,
)
ACTIVE_ROOM_STATUSES = (ROOM_WAITING, ROOM_INSTRUCTIONS, ROOM_PLAYING, ROOM_QUESTIONNAIRE)

ARCHIVE_COMPLETED = "completed"
ARCHIVE_NOT_FULL = "not_full"
ARCHIVE_NO_SHOW = "no_show"
ARCHIVE_NO_START = "no_start"
ARCHIVE_ABANDONED = "abandoned"
ARCHIVE_TECHNICAL_ABORT = "technical_abort"
ARCHIVE_QUESTIONNAIRE_INCOMPLETE = "questionnaire_incomplete"
ARCHIVE_ADMIN_CANCELLED = "admin_cancelled"
ARCHIVE_ADMIN_ABORTED = "admin_aborted"
ARCHIVE_REASONS = (
    ARCHIVE_COMPLETED,
    ARCHIVE_NOT_FULL,
    ARCHIVE_NO_SHOW,
    ARCHIVE_NO_START,
    ARCHIVE_ABANDONED,
    ARCHIVE_TECHNICAL_ABORT,
    ARCHIVE_QUESTIONNAIRE_INCOMPLETE,
    ARCHIVE_ADMIN_CANCELLED,
    ARCHIVE_ADMIN_ABORTED,
)

BOOKING_BOOKED = "booked"
BOOKING_CANCELED = "canceled"
BOOKING_ATTENDED = "attended"
BOOKING_NO_SHOW = "no_show"
BOOKING_STATUSES = (BOOKING_BOOKED, BOOKING_CANCELED, BOOKING_ATTENDED, BOOKING_NO_SHOW)

VERSION_DRAFT = "draft"
VERSION_PUBLISHED = "published"
VERSION_ARCHIVED = "archived"
VERSION_STATUSES = (VERSION_DRAFT, VERSION_PUBLISHED, VERSION_ARCHIVED)

QUESTIONNAIRE_NOT_STARTED = "not_started"
QUESTIONNAIRE_IN_PROGRESS = "in_progress"
QUESTIONNAIRE_COMPLETED = "completed"

PAYMENT_PENDING = "pending"
PAYMENT_PAID = "paid"
PAYMENT_STATUSES = (PAYMENT_PENDING, PAYMENT_PAID)

ROLE_PLAYER_1 = 1
ROLE_PLAYER_2 = 2
ROLES = (ROLE_PLAYER_1, ROLE_PLAYER_2)

SELECTION_MANUAL = "manual"
SELECTION_TIMEOUT = "timeout"
SELECTION_FORCED = "forced"

END_REASON_ANNIHILATION = "annihilation"
END_REASON_TURN_LIMIT = "turn_limit"

PHASE_WAITING = "waiting"
PHASE_INSTRUCTIONS = "instructions"
PHASE_TURN = "turn"
PHASE_REST = "rest"
PHASE_QUESTIONNAIRE = "questionnaire"

EVENT_TYPES = (
    "room_published",
    "booking_created",
    "booking_canceled",
    "participant_entered",
    "start_matching",
    "partner_absent",
    "participant_exited",
    "role_assigned",
    "config_locked",
    "instruction_started",
    "instruction_completed",
    "game_started",
    "trial_started",
    "turn_resolved",
    "disconnect",
    "reconnect",
    "server_restart",
    "game_completed",
    "questionnaire_started",
    "questionnaire_completed",
    "payment_computed",
    "payment_paid",
    "room_archived",
    "admin_action",
)
