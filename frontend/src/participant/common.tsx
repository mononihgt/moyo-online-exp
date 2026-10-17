import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Hash, Mail, RefreshCw } from "lucide-react";

export function StatusChip({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "success" | "warning" | "error";
}) {
  const className =
    tone === "success"
      ? "p-chip p-chip-success"
      : tone === "warning"
        ? "p-chip p-chip-warning"
        : tone === "error"
          ? "p-chip p-chip-error"
          : "p-chip";
  return <span className={className}>{children}</span>;
}

export function LoadingCard({ text = "正在加载…" }: { text?: string }) {
  return (
    <div className="p-card p-empty" role="status">
      {text}
    </div>
  );
}

export function ErrorCard({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="p-card">
      <div className="p-banner p-banner-error" role="alert">
        {message}
      </div>
      {onRetry ? (
        <button type="button" className="p-btn p-btn-secondary" onClick={onRetry}>
          <RefreshCw size={16} aria-hidden="true" />
          重试
        </button>
      ) : null}
    </div>
  );
}

export function SubpageHeader({
  title,
  description,
  backTo = "/",
  backLabel = "返回首页",
}: {
  title: string;
  description?: string;
  backTo?: string;
  backLabel?: string;
}) {
  return (
    <header className="p-subpage-header">
      <Link className="p-nav-link" to={backTo}>
        <ArrowLeft size={16} aria-hidden="true" />
        {backLabel}
      </Link>
      <h1 className="p-title">{title}</h1>
      {description ? <p className="p-subtitle">{description}</p> : null}
    </header>
  );
}

export function PageLinks({
  items,
}: {
  items: ("home" | "history" | "contact")[];
}) {
  return (
    <div className="p-footer-links">
      {items.includes("home") ? <Link to="/">返回首页</Link> : null}
      {items.includes("history") ? (
        <Link to="/history">
          <Hash size={14} aria-hidden="true" />
          历史实验
        </Link>
      ) : null}
      {items.includes("contact") ? (
        <Link to="/contact">
          <Mail size={14} aria-hidden="true" />
          联系主试
        </Link>
      ) : null}
    </div>
  );
}
