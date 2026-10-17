import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  AlertTriangle,
  CheckCircle2,
  Inbox,
  Info,
  RefreshCw,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type {
  BookingStatus,
  ParticipantStatus,
  PaymentStatus,
  QuestionnaireStatus,
  RoomStatus,
  VersionStatus,
} from "../shared/types";
import {
  BOOKING_STATUS_LABELS,
  PARTICIPANT_STATUS_LABELS,
  PAYMENT_STATUS_LABELS,
  QUESTIONNAIRE_STATUS_LABELS,
  ROOM_STATUS_LABELS,
  VERSION_STATUS_LABELS,
  bookingStatusTone,
  participantStatusTone,
  paymentStatusTone,
  questionnaireStatusTone,
  roomStatusTone,
  versionStatusTone,
} from "./labels";
import type { ChipTone } from "./labels";

type ToastKind = "success" | "error";

interface ToastItem {
  id: number;
  message: string;
  kind: ToastKind;
}

export interface ConfirmOptions {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
}

interface PendingConfirm {
  options: ConfirmOptions;
  resolve: (value: boolean) => void;
}

interface UiContextValue {
  notify: (message: string, kind?: ToastKind) => void;
  confirm: (options: ConfirmOptions) => Promise<boolean>;
}

const UiContext = createContext<UiContextValue | null>(null);

export function useUi(): UiContextValue {
  const value = useContext(UiContext);
  if (value === null) {
    throw new Error("UiProvider 未挂载");
  }
  return value;
}

export function UiProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [pending, setPending] = useState<PendingConfirm | null>(null);
  const nextId = useRef(1);

  const notify = useCallback((message: string, kind: ToastKind = "success") => {
    const id = nextId.current;
    nextId.current += 1;
    setToasts((current) => [...current, { id, message, kind }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((item) => item.id !== id));
    }, 4200);
  }, []);

  const confirm = useCallback((options: ConfirmOptions) => {
    return new Promise<boolean>((resolve) => {
      setPending((current) => {
        current?.resolve(false);
        return { options, resolve };
      });
    });
  }, []);

  const settle = useCallback(
    (value: boolean) => {
      setPending((current) => {
        current?.resolve(value);
        return null;
      });
    },
    [],
  );

  const contextValue = useMemo(() => ({ notify, confirm }), [notify, confirm]);

  return (
    <UiContext.Provider value={contextValue}>
      {children}
      <div className="admin-toast-stack" aria-live="polite" role="status">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`admin-toast${toast.kind === "error" ? " admin-toast-error" : ""}`}
          >
            <span>{toast.message}</span>
            <button
              type="button"
              className="admin-toast-close"
              aria-label="关闭提示"
              onClick={() => setToasts((current) => current.filter((item) => item.id !== toast.id))}
            >
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
      {pending ? (
        <Modal
          title={pending.options.title}
          onClose={() => settle(false)}
          footer={
            <>
              <button type="button" className="admin-btn admin-btn-secondary" onClick={() => settle(false)}>
                {pending.options.cancelLabel ?? "取消"}
              </button>
              <button
                type="button"
                className={`admin-btn ${pending.options.danger ? "admin-btn-danger" : "admin-btn-primary"}`}
                onClick={() => settle(true)}
              >
                {pending.options.confirmLabel ?? "确认"}
              </button>
            </>
          }
        >
          <p className="admin-confirm-message">{pending.options.message}</p>
        </Modal>
      ) : null}
    </UiContext.Provider>
  );
}

export function Modal({
  title,
  children,
  onClose,
  footer,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  footer?: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  return createPortal(
    <div
      className="admin-modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className={`admin-modal${wide ? " admin-modal-wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="admin-modal-head">
          <h2 className="admin-modal-title">{title}</h2>
          <button type="button" className="admin-icon-btn" aria-label="关闭" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        {children}
        {footer ? <div className="admin-modal-actions">{footer}</div> : null}
      </div>
    </div>,
    document.body,
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="admin-page-head">
      <div>
        <h1 className="admin-page-title">{title}</h1>
        {subtitle ? <p className="admin-page-subtitle">{subtitle}</p> : null}
      </div>
      {actions ? <div className="admin-btn-row">{actions}</div> : null}
    </div>
  );
}

export function StatusChip({
  tone = "neutral",
  children,
}: {
  tone?: ChipTone;
  children: ReactNode;
}) {
  return (
    <span className={`admin-chip${tone === "neutral" ? "" : ` admin-chip-${tone}`}`}>{children}</span>
  );
}

export function RoomStatusChip({ status }: { status: RoomStatus }) {
  return <StatusChip tone={roomStatusTone(status)}>{ROOM_STATUS_LABELS[status]}</StatusChip>;
}

export function ParticipantStatusChip({ status }: { status: ParticipantStatus }) {
  return (
    <StatusChip tone={participantStatusTone(status)}>{PARTICIPANT_STATUS_LABELS[status]}</StatusChip>
  );
}

export function BookingStatusChip({ status }: { status: BookingStatus }) {
  return <StatusChip tone={bookingStatusTone(status)}>{BOOKING_STATUS_LABELS[status]}</StatusChip>;
}

export function PaymentStatusChip({ status }: { status: PaymentStatus }) {
  return <StatusChip tone={paymentStatusTone(status)}>{PAYMENT_STATUS_LABELS[status]}</StatusChip>;
}

export function VersionStatusChip({ status }: { status: VersionStatus }) {
  return <StatusChip tone={versionStatusTone(status)}>{VERSION_STATUS_LABELS[status]}</StatusChip>;
}

export function QuestionnaireStatusChip({ status }: { status: QuestionnaireStatus }) {
  return (
    <StatusChip tone={questionnaireStatusTone(status)}>
      {QUESTIONNAIRE_STATUS_LABELS[status]}
    </StatusChip>
  );
}

export function LoadingBlock({ rows = 4, label = "加载中" }: { rows?: number; label?: string }) {
  return (
    <div className="admin-skeleton-block" aria-busy="true" aria-label={label}>
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={index}
          className="admin-skeleton-line"
          style={{ width: `${96 - (index % 3) * 14}%` }}
        />
      ))}
    </div>
  );
}

export function ErrorNotice({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="admin-error-box" role="alert">
      <AlertTriangle size={18} />
      <div className="admin-error-box-body">
        <strong>操作未完成</strong>
        <p>{message}</p>
      </div>
      {onRetry ? (
        <button type="button" className="admin-btn admin-btn-secondary admin-btn-sm" onClick={onRetry}>
          <RefreshCw size={14} />
          重试
        </button>
      ) : null}
    </div>
  );
}

export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
}: {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="admin-empty">
      <Icon size={28} aria-hidden="true" />
      <div className="admin-empty-title">{title}</div>
      {description ? <p className="admin-empty-description">{description}</p> : null}
      {action ? <div className="admin-empty-action">{action}</div> : null}
    </div>
  );
}

export function Field({
  label,
  htmlFor,
  hint,
  error,
  children,
}: {
  label: string;
  htmlFor?: string;
  hint?: string;
  error?: string | null;
  children: ReactNode;
}) {
  return (
    <div className="admin-field">
      <label className="admin-label" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {error ? <div className="admin-error">{error}</div> : null}
      {hint ? <div className="admin-hint">{hint}</div> : null}
    </div>
  );
}

export function InlineNotice({
  tone = "info",
  children,
}: {
  tone?: "info" | "success" | "warning" | "error";
  children: ReactNode;
}) {
  const Icon = tone === "success" ? CheckCircle2 : tone === "error" || tone === "warning" ? AlertTriangle : Info;
  return (
    <div className={`admin-inline-notice admin-inline-notice-${tone}`}>
      <Icon size={16} aria-hidden="true" />
      <div>{children}</div>
    </div>
  );
}

export function Pagination({
  total,
  offset,
  limit,
  onChange,
}: {
  total: number;
  offset: number;
  limit: number;
  onChange: (offset: number) => void;
}) {
  if (total <= limit) {
    return <div className="admin-hint admin-pagination-summary">共 {total} 条</div>;
  }
  const start = total === 0 ? 0 : offset + 1;
  const end = Math.min(offset + limit, total);
  return (
    <div className="admin-pagination">
      <span className="admin-hint">
        第 {start} 至 {end} 条，共 {total} 条
      </span>
      <div className="admin-btn-row">
        <button
          type="button"
          className="admin-btn admin-btn-secondary admin-btn-sm"
          disabled={offset === 0}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          上一页
        </button>
        <button
          type="button"
          className="admin-btn admin-btn-secondary admin-btn-sm"
          disabled={offset + limit >= total}
          onClick={() => onChange(offset + limit)}
        >
          下一页
        </button>
      </div>
    </div>
  );
}

export function JsonDetails({
  value,
  label = "打开 JSON",
}: {
  value: unknown;
  label?: string;
}) {
  return (
    <details className="admin-json-details">
      <summary>{label}</summary>
      <pre className="payload-json">{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export function centsFromYuan(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const amount = Number(trimmed);
  if (!Number.isFinite(amount) || amount < 0) return null;
  return Math.round(amount * 100);
}

export function yuanFromCents(cents: number | null | undefined): string {
  if (cents === null || cents === undefined) return "";
  return (cents / 100).toFixed(2);
}

export function toShanghaiInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const map: Record<string, string> = {};
  for (const part of parts) {
    if (part.type !== "literal") map[part.type] = part.value;
  }
  return `${map.year}-${map.month}-${map.day}T${map.hour}:${map.minute}`;
}

export function fromShanghaiInput(value: string): string {
  return new Date(`${value}:00+08:00`).toISOString();
}

export function nowMs(): number {
  return Date.now();
}

export function sortByPublished<T extends { status: VersionStatus; version: number }>(items: T[]): T[] {
  return [...items].sort((a, b) => {
    if (a.status === "published" && b.status !== "published") return -1;
    if (b.status === "published" && a.status !== "published") return 1;
    return b.version - a.version;
  });
}

export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs]);
  return now;
}
