// SPDX-License-Identifier: MIT
// Task F-6: sourced from the surfaces registry via config (CONTRACTS.md
// §8's `surfaces` array) -- never a hardcoded chat/agent_studio/desktop
// list. Toggling calls the host's onChange with the full new surfaces set.
//
// Real UI feedback (2026-09-27): rendered as form checkboxes, which read
// as a settings form rather than a quick per-row control -- rebuilt as
// small pill-style toggle chips (click to flip), matching the reference
// mock's own surface-chip treatment. Behavior (onChange receives the
// full new surfaces array) is unchanged.
import { useConfig } from "../hooks/useEcosystemConfig";

export function SurfaceToggles({ enabledSurfaces, onChange, disabled }: {
  enabledSurfaces: string[]; onChange: (surfaces: string[]) => void; disabled?: boolean;
}) {
  const config = useConfig();
  return (
    <div
      data-testid="surface-toggles"
      // Real bug found live (2026-09-28): a card with several surfaces
      // AND a longer name/description wrapped this row to a second line,
      // making the whole card footer taller than its neighbors in the
      // same grid row. Card footers must never wrap -- nowrap + clipping
      // overflow (rather than shrinking each chip's own padding/font,
      // which would make chips inconsistent-looking depending on count)
      // is the compact-chips behavior the spec asks for; the parent
      // (Card.tsx/Yours.tsx footer) gives this element `minWidth: 0` so
      // it's actually allowed to shrink/clip instead of forcing the
      // footer wider than the card.
      style={{ display: "flex", gap: "6px", flexWrap: "nowrap", overflow: "hidden" }}
    >
      {config.surfaces.map((surface) => {
        const checked = enabledSurfaces.includes(surface.key);
        return (
          <button
            key={surface.key}
            type="button"
            role="switch"
            aria-checked={checked}
            data-testid="surface-toggle"
            data-surface={surface.key}
            disabled={disabled}
            onClick={() => {
              const next = checked
                ? enabledSurfaces.filter((s) => s !== surface.key)
                : [...enabledSurfaces, surface.key];
              onChange(next);
            }}
            style={{
              flexShrink: 0, whiteSpace: "nowrap",
              padding: "3px 10px",
              borderRadius: "var(--eco-radius-full)",
              border: "1px solid " + (checked ? "var(--eco-color-accentSkill)" : "var(--eco-color-border)"),
              background: checked ? "var(--eco-color-accentSkill)" : "var(--eco-color-bg)",
              color: checked ? "var(--eco-color-accentSkillText)" : "var(--eco-color-textSecondary)",
              fontSize: "var(--eco-font-sizeXs)",
              cursor: disabled ? "default" : "pointer",
              opacity: disabled ? 0.6 : 1,
            }}
          >
            {surface.label}
          </button>
        );
      })}
    </div>
  );
}
