import { AlertTriangle, X } from "lucide-react";
import { useEffect, useRef, type KeyboardEvent, type MouseEvent } from "react";
import { createPortal } from "react-dom";

export type ConfirmationDialogRequest = {
  title: string;
  message: string;
  confirmLabel: string;
  cancelLabel?: string;
  details?: string[];
};

type ConfirmationDialogProps = {
  request: ConfirmationDialogRequest;
  onResolve: (confirmed: boolean) => void;
};

export function ConfirmationDialog({ request, onResolve }: ConfirmationDialogProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    cancelRef.current?.focus();
  }, []);

  function handleBackdropMouseDown(event: MouseEvent<HTMLDivElement>) {
    if (event.target === event.currentTarget) {
      onResolve(false);
    }
  }

  function handleDialogKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      onResolve(false);
      return;
    }
    if (event.key !== "Tab") {
      return;
    }
    const first = cancelRef.current;
    const last = confirmRef.current;
    if (!first || !last) {
      return;
    }
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return createPortal(
    <div className="settings-memory-reset-backdrop" onMouseDown={handleBackdropMouseDown}>
      <section
        className="settings-memory-reset-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="app-confirmation-dialog-title"
        aria-describedby="app-confirmation-dialog-description"
        onKeyDown={handleDialogKeyDown}
      >
        <div className="settings-memory-reset-dialog-head">
          <span className="settings-memory-reset-dialog-icon" aria-hidden="true">
            <AlertTriangle size={20} />
          </span>
          <div>
            <strong id="app-confirmation-dialog-title">{request.title}</strong>
            <p id="app-confirmation-dialog-description">{request.message}</p>
          </div>
          <button
            type="button"
            className="secondary settings-memory-reset-dialog-close"
            onClick={() => onResolve(false)}
            aria-label="关闭确认对话框"
          >
            <X size={17} />
          </button>
        </div>

        {request.details?.length ? (
          <ul className="field-note">
            {request.details.map((detail) => <li key={detail}>{detail}</li>)}
          </ul>
        ) : null}

        <div className="settings-memory-reset-dialog-actions">
          <button ref={cancelRef} type="button" className="secondary" onClick={() => onResolve(false)}>
            {request.cancelLabel || "取消"}
          </button>
          <button ref={confirmRef} type="button" className="danger" onClick={() => onResolve(true)}>
            {request.confirmLabel}
          </button>
        </div>
      </section>
    </div>,
    document.body,
  );
}
