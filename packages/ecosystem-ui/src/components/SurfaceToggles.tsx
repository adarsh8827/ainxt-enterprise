// SPDX-License-Identifier: MIT
// Task F-6: sourced from the surfaces registry via config (CONTRACTS.md
// §8's `surfaces` array) -- never a hardcoded chat/agent_studio/desktop
// list. Toggling calls the host's onChange with the full new surfaces set.
import { useConfig } from "../hooks/useEcosystemConfig";

export function SurfaceToggles({ enabledSurfaces, onChange, disabled }: {
  enabledSurfaces: string[]; onChange: (surfaces: string[]) => void; disabled?: boolean;
}) {
  const config = useConfig();
  return (
    <div data-testid="surface-toggles" style={{ display: "flex", gap: "var(--eco-space-sm)", flexWrap: "wrap" }}>
      {config.surfaces.map((surface) => {
        const checked = enabledSurfaces.includes(surface.key);
        return (
          <label
            key={surface.key}
            data-testid="surface-toggle"
            data-surface={surface.key}
            style={{ display: "flex", alignItems: "center", gap: "4px", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)" }}
          >
            <input
              type="checkbox"
              checked={checked}
              disabled={disabled}
              onChange={(e) => {
                const next = e.target.checked
                  ? [...enabledSurfaces, surface.key]
                  : enabledSurfaces.filter((s) => s !== surface.key);
                onChange(next);
              }}
            />
            {surface.label}
          </label>
        );
      })}
    </div>
  );
}
