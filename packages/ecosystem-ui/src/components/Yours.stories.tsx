// SPDX-License-Identifier: MIT
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Yours } from "./Yours";
import { HostProvider } from "../context/HostContext";
import { EcosystemConfigProvider } from "../hooks/useEcosystemConfig";
import { MOCK_CONFIG, MOCK_DETAILS } from "../client/fixtures";
import { LIGHT_TOKENS, DARK_TOKENS } from "../theme";
import type { EcosystemClient } from "../client/EcosystemClient";
import type { Install } from "../types";

const meta: Meta<typeof Yours> = { title: "Yours/Yours", component: Yours };
export default meta;

export const EmptyState: StoryObj<typeof Yours> = {
  // MockEcosystemClient's default (no initialInstalls) has zero installs
  // for a fresh client instance, so this story exercises F-6's empty state.
  args: { itemType: "skill", onOpen: () => {}, onCreate: () => {}, onDiscover: () => {} },
};

const DETAILS = Object.values(MOCK_DETAILS);
const mkInstall = (id: string, origin: Install["origin"], scope: Install["scope"] = "private"): Install => ({
  install_id: `install-${id}`, item: DETAILS.find((d) => d.id === id)!, version_id: `${id}-v1`, scope, origin,
  installed_by: "user-1", installed_for: "user-1", enabled: true, surfaces: ["chat"],
  auto_update: false, installed_at: new Date().toISOString(),
});

// Bypasses the global Storybook decorator's own single shared client
// (preview.tsx) with a nested HostProvider carrying a purpose-built fake
// client -- needed here since MockEcosystemClient's initialInstalls
// option always tags rows origin="provisioned", and this story needs
// every GROUP_ORDER bucket populated to visually match the reference
// mock's own "Yours" grouping (Created by me / Shared with me / Org
// provisioned / Required / Added from Discover).
export const Populated: StoryObj<typeof Yours> = {
  // Reads context.globals.theme/layout itself -- this story's own nested
  // HostProvider replaces the global decorator's client, so it must also
  // replicate the decorator's own theme/layout toolbar wiring (preview.tsx)
  // rather than silently ignoring it (a real bug caught while producing
  // parity screenshots: the first draft hardcoded LIGHT_TOKENS, so toggling
  // the Storybook toolbar's Theme control had no visible effect at all).
  render: (args, context) => {
    const sharedInstall = mkInstall("item-invoice-parser", "shared", "shared");
    // Task 3c fix: "Shared with me" now offers a real Unshare action --
    // share_id (items_service._share_id_for_recipient()) is what makes it
    // callable at all; MOCK_ITEMS' own item-invoice-parser has neither by
    // default, so this story overrides both to actually show the button.
    sharedInstall.item = { ...sharedInstall.item, allowed_actions: ["unshare", "report"], share_id: "share-story-demo" };
    const installs: Install[] = [
      mkInstall("item-exec-assistant", "created"),
      sharedInstall,
      mkInstall("item-standup-notes", "provisioned", "provisioned"),
      mkInstall("item-onboarding-buddy", "required", "required"),
      mkInstall("item-contract-reviewer", "added"),
    ];
    const client = {
      getInstalls: () => Promise.resolve({ installs, legacy_items: [], has_any: true, next_cursor: null }),
    } as unknown as EcosystemClient;
    const theme = context.globals.theme === "dark" ? DARK_TOKENS : LIGHT_TOKENS;
    const layout = context.globals.layout === "compact" ? "compact" : "full";
    return (
      <HostProvider value={{ client, theme, layout, router: { path: "/skills", navigate: () => {} } }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours {...args} />
        </EcosystemConfigProvider>
      </HostProvider>
    );
  },
  args: { itemType: "skill", onOpen: () => {}, onCreate: () => {}, onDiscover: () => {} },
};
