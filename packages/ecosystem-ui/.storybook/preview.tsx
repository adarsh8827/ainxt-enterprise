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
          <EcosystemConfigProvider>
            <Story />
          </EcosystemConfigProvider>
        </HostProvider>
      );
    },
  ],
};

export default preview;
