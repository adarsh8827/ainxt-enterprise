// SPDX-License-Identifier: MIT
// Task F-6: renders ONLY from the server-provided allowed_actions array --
// never inferring an action's availability from any other field
// client-side (F-6's own test requirement). One label/handler pair per
// AllowedAction value this menu is able to trigger from Yours.
import { useState } from "react";
import type { AllowedAction } from "../types";

export interface KebabMenuAction {
  action: AllowedAction;
  label: string;
  onSelect: () => void;
  danger?: boolean;
}

const ACTION_LABELS: Partial<Record<AllowedAction, string>> = {
  enable: "Enable", disable: "Disable", share: "Share", unshare: "Unshare",
  update: "Update", rollback: "Roll back", report: "Report",
  deprecate: "Deprecate", delete_draft: "Delete draft", uninstall: "Uninstall",
};

/** Filters `allowedActions` down to the subset this menu knows how to
 * render, in a stable order, pairing each with its handler. */
export function buildKebabActions(
  allowedActions: AllowedAction[],
  handlers: Partial<Record<AllowedAction, () => void>>,
): KebabMenuAction[] {
  const order: AllowedAction[] = ["enable", "disable", "share", "unshare", "update", "rollback", "report", "deprecate", "delete_draft", "uninstall"];
  return order
    .filter((action) => allowedActions.includes(action) && handlers[action])
    .map((action) => ({
      action, label: ACTION_LABELS[action] ?? action, onSelect: handlers[action]!,
      danger: action === "delete_draft" || action === "uninstall",
    }));
}

export function KebabMenu({ onOpenItem, actions }: { onOpenItem?: () => void; actions: KebabMenuAction[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ position: "relative" }}>
      <button
        type="button"
        data-testid="kebab-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="More actions"
        onClick={() => setOpen((o) => !o)}
        style={{ background: "none", border: "none", cursor: "pointer", color: "var(--eco-color-textSecondary)", fontSize: "18px", padding: "4px 8px" }}
      >
        {"⋮"}
      </button>
      {open && (
        <div
          role="menu"
          data-testid="kebab-menu"
          style={{
            position: "absolute", right: 0, top: "100%", zIndex: 10, minWidth: "160px",
            background: "var(--eco-color-bg)", border: "1px solid var(--eco-color-border)",
            borderRadius: "var(--eco-radius-md)", boxShadow: "0 4px 12px var(--eco-color-overlay)",
          }}
          onMouseLeave={() => setOpen(false)}
        >
          {onOpenItem && (
            <MenuItem label="Open" onSelect={() => { onOpenItem(); setOpen(false); }} />
          )}
          {actions.map((a) => (
            <MenuItem key={a.action} label={a.label} danger={a.danger} onSelect={() => { a.onSelect(); setOpen(false); }} />
          ))}
        </div>
      )}
    </div>
  );
}

function MenuItem({ label, onSelect, danger }: { label: string; onSelect: () => void; danger?: boolean }) {
  return (
    <button
      type="button"
      role="menuitem"
      data-testid="kebab-menu-item"
      onClick={onSelect}
      style={{
        display: "block", width: "100%", textAlign: "left", padding: "8px 12px",
        background: "none", border: "none", cursor: "pointer", fontSize: "var(--eco-font-sizeSm)",
        color: danger ? "var(--eco-color-danger)" : "var(--eco-color-textPrimary)",
      }}
    >
      {label}
    </button>
  );
}
