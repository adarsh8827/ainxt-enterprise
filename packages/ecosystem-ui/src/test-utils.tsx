// SPDX-License-Identifier: MIT
// Shared render helper for component tests -- wraps a component under a
// real HostProvider + EcosystemConfigProvider, backed by MockEcosystemClient
// (never a hand-rolled fake, so tests exercise the same context-consumption
// path every real screen does).
import { render, type RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";
import { HostProvider, type RouterHooks } from "./context/HostContext";
import { EcosystemConfigProvider } from "./hooks/useEcosystemConfig";
import { MockEcosystemClient, type MockEcosystemClientOptions } from "./client/MockEcosystemClient";
import { MOCK_CONFIG } from "./client/fixtures";
import { LIGHT_TOKENS } from "./theme";

/**
 * Renders under a real HostProvider + EcosystemConfigProvider.
 *
 * Passes the client's own config as EcosystemConfigProvider's
 * `initialConfig` (never leaving it to the provider's own async fetch) --
 * most component tests render a leaf screen directly, skipping the
 * loading gate that Marketplace.tsx's own root component provides in the
 * real app. Without this, any component calling useConfig() would throw
 * on the test's very first synchronous render, since the mock client's
 * getConfig() (like the real one) always resolves on a microtask, never
 * synchronously.
 */
export function renderWithHost(
  ui: ReactElement,
  options: { clientOptions?: MockEcosystemClientOptions; router?: RouterHooks } = {},
): RenderResult & { client: MockEcosystemClient } {
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
