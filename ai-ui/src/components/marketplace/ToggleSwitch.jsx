// SPDX-License-Identifier: MIT
// A minimal on/off pill switch for Detail.tsx's installed-state header
// (enable/disable, from the user's own reference screenshot -- layout and
// interaction only, no text/colors copied). No existing visual toggle
// exists anywhere in this package yet -- Yours.tsx's own enable/disable is
// a plain kebab-menu text item, client.setEnabled(installId, bool) either
// way -- so this is a real UI primitive, not a duplicate of one. Theme
// tokens only, no new dependency (a two-state pill needs no icon).
export function ToggleSwitch({
  checked,
  onChange,
  disabled,
  label
}) {
  return <button type="button" role="switch" aria-checked={checked} aria-label={label} data-testid="toggle-switch" disabled={disabled} onClick={() => onChange(!checked)} className={["relative w-9 h-5 rounded-full border-none p-0 flex-shrink-0", checked ? "bg-indigo-600" : "bg-gray-200", disabled ? "opacity-60 cursor-default" : "cursor-pointer"].join(" ")}>
      <span className="absolute top-0.5 w-4 h-4 rounded-full bg-white transition-[left] duration-150 ease-linear" style={{
      left: checked ? "18px" : "2px"
    }} />
    </button>;
}