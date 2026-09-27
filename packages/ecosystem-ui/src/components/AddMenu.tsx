// SPDX-License-Identifier: MIT
// The "+ Add" menu (CONTRACTS.md §8): every entry always renders (never
// omitted), for every item type -- an entry for a not-yet-`available`
// type (Plugin/Connector/MCP server this phase) renders disabled with a
// "Coming soon" label rather than being hidden or swapped out, per §8's
// own documented rule ("no install/add actions rendered anywhere for
// it... including the '+ Add' menu (whose corresponding entries... render
// disabled with a 'Coming soon' label rather than being omitted")).
// Admin entries are hidden outright (not just disabled) for a caller
// without marketplace:provision -- config.caller_permissions is the only
// signal this ever gates on, never role/product inferred client-side.
import { useRef, useState, type CSSProperties } from "react";
import { PlusIcon, SparklesIcon, PencilIcon, ArrowUpTrayIcon, CodeBracketIcon, PuzzlePieceIcon, LinkIcon, GlobeAltIcon, ShieldCheckIcon } from "@heroicons/react/24/outline";
import { useConfig } from "../hooks/useEcosystemConfig";
import { useHost } from "../context/HostContext";
import { adminPath } from "../routing";
import type { CreateAction } from "../routing";
import { PopoverAnchor } from "./PopoverAnchor";

export function AddMenu({ activeSlug, onSelect, onCreateWithAi }: {
  activeSlug: string; onSelect: (action: CreateAction) => void; onCreateWithAi?: () => void;
}) {
  const config = useConfig();
  const { router } = useHost();
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const active = config.item_types.find((t) => t.slug === activeSlug);
  const isAvailable = active?.state === "available";

  const skillEntries: Array<{ action: CreateAction; icon: typeof PencilIcon; label: string; enabledFeature: boolean }> = [
    { action: "new", icon: PencilIcon, label: "Write a skill", enabledFeature: config.features.write },
    { action: "upload", icon: ArrowUpTrayIcon, label: "Upload (.zip / .skill)", enabledFeature: config.features.upload },
    { action: "import", icon: CodeBracketIcon, label: "Import from GitHub / URL", enabledFeature: config.features.import_url },
  ];
  // Always rendered, every type, regardless of activeSlug -- these are
  // NOT alternates for whichever type tab happens to be active; they are
  // the other 3 types' own entries, always disabled this phase.
  const comingSoonEntries = [
    { key: "mcp_server", icon: PuzzlePieceIcon, label: "Add MCP server" },
    { key: "connector", icon: LinkIcon, label: "Add connector" },
    { key: "plugin", icon: GlobeAltIcon, label: "Add plugin" },
  ];
  const showAdmin = config.caller_permissions.can_provision;

  const itemStyle = (disabled: boolean): CSSProperties => ({
    display: "flex", alignItems: "center", gap: "8px", width: "100%", textAlign: "left",
    padding: "8px 12px", background: "none", border: "none", cursor: disabled ? "default" : "pointer",
    color: disabled ? "var(--eco-color-textMuted)" : "var(--eco-color-textPrimary)", fontSize: "var(--eco-font-sizeSm)",
  });

  return (
    <div style={{ position: "relative" }}>
      <button
        ref={triggerRef}
        type="button"
        data-testid="add-menu-trigger"
        onClick={() => setOpen((o) => !o)}
        style={{ display: "inline-flex", alignItems: "center", gap: "6px", padding: "8px 16px", borderRadius: "var(--eco-radius-md)", border: "none", background: "var(--eco-color-accentSkill)", color: "var(--eco-color-accentSkillText)", cursor: "pointer" }}
      >
        <PlusIcon width={16} height={16} aria-hidden="true" /> Add
      </button>
      <PopoverAnchor anchorRef={triggerRef} open={open} align="right">
        <div
          role="menu"
          data-testid="add-menu"
          style={{ minWidth: "240px", background: "var(--eco-color-bg)", border: "1px solid var(--eco-color-border)", borderRadius: "var(--eco-radius-md)", boxShadow: "0 4px 12px var(--eco-color-overlay)" }}
          onMouseLeave={() => setOpen(false)}
        >
          {isAvailable && config.features.create_with_ai && onCreateWithAi && (
            <button
              type="button" role="menuitem" data-testid="add-menu-create-with-ai"
              onClick={() => { onCreateWithAi(); setOpen(false); }}
              style={itemStyle(false)}
            >
              <SparklesIcon width={16} height={16} aria-hidden="true" /> Create with AI
            </button>
          )}
          {isAvailable && skillEntries.map((entry) => {
            const disabled = !entry.enabledFeature;
            const Icon = entry.icon;
            return (
              <button
                key={entry.action}
                type="button"
                role="menuitem"
                data-testid={`add-menu-${entry.action}`}
                disabled={disabled}
                onClick={() => { if (!disabled) { onSelect(entry.action); setOpen(false); } }}
                style={itemStyle(disabled)}
              >
                <Icon width={16} height={16} aria-hidden="true" /> {entry.label}
              </button>
            );
          })}
          <div style={{ borderTop: "1px solid var(--eco-color-border)" }} />
          {comingSoonEntries.map((entry) => {
            const Icon = entry.icon;
            return (
              <button
                key={entry.key}
                type="button"
                role="menuitem"
                data-testid={`add-menu-${entry.key}-coming-soon`}
                disabled
                title="Coming soon"
                style={itemStyle(true)}
              >
                <Icon width={16} height={16} aria-hidden="true" />
                <span style={{ flex: 1 }}>{entry.label}</span>
                <span style={{ fontSize: "var(--eco-font-sizeXs)" }}>Coming soon</span>
              </button>
            );
          })}
          {showAdmin && (
            <>
              <div style={{ borderTop: "1px solid var(--eco-color-border)" }} />
              <div style={{ padding: "6px 12px", fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-textSecondary)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                Admin
              </div>
              <button
                type="button" role="menuitem" data-testid="add-menu-add-source" disabled title="Not yet available"
                style={itemStyle(true)}
              >
                <GlobeAltIcon width={16} height={16} aria-hidden="true" />
                <span style={{ flex: 1 }}>Add source</span>
                <span style={{ fontSize: "var(--eco-font-sizeXs)" }}>Coming soon</span>
              </button>
              <button
                type="button" role="menuitem" data-testid="add-menu-provision-for-org"
                onClick={() => { setOpen(false); router.navigate(adminPath("provisioning")); }}
                style={itemStyle(false)}
              >
                <ShieldCheckIcon width={16} height={16} aria-hidden="true" /> Provision for org
              </button>
            </>
          )}
        </div>
      </PopoverAnchor>
    </div>
  );
}
