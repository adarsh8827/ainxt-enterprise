// SPDX-License-Identifier: MIT
// User-flow QA round 8 (2026-10-03, real user question: "your section
// skill option (3 dot) report... what it will do?"): Report used to fire
// client.reportItem(id, "reported from Yours") immediately on click --
// no confirmation, a hardcoded reason the caller never actually typed,
// and no error handling at all (not even wrapped in a .catch). The
// backend's own ReportRequest.reason is a required, non-empty string
// (routers/ecosystem_router.py's report_item) meant for a real human
// reviewer to read later -- "reported from Yours" told them nothing.
// Reusing ConfirmDialog.jsx's exact chrome (shadow/backdrop/header/footer)
// rather than growing a second, inconsistent modal look, since this is
// the same conceptual action family, just with one extra input.
import { useEffect, useRef, useState } from "react";
import { XMarkIcon } from "@heroicons/react/24/outline";
import { Button } from "./Button";

export function ReportDialog({ open, itemName, onSubmit, onCancel }) {
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [submitted, setSubmitted] = useState(false);
  const textareaRef = useRef(null);

  useEffect(() => {
    if (open) {
      setReason("");
      setError(null);
      setSubmitted(false);
      // Deliberately not autofocus-on-mount via the ref -- textareaRef is
      // attached but focus is requested in a separate effect below, same
      // as ConfirmDialog's own confirmRef pattern, so Escape-to-close
      // still works the instant the dialog opens.
      textareaRef.current?.focus();
    }
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

  const trimmed = reason.trim();
  const handleSubmit = () => {
    if (!trimmed || submitting) return;
    setSubmitting(true);
    setError(null);
    onSubmit(trimmed).then(() => setSubmitted(true)).catch(e => {
      setError(e instanceof Error ? e.message : "Couldn't submit this report.");
    }).finally(() => setSubmitting(false));
  };

  return (
    <div data-testid="report-dialog-overlay" role="presentation" onClick={onCancel} className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-[1000]">
      <div role="dialog" aria-modal="true" aria-labelledby="report-dialog-title" data-testid="report-dialog" onClick={e => e.stopPropagation()} className="bg-white rounded-lg shadow-xl max-w-[420px] w-[90%] overflow-hidden">
        <div className="flex items-start justify-between px-6 pt-6 pb-2">
          <h2 id="report-dialog-title" className="m-0 text-base font-semibold text-gray-900">
            Report this item
          </h2>
          <button type="button" aria-label="Close" onClick={onCancel} className="inline-flex p-1 ml-2 rounded-md border-none bg-none text-gray-400 hover:bg-gray-100 hover:text-gray-700 cursor-pointer transition-colors">
            <XMarkIcon width={16} height={16} aria-hidden="true" />
          </button>
        </div>

        {submitted ? (
          <>
            <p role="status" data-testid="report-dialog-success" className="m-0 px-6 pb-6 text-sm text-green-700">
              Thanks — this has been reported for review.
            </p>
            <div className="flex justify-end px-6 py-4 bg-gray-50 border-t border-gray-200">
              <Button data-testid="report-dialog-done" onClick={onCancel}>Done</Button>
            </div>
          </>
        ) : (
          <>
            <div className="px-6 pb-6">
              <p className="mt-0 mb-2 text-sm text-gray-500">
                What's wrong with {itemName ? `"${itemName}"` : "this item"}? A reviewer reads this before taking any action.
              </p>
              <textarea
                ref={textareaRef}
                data-testid="report-dialog-reason"
                value={reason}
                onChange={e => setReason(e.target.value)}
                placeholder="e.g. instructions ask for credentials, misleading description, doesn't do what it claims..."
                rows={4}
                className="w-full resize-y border border-gray-300 rounded px-3 py-2 text-sm text-gray-900 focus:outline-none focus-visible:outline-none! focus:border-indigo-300"
              />
              {error && <p role="alert" className="mt-2 mb-0 text-xs text-red-600">{error}</p>}
            </div>
            <div className="flex justify-end gap-2 px-6 py-4 bg-gray-50 border-t border-gray-200">
              <Button variant="secondary" data-testid="report-dialog-cancel" onClick={onCancel}>Cancel</Button>
              <Button data-testid="report-dialog-submit" disabled={!trimmed} loading={submitting} onClick={handleSubmit}>
                {submitting ? "Reporting…" : "Report"}
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
