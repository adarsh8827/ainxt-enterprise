// SPDX-License-Identifier: MIT
// A minimal on/off pill switch for Detail.tsx's installed-state header
// (enable/disable, from the user's own reference screenshot -- layout and
// interaction only, no text/colors copied). No existing visual toggle
// exists anywhere in this package yet -- Yours.tsx's own enable/disable is
// a plain kebab-menu text item, client.setEnabled(installId, bool) either
// way -- so this is a real UI primitive, not a duplicate of one. Theme
// tokens only, no new dependency (a two-state pill needs no icon).
export function ToggleSwitch({ checked, onChange, disabled, label }: {
  checked: boolean; onChange: (next: boolean) => void; disabled?: boolean; label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      data-testid="toggle-switch"
      disabled={disabled}
      onClick={() => onChange(!checked)}
      style={{
        position: "relative", width: "36px", height: "20px", borderRadius: "var(--eco-radius-full)",
        border: "none", padding: 0, cursor: disabled ? "default" : "pointer",
        background: checked ? "var(--eco-color-accentSkill)" : "var(--eco-color-border)",
        opacity: disabled ? 0.6 : 1, flexShrink: 0,
      }}
    >
      <span
        style={{
          position: "absolute", top: "2px", left: checked ? "18px" : "2px",
          width: "16px", height: "16px", borderRadius: "var(--eco-radius-full)",
          background: "var(--eco-color-bg)", transition: "left 0.15s ease",
        }}
      />
    </button>
  );
}
