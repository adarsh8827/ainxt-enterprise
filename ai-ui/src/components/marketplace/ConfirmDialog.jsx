// SPDX-License-Identifier: MIT
// Shared confirmation dialog -- "Delete permanently" (item 1, M5
// UI-polish review) is the first real caller: a hard delete must never
// fire on a single click. Deliberately generic (title/message/confirm
// label only) so any future destructive action reuses this instead of
// growing its own bespoke modal.
//
// Full Tailwind pass (2026-10-03): rewritten to literal Tailwind classes
// (no more Modal.css) -- confirm button is brand-grad/bg-red-600 with
// hover:opacity-70, matching Button.jsx's own primary/danger treatment.
import { useEffect, useRef } from "react";
import { XMarkIcon } from "@heroicons/react/24/outline";
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  danger,
  onConfirm,
  onCancel
}) {
  const confirmRef = useRef(null);
  useEffect(() => {
    if (open) confirmRef.current?.focus();
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const onKeyDown = e => {
      if (e.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onCancel]);
  if (!open) return null;
  return <div data-testid="confirm-dialog-overlay" role="presentation" onClick={onCancel} className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-[1000]">
      <div role="alertdialog" aria-modal="true" aria-labelledby="confirm-dialog-title" aria-describedby="confirm-dialog-message" data-testid="confirm-dialog" onClick={e => e.stopPropagation()} className="bg-white rounded-lg shadow-xl max-w-[360px] w-[90%] overflow-hidden">
        <div className="flex items-start justify-between px-6 pt-6 pb-2">
          <h2 id="confirm-dialog-title" className="m-0 text-base font-semibold text-gray-900">
            {title}
          </h2>
          <button type="button" aria-label="Close" onClick={onCancel} className="inline-flex p-1 ml-2 rounded-md border-none bg-none text-gray-400 hover:bg-gray-100 hover:text-gray-700 cursor-pointer transition-colors">
            <XMarkIcon width={16} height={16} aria-hidden="true" />
          </button>
        </div>
        <p id="confirm-dialog-message" className="m-0 px-6 pb-6 text-sm text-gray-500">
          {message}
        </p>
        <div className="flex justify-end gap-2 px-6 py-4 bg-gray-50 border-t border-gray-200">
          <button type="button" data-testid="confirm-dialog-cancel" onClick={onCancel} className="px-3 py-2 text-sm font-medium rounded-md border border-gray-300 bg-white text-gray-900 hover:bg-gray-100 cursor-pointer transition-colors">
            {cancelLabel}
          </button>
          <button ref={confirmRef} type="button" data-testid="confirm-dialog-confirm" onClick={onConfirm} className={["px-3 py-2 text-sm font-semibold rounded-md border-none text-white cursor-pointer transition-colors hover:opacity-70", danger ? "bg-red-600" : "brand-grad"].join(" ")}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>;
}
