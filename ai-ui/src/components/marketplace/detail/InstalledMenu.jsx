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
  onUnshare
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef(null);
  const showDelete = canDeleteDraft && onDeletePermanently;
  const showRetireFallback = !canDeleteDraft && hasOtherInstalls && (canDeprecate && onRetire || canUnshare && onUnshare);
  return <div className="relative">
      <button ref={triggerRef} type="button" data-testid="detail-installed-trigger" aria-haspopup="menu" aria-expanded={open} disabled={disabled} onClick={() => setOpen(o => !o)} className={["inline-flex items-center gap-1 px-3 py-2 rounded-md border border-gray-300 bg-white text-gray-900 transition-colors", disabled ? "opacity-60 cursor-default" : "hover:bg-gray-100 cursor-pointer"].join(" ")}>
        Installed <ChevronDownIcon width={14} height={14} aria-hidden="true" />
      </button>
      <PopoverAnchor anchorRef={triggerRef} open={open} align="right" onRequestClose={() => setOpen(false)}>
        <div role="menu" data-testid="detail-installed-menu" className="min-w-[200px] bg-white border border-gray-200 rounded-md shadow-md" onMouseLeave={() => setOpen(false)}>
          {onManageInYours && <MenuItem label="Manage in Yours" onSelect={() => {
          onManageInYours();
          setOpen(false);
        }} />}
          <MenuItem label={enabled ? "Disable" : "Enable"} onSelect={() => {
          onToggleEnabled(!enabled);
          setOpen(false);
        }} />
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