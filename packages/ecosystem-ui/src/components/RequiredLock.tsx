// SPDX-License-Identifier: MIT
// Task F-6: a small lock glyph + label for scope='required' installs --
// no lucide-react (this package's own rule); a plain inline SVG lock,
// styled entirely from theme tokens.
export function RequiredLock() {
  return (
    <span
      data-testid="required-lock"
      title="Required by your organization"
      style={{ display: "inline-flex", alignItems: "center", gap: "4px", color: "var(--eco-color-textMuted)", fontSize: "var(--eco-font-sizeXs)" }}
    >
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        <rect x="5" y="11" width="14" height="9" rx="2" />
        <path d="M8 11V7a4 4 0 0 1 8 0v4" />
      </svg>
      Required
    </span>
  );
}
