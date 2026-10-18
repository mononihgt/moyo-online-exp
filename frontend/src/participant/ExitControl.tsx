import { useEffect, useId, useState } from "react";

import {
  EXIT_BUTTON,
  EXIT_CONFIRM,
  EXIT_CONTINUE,
  EXIT_DETAIL,
  EXIT_TITLE,
} from "./flowCopy";

export function ExitControl({
  onConfirm,
  disabled = false,
  className = "",
}: {
  onConfirm: () => void;
  disabled?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    if (!open) return;
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [open]);

  return (
    <>
      <button
        type="button"
        className={`exp-exit-link${className === "" ? "" : ` ${className}`}`}
        data-testid="exit-experiment"
        disabled={disabled}
        onClick={() => setOpen(true)}
      >
        {EXIT_BUTTON}
      </button>
      {open ? (
        <div className="exp-modal-backdrop" role="presentation">
          <div
            className="exp-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            aria-describedby={descriptionId}
          >
            <h2 className="p-title-sm" id={titleId}>
              {EXIT_TITLE}
            </h2>
            <p className="p-muted" id={descriptionId}>
              {EXIT_DETAIL}
            </p>
            <div className="p-btn-row exp-modal-actions">
              <button
                type="button"
                className="p-btn p-btn-quiet"
                data-testid="exit-cancel"
                autoFocus
                onClick={() => setOpen(false)}
              >
                {EXIT_CONTINUE}
              </button>
              <button
                type="button"
                className="p-btn p-btn-danger"
                data-testid="exit-confirm"
                disabled={disabled}
                onClick={() => {
                  setOpen(false);
                  onConfirm();
                }}
              >
                {EXIT_CONFIRM}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
