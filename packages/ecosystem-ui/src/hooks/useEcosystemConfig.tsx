// SPDX-License-Identifier: MIT
// Task F-4: config-driven rendering. Every screen calls useConfig() for its
// item-types/surfaces/features/taxonomy -- no component in this package may
// hardcode any of those lists (enforced by a CI grep check, task F-4's own
// test requirement, see scripts/ecosystem/check_no_hardcoded_config.py).
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { EcosystemConfig } from "../types";
import { useEcosystemClient } from "../context/HostContext";

interface ConfigState {
  config: EcosystemConfig | null;
  loading: boolean;
  error: unknown;
  refetch: () => void;
}

const ConfigContext = createContext<ConfigState | null>(null);

export function EcosystemConfigProvider({ children, initialConfig }: { children: ReactNode; initialConfig?: EcosystemConfig }) {
  const client = useEcosystemClient();
  const [config, setConfig] = useState<EcosystemConfig | null>(initialConfig ?? null);
  const [loading, setLoading] = useState(!initialConfig);
  const [error, setError] = useState<unknown>(null);
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    // A host that already has a config response (e.g. it fetched
    // GET /ecosystem/config itself for nav badges) skips this fetch
    // entirely -- every descendant still reads it via useConfig()/
    // useConfigState(), so there's exactly one source of truth for the
    // context regardless of which path populated it. A refetch()
    // (generation bump) always re-fetches for real, even if the initial
    // render used a preset value -- a caller that explicitly asks to
    // refresh should get a genuinely fresh response, not the stale preset.
    if (initialConfig && generation === 0) return;

    let cancelled = false;
    setLoading(true);
    setError(null);
    client.getConfig()
      .then((c) => { if (!cancelled) setConfig(c); })
      .catch((e) => { if (!cancelled) setError(e); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, generation]);

  return (
    <ConfigContext.Provider value={{ config, loading, error, refetch: () => setGeneration((g) => g + 1) }}>
      {children}
    </ConfigContext.Provider>
  );
}

/** Throws if called before the config has loaded -- callers that can render
 * during the loading state should use useConfigState() instead. */
export function useConfig(): EcosystemConfig {
  const ctx = useContext(ConfigContext);
  if (!ctx) throw new Error("useConfig() called outside <EcosystemConfigProvider>");
  if (!ctx.config) throw new Error("useConfig() called before GET /ecosystem/config resolved -- guard with useConfigState().loading first");
  return ctx.config;
}

export function useConfigState(): ConfigState {
  const ctx = useContext(ConfigContext);
  if (!ctx) throw new Error("useConfigState() called outside <EcosystemConfigProvider>");
  return ctx;
}

/** Type slug -> ItemType lookup (CONTRACTS.md §2), derived from the live
 * config's route_slugs -- never the hardcoded ROUTE_SLUGS constant, so a
 * caller reading from a real config response always matches what the
 * backend actually served. */
export function useTypeSlugLookup(): Record<string, string> {
  const config = useConfig();
  const bySlug: Record<string, string> = {};
  for (const [type, slug] of Object.entries(config.route_slugs)) bySlug[slug] = type;
  return bySlug;
}
