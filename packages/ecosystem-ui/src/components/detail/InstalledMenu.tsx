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
import { useRef, useState } from "react";
import { ChevronDownIcon } from "@heroicons/react/24/outline";
import { PopoverAnchor } from "../PopoverAnchor";
import { MenuItem } from "../KebabMenu";

export function InstalledMenu({ enabled, required, onManageInYours, onToggleEnabled, onViewVersions, onUninstall, disabled }: {
  enabled: boolean;
  required: boolean;
  onManageInYours: () => void;
  onToggleEnabled: (next: boolean) => void;
  onViewVersions: () => void;
  onUninstall: () => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

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
        style={{
          display: "inline-flex", alignItems: "center", gap: "4px", padding: "8px 12px",
          borderRadius: "var(--eco-radius-md)", border: "1px solid var(--eco-color-border)",
          background: "var(--eco-color-bg)", color: "var(--eco-color-textPrimary)",
          cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.6 : 1,
        }}
      >
        Installed <ChevronDownIcon width={14} height={14} aria-hidden="true" />
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
          <MenuItem label="Manage in Yours" onSelect={() => { onManageInYours(); setOpen(false); }} />
          <MenuItem label={enabled ? "Disable" : "Enable"} onSelect={() => { onToggleEnabled(!enabled); setOpen(false); }} />
          <MenuItem label="Versions & rollback" onSelect={() => { onViewVersions(); setOpen(false); }} />
          <div style={{ borderTop: "1px solid var(--eco-color-border)" }} />
          {required ? (
            <MenuItem label="Required" disabled note="Required by your admin. It can't be removed." />
          ) : (
            <MenuItem label="Uninstall" danger onSelect={() => { onUninstall(); setOpen(false); }} />
          )}
        </div>
      </PopoverAnchor>
    </div>
  );
}
