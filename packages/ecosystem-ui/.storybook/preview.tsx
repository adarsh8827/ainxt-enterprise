// SPDX-License-Identifier: MIT
// Global decorator: every story renders under a real HostProvider +
// EcosystemConfigProvider (backed by MockEcosystemClient), with a
// Storybook toolbar toggle for theme (light/dark) and layout
// (full/compact) -- task F-1/F-5-F-8's "Storybook stories (full/compact x
// light/dark)" requirement, applied once here rather than per-story.
import type { Preview } from "@storybook/react-vite";
import { HostProvider } from "../src/context/HostContext";
import { EcosystemConfigProvider } from "../src/hooks/useEcosystemConfig";
import { MockEcosystemClient } from "../src/client/MockEcosystemClient";
import { MOCK_CONFIG } from "../src/client/fixtures";
import { LIGHT_TOKENS, DARK_TOKENS } from "../src/theme";

const preview: Preview = {
  globalTypes: {
    theme: {
      description: "Theme tokens",
      toolbar: { title: "Theme", items: ["light", "dark"], dynamicTitle: true },
    },
    layout: {
      description: "Host layout",
      toolbar: { title: "Layout", items: ["full", "compact"], dynamicTitle: true },
    },
  },
  initialGlobals: { theme: "light", layout: "full" },
  decorators: [
    (Story, context) => {
      const theme = context.globals.theme === "dark" ? DARK_TOKENS : LIGHT_TOKENS;
      const layout = context.globals.layout === "compact" ? "compact" : "full";
      const client = new MockEcosystemClient();
      return (
        <HostProvider
          value={{
            client,
            theme,
            layout,
            router: { path: "/skills", navigate: () => {} },
          }}
        >
          {/* initialConfig -- without it, any story rendering a "leaf"
              screen (Discover/Yours/AddDialog/etc., anything calling
              useConfig() directly rather than going through
              Marketplace.tsx's own loading gate) races
              MockEcosystemClient's async getConfig() on first render and
              permanently trips its error boundary on a cold navigation
              straight to iframe.html?id=... (found while producing UI
              parity screenshots against the reference mock -- every
              affected story rendered its "Something went wrong" fallback
              instead of the real UI, silently, since Storybook's own dev
              UI don't surface a console error the same way a script
              driving it headlessly does). renderWithHost() (src/
              test-utils.tsx) already avoids this exact race for vitest
              component tests the same way. */}
          <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
            <Story />
          </EcosystemConfigProvider>
        </HostProvider>
      );
    },
  ],
};

export default preview;
