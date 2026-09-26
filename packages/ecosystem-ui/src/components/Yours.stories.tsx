// SPDX-License-Identifier: MIT
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Yours } from "./Yours";

const meta: Meta<typeof Yours> = { title: "Yours/Yours", component: Yours };
export default meta;

export const EmptyState: StoryObj<typeof Yours> = {
  // MockEcosystemClient's default (no initialInstalls) has zero installs
  // for a fresh client instance, so this story exercises F-6's empty state.
  args: { itemType: "skill", onOpen: () => {}, onCreate: () => {}, onDiscover: () => {} },
};
