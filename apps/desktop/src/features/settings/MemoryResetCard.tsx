import { AlertTriangle, Loader2, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import { createPortal } from "react-dom";

type MemoryResetCardProps = {
  resetting: boolean;
  onReset: () => void;
};

export function MemoryResetCard({ resetting, onReset }: MemoryResetCardProps) {
  const [confirmationOpen, setConfirmationOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (confirmationOpen) {
      cancelRef.current?.focus();
    }
  }, [confirmationOpen]);

  function closeConfirmation() {
    setConfirmationOpen(false);
    window.setTimeout(() => triggerRef.current?.focus(), 0);
  }

  function confirmReset() {
    setConfirmationOpen(false);
    onReset();
  }

  function handleBackdropMouseDown(event: MouseEvent<HTMLDivElement>) {
    if (event.target === event.currentTarget) {
      closeConfirmation();
    }
  }

  function handleDialogKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeConfirmation();
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

  const confirmationDialog = confirmationOpen && typeof document !== "undefined"
    ? createPortal(
        <div className="settings-memory-reset-backdrop" onMouseDown={handleBackdropMouseDown}>
          <section
            className="settings-memory-reset-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="memory-reset-dialog-title"
            aria-describedby="memory-reset-dialog-description"
            onKeyDown={handleDialogKeyDown}
          >
            <div className="settings-memory-reset-dialog-head">
              <span className="settings-memory-reset-dialog-icon" aria-hidden="true">
                <AlertTriangle size={20} />
              </span>
              <div>
                <strong id="memory-reset-dialog-title">确认重置记忆？</strong>
                <p id="memory-reset-dialog-description">此操作不可恢复，完成后应用会回到没有个人记忆的状态。</p>
              </div>
              <button type="button" className="secondary settings-memory-reset-dialog-close" onClick={closeConfirmation} aria-label="关闭确认弹窗">
                <X size={17} />
              </button>
            </div>

            <dl className="settings-memory-reset-impact">
              <div>
                <dt>将清空</dt>
                <dd>聊天、日记、长期记忆、画像、连续性和记忆活动记录。</dd>
              </div>
              <div className="safe">
                <dt>仍会保留</dt>
                <dd>LLM 与 Embedding 配置、API 密钥、自动化设置、任务、保存位置和 Vault 文件。</dd>
              </div>
            </dl>

            <div className="settings-memory-reset-dialog-actions">
              <button ref={cancelRef} type="button" className="secondary" onClick={closeConfirmation}>
                取消
              </button>
              <button ref={confirmRef} type="button" className="danger" onClick={confirmReset}>
                <Trash2 size={16} />
                确认重置记忆
              </button>
            </div>
          </section>
        </div>,
        document.body,
      )
    : null;

  return (
    <section className="settings-card settings-memory-reset-card" aria-label="重置记忆">
      <div className="section-heading">
        <strong>重置记忆</strong>
        <span>清空测试产生的聊天、日记、长期记忆、画像、连续性和记忆活动记录。</span>
      </div>
      <div className="settings-memory-reset-body">
        <p className="field-note">
          会保留 LLM 与 Embedding 配置、API 密钥、自动化设置、任务、保存位置和 Vault 文件。此操作不可恢复，请确认后执行。
        </p>
        <button
          ref={triggerRef}
          type="button"
          className="danger"
          onClick={() => setConfirmationOpen(true)}
          disabled={resetting}
        >
          {resetting ? <Loader2 className="spin" size={16} /> : <Trash2 size={16} />}
          {resetting ? "正在重置记忆" : "重置记忆"}
        </button>
      </div>
      {confirmationDialog}
    </section>
  );
}
