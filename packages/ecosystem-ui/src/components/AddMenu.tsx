// SPDX-License-Identifier: MIT
// The "+ Add" menu (CONTRACTS.md §8): write/upload/import entries for the
// active, available type; every other type's entries render disabled with
// a "Coming soon" label rather than being omitted (Review fix 18).
import { useState } from "react";
import { PlusIcon } from "@heroicons/react/24/outline";
import { useConfig } from "../hooks/useEcosystemConfig";
import type { CreateAction } from "../routing";

export function AddMenu({ activeSlug, onSelect }: { activeSlug: string; onSelect: (action: CreateAction) => void }) {
  const config = useConfig();
  const [open, setOpen] = useState(false);
  const active = config.item_types.find((t) => t.slug === activeSlug);
  const isAvailable = active?.state === "available";

  const entries: Array<{ action: CreateAction; label: string; enabledFeature: boolean }> = [
    { action: "new", label: "Write", enabledFeature: config.features.write },
    { action: "upload", label: "Upload", enabledFeature: config.features.upload },
    { action: "import", label: "Import from URL", enabledFeature: config.features.import_url },
  ];

  return (
    <div style={{ position: "relative" }}>
      <button
        type="button"
        data-testid="add-menu-trigger"
        onClick={() => setOpen((o) => !o)}
        style={{ display: "inline-flex", alignItems: "center", gap: "6px", padding: "8px 16px", borderRadius: "var(--eco-radius-md)", border: "none", background: "var(--eco-color-accentSkill)", color: "var(--eco-color-accentSkillText)", cursor: "pointer" }}
      >
        <PlusIcon width={16} height={16} aria-hidden="true" /> Add
      </button>
      {open && (
        <div
          role="menu"
          data-testid="add-menu"
          style={{ position: "absolute", right: 0, top: "100%", zIndex: 10, minWidth: "180px", background: "var(--eco-color-bg)", border: "1px solid var(--eco-color-border)", borderRadius: "var(--eco-radius-md)", boxShadow: "0 4px 12px var(--eco-color-overlay)" }}
          onMouseLeave={() => setOpen(false)}
        >
          {entries.map((entry) => {
            const disabled = !isAvailable || !entry.enabledFeature;
            return (
              <button
                key={entry.action}
                type="button"
                role="menuitem"
                data-testid={`add-menu-${entry.action}`}
                disabled={disabled}
                onClick={() => { if (!disabled) { onSelect(entry.action); setOpen(false); } }}
                style={{
                  display: "flex", justifyContent: "space-between", width: "100%", textAlign: "left",
                  padding: "8px 12px", background: "none", border: "none", cursor: disabled ? "default" : "pointer",
                  color: disabled ? "var(--eco-color-textMuted)" : "var(--eco-color-textPrimary)",
                }}
              >
                {entry.label}
                {!isAvailable && <span style={{ fontSize: "var(--eco-font-sizeXs)" }}>Coming soon</span>}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
