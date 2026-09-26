// SPDX-License-Identifier: MIT
// Task F-12: renders the real Marketplace root against a workspace-shaped
// config fixture (MOCK_CONFIG_WORKSPACE) -- proves the *same* build, given
// a different EcosystemConfig, shows the compact layout with only that
// profile's entitled features (no Admin nav, no Share action, no
// import-by-URL) rather than needing a forked/parallel component.
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Marketplace } from "./Marketplace";
import { MockEcosystemClient } from "./client/MockEcosystemClient";
import { MOCK_CONFIG_WORKSPACE } from "./client/fixtures";
import { LIGHT_TOKENS } from "./theme";

const meta: Meta<typeof Marketplace> = { title: "Marketplace/Marketplace", component: Marketplace };
export default meta;

export const WorkspaceCompactProfile: StoryObj<typeof Marketplace> = {
  args: {
    client: new MockEcosystemClient({ config: MOCK_CONFIG_WORKSPACE }),
    layout: "compact",
    theme: LIGHT_TOKENS,
    router: { path: "/skills", navigate: () => {} },
  },
};
