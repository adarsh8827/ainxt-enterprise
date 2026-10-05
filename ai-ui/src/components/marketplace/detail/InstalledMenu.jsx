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
import { ChevronDownIcon, CheckIcon } from "@heroicons/react/24/outline";
import { PopoverAnchor } from "../PopoverAnchor";
import { MenuItem } from "../KebabMenu";
export function InstalledMenu({
  enabled,
  required,
  managedByPlugin,
  managedByPluginName,
  onManageInYours,
  onToggleEnabled,
  onViewVersions,
  onUninstall,
  disabled,
  canDeleteDraft,
  hasOtherInstalls,
  canDeprecate,
  canUnshare,
  onDeletePermanently,
  onRetire,
  onUnshare,
  // Card density pass (2026-10-05, explicit product ask: "a tick to show
  // installed in right corner how claude having... no need to have a big
  // button"): a small circular checkmark replaces the "Installed ▾"
  // text+chevron button, for grid-card usage ONLY -- Yours.jsx's grid rows
  // pass this; Detail.tsx's own header (a full page, not a dense card)
  // keeps the original control untouched, default false. Same popover
  // menu either way -- this only changes the trigger's own appearance.
  // Deliberately does NOT revisit the EARLIER "standard control size"
  // decision (Yours.test.jsx's own regression test, Item 4 2026-09-28) --
  // that was about shrinking the TEXT button to a tiny font; this is a
  // different, explicitly-requested paradigm (icon instead of text),
  // requested fresh in this round.
  iconOnly = false
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef(null);
  const showDelete = canDeleteDraft && onDeletePermanently;
  const showRetireFallback = !canDeleteDraft && hasOtherInstalls && (canDeprecate && onRetire || canUnshare && onUnshare);
  return <div className="relative">
      {iconOnly ? <button ref={triggerRef} type="button" data-testid="detail-installed-trigger" aria-haspopup="menu" aria-expanded={open} aria-label="Installed — manage" title="Installed" disabled={disabled} onClick={() => setOpen(o => !o)} className={["inline-flex items-center justify-center w-7 h-7 rounded-full transition-colors flex-shrink-0", disabled ? "opacity-60 cursor-default bg-gray-100 text-gray-400" : "bg-green-50 text-green-600 hover:bg-green-100 cursor-pointer"].join(" ")}>
          <CheckIcon width={15} height={15} aria-hidden="true" />
          <span className="sr-only">Installed</span>
        </button> :
    // Theme-alignment pass (2026-10-05, explicit product ask: "Installed
    // button on detailed page is too big, need to have aligned with
    // theme, take a ref from Products.jsx, knowledgebase"): was
    // `px-3 py-2` with NO font-size class at all (inherits the browser's
    // ~16px default -- larger than every other control in the app,
    // including this package's own `text-sm`/`text-xs` controls). Matched
    // to ProductManager.jsx's own bordered secondary-button convention
    // (its Edit/Delete buttons: `px-3 py-1.5 text-sm`, icon size 12) --
    // NOT a repeat of the earlier (2026-09-28) "don't shrink to a tiny
    // XS-font pill" mistake this file's own iconOnly comment already
    // documents: `py-1.5`/`text-sm` is still a real, substantial standard
    // control, just correctly sized to the app's actual theme instead of
    // this package's own larger invented default.
    <button ref={triggerRef} type="button" data-testid="detail-installed-trigger" aria-haspopup="menu" aria-expanded={open} disabled={disabled} onClick={() => setOpen(o => !o)} className={["inline-flex items-center gap-1 px-3 py-1.5 rounded-md border border-gray-300 bg-white text-gray-900 text-sm transition-colors", disabled ? "opacity-60 cursor-default" : "hover:bg-gray-100 cursor-pointer"].join(" ")}>
          Installed <ChevronDownIcon width={12} height={12} aria-hidden="true" />
        </button>}
      <PopoverAnchor anchorRef={triggerRef} open={open} align="right" onRequestClose={() => setOpen(false)}>
        <div role="menu" data-testid="detail-installed-menu" className="min-w-[200px] bg-white border border-gray-200 rounded-md shadow-md" onMouseLeave={() => setOpen(false)}>
          {onManageInYours && <MenuItem label="Manage in Yours" onSelect={() => {
          onManageInYours();
          setOpen(false);
        }} />}
          {/* BUG-04 fix: the Uninstall item just below already locks itself
              behind `required` -- this one never did, so a required
              install's "Disable" stayed live and clickable, failing late
              with a raw backend message (and an exposed internal install
              UUID) instead of being locked up front like Uninstall is. */}
          {required ? <MenuItem label="Disable" disabled note="Required by your admin. It can't be disabled." /> : <MenuItem label={enabled ? "Disable" : "Enable"} onSelect={() => {
          onToggleEnabled(!enabled);
          setOpen(false);
        }} />}
          <MenuItem label="Versions & rollback" onSelect={() => {
          onViewVersions();
          setOpen(false);
        }} />
          <div className="border-t border-gray-200" />
          {required ? <MenuItem label="Required" disabled note="Required by your admin. It can't be removed." /> : managedByPlugin ? <MenuItem label="Uninstall" disabled note={managedByPluginName ? `Managed by the "${managedByPluginName}" plugin. Uninstall the plugin instead.` : "Managed by a plugin. Uninstall the plugin instead."} /> : <MenuItem label="Uninstall" danger onSelect={() => {
          onUninstall();
          setOpen(false);
        }} />}
          {showDelete && <MenuItem label="Delete permanently" danger onSelect={() => {
          onDeletePermanently();
          setOpen(false);
        }} />}
          {showRetireFallback && <>
              <div className="border-t border-gray-200" />
              <div data-testid="detail-installed-menu-retire-note" className="px-3 pt-2 text-xs text-gray-400">
                Shared with or installed by others, so it can&apos;t be deleted.
              </div>
              {canDeprecate && onRetire && <MenuItem label="Retire" onSelect={() => {
            onRetire();
            setOpen(false);
          }} />}
              {canUnshare && onUnshare && <MenuItem label="Unshare" onSelect={() => {
            onUnshare();
            setOpen(false);
          }} />}
            </>}
        </div>
      </PopoverAnchor>
    </div>;
}