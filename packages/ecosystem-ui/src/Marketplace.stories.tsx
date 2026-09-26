// SPDX-License-Identifier: MIT
// Task F-12: renders the real Marketplace root against a workspace-shaped
// config fixture (MOCK_CONFIG_WORKSPACE) -- proves the *same* build, given
// a different EcosystemConfig, shows the compact layout with only that
// profile's entitled features (no Admin nav, no Share action, no
// import-by-URL) rather than needing a forked/parallel component.
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Marketplace } from "./Marketplace";
import { MockEcosystemClient } from "./client/MockEcosystemClient";
import { MOCK_CONFIG, MOCK_CONFIG_WORKSPACE } from "./client/fixtures";
import { LIGHT_TOKENS, DARK_TOKENS } from "./theme";

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

// Task item 4 (M5 UI-parity review): the full catalog list page -- Toolbar
// (title, type tabs, Yours/Discover switch, search, filter, sort, "+ Add")
// plus Discover -- at the enterprise profile's `full` layout, in both
// themes. Marketplace.stories.tsx's own args always win over the global
// decorator's theme/layout toolbar toggle (`<Marketplace>` builds its own
// HostProvider from these exact props, nested inside and shadowing the
// decorator's), so a light/dark and full/compact comparison needs one
// story per combination rather than relying on the toolbar toggle here.
export const EnterpriseFullLightProfile: StoryObj<typeof Marketplace> = {
  args: {
    client: new MockEcosystemClient({ config: MOCK_CONFIG, initialInstalls: ["item-standup-notes"] }),
    layout: "full",
    theme: LIGHT_TOKENS,
    router: { path: "/skills", navigate: () => {} },
  },
};

export const EnterpriseFullDarkProfile: StoryObj<typeof Marketplace> = {
  args: {
    client: new MockEcosystemClient({ config: MOCK_CONFIG, initialInstalls: ["item-standup-notes"] }),
    layout: "full",
    theme: DARK_TOKENS,
    router: { path: "/skills", navigate: () => {} },
  },
};

export const WorkspaceCompactDarkProfile: StoryObj<typeof Marketplace> = {
  args: {
    client: new MockEcosystemClient({ config: MOCK_CONFIG_WORKSPACE }),
    layout: "compact",
    theme: DARK_TOKENS,
    router: { path: "/skills", navigate: () => {} },
  },
};
