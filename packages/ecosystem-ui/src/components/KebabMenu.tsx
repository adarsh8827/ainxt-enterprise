// SPDX-License-Identifier: MIT
// Task F-6: renders ONLY from the server-provided allowed_actions array --
// never inferring an action's availability from any other field
// client-side (F-6's own test requirement). One label/handler pair per
// AllowedAction value this menu is able to trigger from Yours.
import { useRef, useState } from "react";
import { EllipsisVerticalIcon } from "@heroicons/react/24/outline";
import type { AllowedAction } from "../types";
import { PopoverAnchor } from "./PopoverAnchor";

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
  const triggerRef = useRef<HTMLButtonElement>(null);
  return (
    <div style={{ position: "relative" }}>
      <button
        ref={triggerRef}
        type="button"
        data-testid="kebab-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="More actions"
        onClick={() => setOpen((o) => !o)}
        style={{ display: "inline-flex", background: "none", border: "none", cursor: "pointer", color: "var(--eco-color-textSecondary)", padding: "4px 8px" }}
      >
        <EllipsisVerticalIcon width={18} height={18} aria-hidden="true" />
      </button>
      <PopoverAnchor anchorRef={triggerRef} open={open} align="right" onRequestClose={() => setOpen(false)}>
        <div
          role="menu"
          data-testid="kebab-menu"
          style={{
            minWidth: "160px",
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
      </PopoverAnchor>
    </div>
  );
}

/** Exported so detail/InstalledMenu.tsx (a differently-triggered popover
 * needing the same menu-item look) doesn't duplicate this styling. */
export function MenuItem({ label, onSelect, danger, disabled, note }: {
  label: string; onSelect?: () => void; danger?: boolean; disabled?: boolean; note?: string;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      data-testid="kebab-menu-item"
      disabled={disabled}
      title={note}
      onClick={disabled ? undefined : onSelect}
      style={{
        display: "block", width: "100%", textAlign: "left", padding: "8px 12px",
        background: "none", border: "none", cursor: disabled ? "default" : "pointer",
        fontSize: "var(--eco-font-sizeSm)",
        color: disabled ? "var(--eco-color-textMuted)" : danger ? "var(--eco-color-danger)" : "var(--eco-color-textPrimary)",
      }}
    >
      {label}
      {note && <div style={{ fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-textMuted)", marginTop: "2px" }}>{note}</div>}
    </button>
  );
}
