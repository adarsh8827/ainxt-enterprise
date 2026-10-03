// SPDX-License-Identifier: MIT
// Shared render helper for component tests -- wraps a component under a
// real HostProvider + EcosystemConfigProvider, backed by MockEcosystemClient
// (never a hand-rolled fake, so tests exercise the same context-consumption
// path every real screen does).
import { render } from "@testing-library/react";
import { HostProvider } from "@marketplace/lib/context/HostContext";
import { EcosystemConfigProvider } from "@marketplace/lib/hooks/useEcosystemConfig";
import { MockEcosystemClient } from "@marketplace/lib/client/MockEcosystemClient";
import { MOCK_CONFIG } from "@marketplace/lib/client/fixtures";
import { LIGHT_TOKENS } from "@marketplace/lib/theme";

/**
 * Renders under a real HostProvider + EcosystemConfigProvider.
 *
 * Passes the client's own config as EcosystemConfigProvider's
 * `initialConfig` (never leaving it to the provider's own async fetch) --
 * most component tests render a leaf screen directly, skipping the
 * loading gate that MarketplaceScreen.jsx's own root component provides in
 * the real app. Without this, any component calling useConfig() would
 * throw on the test's very first synchronous render, since the mock
 * client's getConfig() (like the real one) always resolves on a
 * microtask, never synchronously.
 */
export function renderWithHost(ui, options = {}) {
  const client = new MockEcosystemClient(options.clientOptions);
  const router = options.router ?? { path: "/skills", navigate: () => {} };
  const initialConfig = options.clientOptions?.config ?? MOCK_CONFIG;
  const result = render(
    <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router }}>
      <EcosystemConfigProvider initialConfig={initialConfig}>{ui}</EcosystemConfigProvider>
    </HostProvider>,
  );
  return { ...result, client };
}
