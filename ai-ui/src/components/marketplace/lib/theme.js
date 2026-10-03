// SPDX-License-Identifier: MIT
// ============================================================
// Host-injected design tokens (CONFIG_AND_PRODUCTS.md §7 item 16). No
// component in this package ever references a hex value directly -- every
// color/spacing/radius value flows through this token set, applied as CSS
// custom properties by <ThemeProvider>, so a host with its own theme system
// (ai-ui's Tailwind utilities today) or one with none (a bare workspace
// example host) both work identically: the tokens ARE the theme.
//
// ai-ui has no live dark-mode toggle today (confirmed by direct inspection
// of ai-ui/src/index.css -- ":root { color-scheme: light; }", "The app has
// no dark theme.") -- LIGHT_TOKENS below is what ai-ui's Marketplace.jsx
// wrapper actually supplies. DARK_TOKENS exists so this package's own
// Storybook/light-dark story matrix (task F-1's own requirement) has a real
// second token set to render against, not a hypothetical one; it's not
// reachable from ai-ui until ai-ui itself gains a dark mode.
// ============================================================

export const LIGHT_TOKENS = {
  color: {
    bg: "#ffffff",
    surface: "#f9fafb",
    surfaceHover: "#f3f4f6",
    border: "#e5e7eb",
    borderHover: "#d1d5db",
    textPrimary: "#111827",
    textSecondary: "#4b5563",
    textMuted: "#9ca3af",
    accentSkill: "#4f46e5",
    accentSkillHover: "#4338ca",
    accentSkillText: "#ffffff",
    accentPlugin: "#0284c7",
    accentConnector: "#7c3aed",
    accentMcp: "#0d9488",
    success: "#15803d",
    successBg: "#f0fdf4",
    warning: "#b45309",
    warningBg: "#fffbeb",
    danger: "#b91c1c",
    dangerHover: "#991b1b",
    dangerBg: "#fef2f2",
    info: "#1d4ed8",
    infoBg: "#eff6ff",
    overlay: "rgba(17, 24, 39, 0.5)",
    monogramPalette: ["#4f46e5", "#0284c7", "#7c3aed", "#0d9488", "#b45309", "#b91c1c", "#15803d", "#1d4ed8"],
    monogramText: "#ffffff"
  },
  radius: {
    sm: "6px",
    md: "8px",
    lg: "12px",
    full: "9999px"
  },
  space: {
    xs: "4px",
    sm: "8px",
    md: "16px",
    lg: "24px",
    xl: "32px"
  },
  font: {
    family: "inherit",
    sizeXs: "12px",
    sizeSm: "13px",
    sizeMd: "14px",
    sizeLg: "16px",
    sizeXl: "20px"
  },
  // ai-ui's own native components (KnowledgeBase.jsx, ProductManager.jsx)
  // keep elevation modest -- panels/cards sit on `shadow-sm`, dropdowns on
  // `shadow-md`, and nothing lifts/escalates its shadow on hover. Matched
  // here instead of the earlier Linear/Stripe-style "raised on hover" scale.
  shadow: {
    sm: "0 1px 2px rgba(17, 24, 39, 0.05)",
    md: "0 4px 6px -1px rgba(17, 24, 39, 0.08), 0 2px 4px -2px rgba(17, 24, 39, 0.06)",
    lg: "0 10px 20px -5px rgba(17, 24, 39, 0.12), 0 4px 6px -4px rgba(17, 24, 39, 0.08)",
    xl: "0 20px 32px -8px rgba(17, 24, 39, 0.18), 0 6px 10px -6px rgba(17, 24, 39, 0.1)"
  },
  // Shared easing/duration so every hover/press/entrance transition across
  // the feature feels like one motion language instead of each component
  // picking its own -- consumed as plain CSS strings (`transition: all
  // ${motion.base}`), never a CSS custom property of its own (JS template
  // strings compose these inline, no indirection needed).
  motion: {
    fast: "120ms cubic-bezier(0.4, 0, 0.2, 1)",
    base: "180ms cubic-bezier(0.4, 0, 0.2, 1)",
    slow: "280ms cubic-bezier(0.16, 1, 0.3, 1)"
  }
};
export const DARK_TOKENS = {
  color: {
    bg: "#0f1115",
    surface: "#181b21",
    surfaceHover: "#20242c",
    border: "#2b2f38",
    borderHover: "#3a3f4a",
    textPrimary: "#f3f4f6",
    textSecondary: "#c9ccd3",
    textMuted: "#7d828d",
    accentSkill: "#818cf8",
    accentSkillHover: "#a5b4fc",
    accentSkillText: "#0f1115",
    accentPlugin: "#38bdf8",
    accentConnector: "#a78bfa",
    accentMcp: "#2dd4bf",
    success: "#4ade80",
    successBg: "#0f2417",
    warning: "#fbbf24",
    warningBg: "#2a2007",
    danger: "#f87171",
    dangerHover: "#fca5a5",
    dangerBg: "#2a1212",
    info: "#60a5fa",
    infoBg: "#0f1e33",
    overlay: "rgba(0, 0, 0, 0.65)",
    monogramPalette: ["#818cf8", "#38bdf8", "#a78bfa", "#2dd4bf", "#fbbf24", "#f87171", "#4ade80", "#60a5fa"],
    monogramText: "#0f1115"
  },
  radius: {
    sm: "6px",
    md: "8px",
    lg: "12px",
    full: "9999px"
  },
  space: {
    xs: "4px",
    sm: "8px",
    md: "16px",
    lg: "24px",
    xl: "32px"
  },
  font: {
    family: "inherit",
    sizeXs: "12px",
    sizeSm: "13px",
    sizeMd: "14px",
    sizeLg: "16px",
    sizeXl: "20px"
  },
  // Shadows stay the same (near-black, low-opacity) across light/dark --
  // standard practice, and matches ai-ui's own Tailwind shadow utilities,
  // which don't vary by color-scheme either.
  shadow: {
    sm: "0 1px 2px rgba(0, 0, 0, 0.05)",
    md: "0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -2px rgba(0, 0, 0, 0.1)",
    lg: "0 10px 20px -5px rgba(0, 0, 0, 0.3), 0 4px 6px -4px rgba(0, 0, 0, 0.16)",
    xl: "0 20px 32px -8px rgba(0, 0, 0, 0.4), 0 6px 10px -6px rgba(0, 0, 0, 0.2)"
  },
  motion: {
    fast: "120ms cubic-bezier(0.4, 0, 0.2, 1)",
    base: "180ms cubic-bezier(0.4, 0, 0.2, 1)",
    slow: "280ms cubic-bezier(0.16, 1, 0.3, 1)"
  }
};

/** Flattens ThemeTokens into a CSS-custom-property map, e.g. "--eco-color-bg".
 * Array-valued tokens (monogramPalette) are skipped -- a CSS custom property
 * holds one value, and that palette is selected by index in JS
 * (ItemIcon.tsx reads useHost().theme directly for it), not via CSS var. */
export function tokensToCssVars(tokens) {
  const vars = {};
  for (const [group, values] of Object.entries(tokens)) {
    for (const [key, value] of Object.entries(values)) {
      if (typeof value === "string") vars[`--eco-${group}-${key}`] = value;
    }
  }
  return vars;
}