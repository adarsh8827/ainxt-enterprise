// SPDX-License-Identifier: MIT
// Task F-12: a minimal example host demonstrating layout:"compact" +
// x-ainxt-product: workspace consumption of this same package -- explicitly
// a test/demo host for this repo (Playwright's "workspace" profile spec
// points at it), not the production ainxt-workspace product itself (which,
// like ainxt-cli, is out of this repo's scope). No forked components: this
// imports the exact same source ai-ui's Marketplace.jsx wrapper does.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import {
  Marketplace, MockEcosystemClient, RealEcosystemClient, MOCK_CONFIG_WORKSPACE, LIGHT_TOKENS,
} from "../../src/index";

// Default: a real backend at VITE_WORKSPACE_HOST_API (e.g.
// http://localhost:8000/ainxt/v1/api), asking for the "workspace" product --
// requires the caller's org to actually have a workspace entitlement row
// (docs/ecosystem/CONFIG_AND_PRODUCTS.md §3). Falls back to an in-memory
// MockEcosystemClient (MOCK_CONFIG_WORKSPACE fixture) when no API base is
// configured, so this host also runs with zero backend dependency.
const apiBase = import.meta.env.VITE_WORKSPACE_HOST_API as string | undefined;
const client = apiBase
  ? new RealEcosystemClient({ baseUrl: apiBase, product: "workspace" })
  : new MockEcosystemClient({ config: MOCK_CONFIG_WORKSPACE });

function App() {
  return (
    <Marketplace
      client={client}
      layout="compact"
      theme={LIGHT_TOKENS}
      router={{
        path: window.location.pathname.replace(/^\/workspace-host/, "") || "/skills",
        navigate: (path) => window.history.pushState(null, "", `/workspace-host${path}`),
        basePath: "/workspace-host",
      }}
    />
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
