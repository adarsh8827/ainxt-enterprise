// SPDX-License-Identifier: MIT
// Task F-6: renders ONLY from the server-provided allowed_actions array --
// never inferring an action's availability from any other field
// client-side (F-6's own test requirement). One label/handler pair per
// AllowedAction value this menu is able to trigger from Yours.
import { useRef, useState } from "react";
import { EllipsisVerticalIcon } from "@heroicons/react/24/outline";
import { PopoverAnchor } from "./PopoverAnchor";
const ACTION_LABELS = {
  enable: "Enable",
  disable: "Disable",
  // "share" intentionally omitted (user-flow QA round, 2026-10-03): no
  // caller anywhere in this package has ever supplied a `share` handler
  // (confirmed: client.share() is never invoked from any component), so
  // this entry was permanently unreachable dead weight -- buildKebabActions
  // already filters by `handlers[action]` being present, so it never
  // actually rendered, but keeping the label/order entry around implied a
  // working UI path that doesn't exist. The backend endpoint itself works
  // fine (verified directly over the API) -- only a UI entry point is
  // missing. Re-add both this label and "share" in the `order` array below
  // once a real Share UI (e.g. a ShareDialog picking a user/org) exists and
  // wires an onSelect handler through from Yours.tsx/Detail.tsx.
  unshare: "Unshare",
  update: "Update",
  rollback: "Roll back",
  report: "Report",
  deprecate: "Retire",
  delete_draft: "Delete permanently",
  uninstall: "Uninstall"
};

/** Filters `allowedActions` down to the subset this menu knows how to
 * render, in a stable order, pairing each with its handler. */
export function buildKebabActions(allowedActions, handlers) {
  // "share" deliberately excluded here too -- see ACTION_LABELS comment above.
  const order = ["enable", "disable", "unshare", "update", "rollback", "report", "deprecate", "delete_draft", "uninstall"];
  return order.filter(action => allowedActions.includes(action) && handlers[action]).map(action => ({
    action,
    label: ACTION_LABELS[action] ?? action,
    onSelect: handlers[action],
    danger: action === "delete_draft" || action === "uninstall"
  }));
}
export function KebabMenu({
  onOpenItem,
  actions,
  infoLines
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef(null);
  return <div className="relative">
      <button ref={triggerRef} type="button" data-testid="kebab-trigger" aria-haspopup="menu" aria-expanded={open} aria-label="More actions" onClick={() => setOpen(o => !o)} className="inline-flex bg-none border-none cursor-pointer text-gray-500 hover:text-gray-700 px-2 py-1 rounded transition-colors">
        <EllipsisVerticalIcon width={18} height={18} aria-hidden="true" />
      </button>
      <PopoverAnchor anchorRef={triggerRef} open={open} align="right" onRequestClose={() => setOpen(false)}>
        <div role="menu" data-testid="kebab-menu" className="min-w-[160px] bg-white border border-gray-200 rounded-md shadow-md" onMouseLeave={() => setOpen(false)}>
          {onOpenItem && <MenuItem label="Open" onSelect={() => {
          onOpenItem();
          setOpen(false);
        }} />}
          {infoLines && infoLines.length > 0 && <>
              {infoLines.map(line => <MenuItem key={line} label={line} disabled />)}
              <div className="border-t border-gray-200" />
            </>}
          {actions.map(a => <MenuItem key={a.action} label={a.label} danger={a.danger} onSelect={() => {
          a.onSelect();
          setOpen(false);
        }} />)}
        </div>
      </PopoverAnchor>
    </div>;
}

/** Exported so detail/InstalledMenu.tsx (a differently-triggered popover
 * needing the same menu-item look) doesn't duplicate this styling. */
export function MenuItem({
  label,
  onSelect,
  danger,
  disabled,
  note
}) {
  return <button type="button" role="menuitem" data-testid="kebab-menu-item" disabled={disabled} title={note} onClick={disabled ? undefined : onSelect} className={["block w-full text-left px-3 py-2 text-sm bg-none border-none transition-colors", disabled ? "text-gray-400 cursor-default" : danger ? "text-red-600 hover:bg-red-50 cursor-pointer" : "text-gray-900 hover:bg-gray-100 cursor-pointer"].join(" ")}>
      {label}
      {note && <div className="text-xs text-gray-400 mt-0.5">{note}</div>}
    </button>;
}