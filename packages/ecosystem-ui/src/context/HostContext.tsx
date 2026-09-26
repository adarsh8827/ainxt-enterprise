// SPDX-License-Identifier: MIT
// The host-injection boundary (task F-1's own definition of done: "<Marketplace />
// accepting the full host-injection prop set: client, config, router hooks,
// theme tokens, layout, i18n strings"). Every component below <Marketplace />
// reads from this context instead of taking its own props, so a new screen
// never needs its own prop-drilling chain.
import { createContext, useContext, useMemo, type CSSProperties, type ReactNode } from "react";
import type { EcosystemClient } from "../client/EcosystemClient";
import { LIGHT_TOKENS, tokensToCssVars, type ThemeTokens } from "../theme";

export interface RouterHooks {
  /** Path relative to the host's own mount point, e.g. "/skills/acme%2Ffoo". */
  path: string;
  navigate: (path: string) => void;
  /** The host's mount point itself, e.g. "/marketplace" for ai-ui (task F-2)
   * -- needed only for constructing a shareable absolute URL (Detail.tsx's
   * Copy Link); every other navigation stays relative via path/navigate.
   * Defaults to "" (host mounted at the root) if omitted. */
  basePath?: string;
}

export type I18nStrings = Record<string, string>;

export const DEFAULT_STRINGS = {
  "discover": "Discover", "yours": "Yours", "create": "Create",
  "coming_soon": "Coming soon", "new_badge": "New", "verifying": "Verifying…",
  "empty_discover": "Nothing here yet.", "empty_yours": "You haven't added anything yet.",
} as const;

/** DEFAULT_STRINGS' own keys are always present as plain `string` (not
 * `string | undefined`, unlike an arbitrary I18nStrings lookup under
 * noUncheckedIndexedAccess) -- a host's custom strings still merge in via
 * the index signature for anything beyond this fixed set. */
export type MergedStrings = typeof DEFAULT_STRINGS & I18nStrings;

export interface HostConfig {
  client: EcosystemClient;
  theme?: ThemeTokens;
  layout: "full" | "compact";
  router: RouterHooks;
  strings?: I18nStrings;
}

/** What's actually stored in context after HostProvider fills in theme/
 * strings defaults -- theme and strings are never optional here, unlike
 * the raw HostConfig props a caller supplies. */
export type ResolvedHostConfig = Omit<HostConfig, "theme" | "strings"> & {
  theme: ThemeTokens;
  strings: MergedStrings;
};

const HostContext = createContext<ResolvedHostConfig | null>(null);

export function HostProvider({ value, children }: { value: HostConfig; children: ReactNode }) {
  const strings = useMemo(() => ({ ...DEFAULT_STRINGS, ...(value.strings ?? {}) }), [value.strings]);
  const theme = value.theme ?? LIGHT_TOKENS;
  const cssVars = useMemo(() => tokensToCssVars(theme), [theme]);

  return (
    <HostContext.Provider value={{ ...value, strings, theme }}>
      {/* Every text/border color below this point comes from the theme
          tokens, but nothing painted an actual background until now -- a
          host with no dark-mode surface of its own (ai-ui today) never
          noticed, since its shell is always light and LIGHT_TOKENS.color.bg
          happens to be white already. DARK_TOKENS made it visible: dark-
          theme text rendered on the *page's* leftover white background,
          nearly unreadable (found producing item 4's parity screenshots). */}
      <div className="eco-root" data-eco-layout={value.layout} style={{ ...cssVars, background: theme.color.bg, color: theme.color.textPrimary } as CSSProperties}>
        {children}
      </div>
    </HostContext.Provider>
  );
}

export function useHost(): ResolvedHostConfig {
  const ctx = useContext(HostContext);
  if (!ctx) throw new Error("useHost() called outside <HostProvider> -- every ecosystem-ui screen must render under <Marketplace />");
  return ctx;
}

export function useEcosystemClient(): EcosystemClient {
  return useHost().client;
}

export function useI18n(): MergedStrings {
  return useHost().strings;
}
