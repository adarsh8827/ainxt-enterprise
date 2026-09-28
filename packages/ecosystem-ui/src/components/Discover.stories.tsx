// SPDX-License-Identifier: MIT
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Discover } from "./Discover";

const meta: Meta<typeof Discover> = { title: "Discover/Discover", component: Discover };
export default meta;

export const Default: StoryObj<typeof Discover> = {
  args: { itemType: "skill", onOpen: () => {} },
};
