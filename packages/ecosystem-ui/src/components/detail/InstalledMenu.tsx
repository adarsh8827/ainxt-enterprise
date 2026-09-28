// SPDX-License-Identifier: MIT
// Item 2 (M5 UI-polish round): replaces Detail.tsx's old kebab-icon +
// separate visible ToggleSwitch pair with a single labeled "Installed ▾"
// control, matching this project's own reference mock
// (docs/ecosystem/claude_ui_refs/ainxt_customize_mock.html's own
// installedPop()): Manage in Yours, Enable/Disable, Versions & rollback,
// a divider, then Uninstall -- locked with an explanatory note instead of
// hidden outright when the install's own scope is "required" (the mock's
// own "Required (can't remove)" pattern; matches the real server-side
// refusal already enforced in installs_service.uninstall()).
//
// Item 1 ("Delete permanently" review, 2026-09-28): a private item the
// caller owns, with no other install/share anywhere, additionally gets a
// "Delete permanently" entry here (this same component is reused
// verbatim by Detail.tsx, so this single change covers both the
// "Installed ▾ menu" AND "detail page" requirements at once). When the
// item IS shared/installed elsewhere, no hard delete is offered -- a
// short note plus "Retire" (server-side: deprecate) and, if this
// specific install is itself a share, "Unshare" instead. Confirmation
// (a real destructive action) is the CALLER's responsibility (Yours.tsx/
// Detail.tsx each wrap onDeletePermanently/onRetire in a ConfirmDialog)
// -- this component only renders the menu item and forwards the click.
import { useRef, useState } from "react";
import { ChevronDownIcon } from "@heroicons/react/24/outline";
import { PopoverAnchor } from "../PopoverAnchor";
import { MenuItem } from "../KebabMenu";

export function InstalledMenu({
  enabled, required, onManageInYours, onToggleEnabled, onViewVersions, onUninstall, disabled,
  canDeleteDraft, hasOtherInstalls, canDeprecate, canUnshare,
  onDeletePermanently, onRetire, onUnshare, compact,
}: {
  enabled: boolean;
  required: boolean;
  /** Omitted when this menu is rendered from Yours itself (2026-09-27,
   * item 5) -- "Manage in Yours" makes no sense as an action on the
   * screen you're already on. */
  onManageInYours?: () => void;
  onToggleEnabled: (next: boolean) => void;
  onViewVersions: () => void;
  onUninstall: () => void;
  disabled?: boolean;
  /** allowed_actions.includes("delete_draft") -- private, owned, no
   * other install/share exists anywhere. */
  canDeleteDraft?: boolean;
  /** ItemSummary.has_other_installs -- some install other than the
   * caller's own exists. Only meaningful when canDeleteDraft is false;
   * distinguishes "shared/installed elsewhere, offer Retire+Unshare
   * instead" from "not owner/built-in/required, offer nothing." */
  hasOtherInstalls?: boolean;
  /** allowed_actions.includes("deprecate") */
  canDeprecate?: boolean;
  /** allowed_actions.includes("unshare") -- true only for a share the
   * caller can revoke, not "this item happens to be shared with someone
   * else too." */
  canUnshare?: boolean;
  onDeletePermanently?: () => void;
  onRetire?: () => void;
  onUnshare?: () => void;
  /** Card-footer context (Yours.tsx grid mode, alongside Discover's own
   * "+ Add" QuickAddButton) needs this trigger to render at the EXACT
   * same padding/font-size/border-radius/line-height as that button --
   * a real bug found live had "Installed ▾" noticeably larger than
   * "+ Add" once an item got installed, an inconsistent size swap in the
   * same footer slot. Detail.tsx's header keeps the roomier default
   * (omit this prop there -- a page-header action can afford to be
   * bigger, and nothing flagged that size as wrong). */
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const showDelete = canDeleteDraft && onDeletePermanently;
  const showRetireFallback = !canDeleteDraft && hasOtherInstalls && ((canDeprecate && onRetire) || (canUnshare && onUnshare));

  return (
    <div style={{ position: "relative" }}>
      <button
        ref={triggerRef}
        type="button"
        data-testid="detail-installed-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        style={
          compact
            ? {
                // Exactly QuickAddButton's own box model (Card.tsx) --
                // same padding/font-size/line-height/border-radius/
                // border-width/box-sizing/gap, so the footer slot never
                // visibly changes size when an item flips from "+ Add" to
                // "Installed ▾". Border color (not width) is the only
                // deliberate difference -- a visible neutral border here
                // vs. Add's transparent one.
                boxSizing: "border-box",
                display: "inline-flex", alignItems: "center", gap: "4px",
                fontSize: "var(--eco-font-sizeXs)", lineHeight: "16px",
                padding: "2px 8px", borderRadius: "var(--eco-radius-full)",
                border: "1px solid var(--eco-color-border)",
                background: "var(--eco-color-bg)", color: "var(--eco-color-textPrimary)",
                cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.6 : 1,
              }
            : {
                display: "inline-flex", alignItems: "center", gap: "4px", padding: "8px 12px",
                borderRadius: "var(--eco-radius-md)", border: "1px solid var(--eco-color-border)",
                background: "var(--eco-color-bg)", color: "var(--eco-color-textPrimary)",
                cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.6 : 1,
              }
        }
      >
        Installed <ChevronDownIcon width={compact ? 12 : 14} height={compact ? 12 : 14} aria-hidden="true" />
      </button>
      <PopoverAnchor anchorRef={triggerRef} open={open} align="right" onRequestClose={() => setOpen(false)}>
        <div
          role="menu"
          data-testid="detail-installed-menu"
          style={{
            minWidth: "200px",
            background: "var(--eco-color-bg)", border: "1px solid var(--eco-color-border)",
            borderRadius: "var(--eco-radius-md)", boxShadow: "0 4px 12px var(--eco-color-overlay)",
          }}
          onMouseLeave={() => setOpen(false)}
        >
          {onManageInYours && (
            <MenuItem label="Manage in Yours" onSelect={() => { onManageInYours(); setOpen(false); }} />
          )}
          <MenuItem label={enabled ? "Disable" : "Enable"} onSelect={() => { onToggleEnabled(!enabled); setOpen(false); }} />
          <MenuItem label="Versions & rollback" onSelect={() => { onViewVersions(); setOpen(false); }} />
          <div style={{ borderTop: "1px solid var(--eco-color-border)" }} />
          {required ? (
            <MenuItem label="Required" disabled note="Required by your admin. It can't be removed." />
          ) : (
            <MenuItem label="Uninstall" danger onSelect={() => { onUninstall(); setOpen(false); }} />
          )}
          {showDelete && (
            <MenuItem
              label="Delete permanently"
              danger
              onSelect={() => { onDeletePermanently!(); setOpen(false); }}
            />
          )}
          {showRetireFallback && (
            <>
              <div style={{ borderTop: "1px solid var(--eco-color-border)" }} />
              <div
                data-testid="detail-installed-menu-retire-note"
                style={{ padding: "8px 12px 0", fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-textMuted)" }}
              >
                Shared with or installed by others, so it can&apos;t be deleted.
              </div>
              {canDeprecate && onRetire && (
                <MenuItem label="Retire" onSelect={() => { onRetire(); setOpen(false); }} />
              )}
              {canUnshare && onUnshare && (
                <MenuItem label="Unshare" onSelect={() => { onUnshare(); setOpen(false); }} />
              )}
            </>
          )}
        </div>
      </PopoverAnchor>
    </div>
  );
}
