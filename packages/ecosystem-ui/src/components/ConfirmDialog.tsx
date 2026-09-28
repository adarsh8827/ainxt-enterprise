// SPDX-License-Identifier: MIT
// Shared confirmation dialog -- "Delete permanently" (item 1, M5
// UI-polish review) is the first real caller: a hard delete must never
// fire on a single click. Deliberately generic (title/message/confirm
// label only) so any future destructive action reuses this instead of
// growing its own bespoke modal.
import { useEffect, useRef } from "react";

export function ConfirmDialog({
  open, title, message, confirmLabel = "Confirm", cancelLabel = "Cancel", danger, onConfirm, onCancel,
}: {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (open) confirmRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div
      data-testid="confirm-dialog-overlay"
      role="presentation"
      onClick={onCancel}
      style={{
        position: "fixed", inset: 0, background: "var(--eco-color-overlay)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
      }}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-message"
        data-testid="confirm-dialog"
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--eco-color-bg)", border: "1px solid var(--eco-color-border)",
          borderRadius: "var(--eco-radius-md)", boxShadow: "0 8px 24px var(--eco-color-overlay)",
          padding: "var(--eco-space-lg)", maxWidth: "360px", width: "90%",
        }}
      >
        <h2 id="confirm-dialog-title" style={{ margin: 0, fontSize: "var(--eco-font-sizeMd)", color: "var(--eco-color-textPrimary)" }}>
          {title}
        </h2>
        <p id="confirm-dialog-message" style={{ margin: "var(--eco-space-sm) 0 var(--eco-space-lg)", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)" }}>
          {message}
        </p>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: "var(--eco-space-sm)" }}>
          <button
            type="button"
            data-testid="confirm-dialog-cancel"
            onClick={onCancel}
            style={{
              padding: "8px 12px", borderRadius: "var(--eco-radius-md)", border: "1px solid var(--eco-color-border)",
              background: "var(--eco-color-bg)", color: "var(--eco-color-textPrimary)", cursor: "pointer",
            }}
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            type="button"
            data-testid="confirm-dialog-confirm"
            onClick={onConfirm}
            style={{
              padding: "8px 12px", borderRadius: "var(--eco-radius-md)", border: "none",
              background: danger ? "var(--eco-color-danger)" : "var(--eco-color-accentSkill)",
              color: "var(--eco-color-bg)", cursor: "pointer", fontWeight: 600,
            }}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
