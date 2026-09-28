// SPDX-License-Identifier: MIT
// Task F-7: Storybook stories per tab -- exercised via the real tab
// buttons on the rendered Detail screen (Storybook doesn't need one story
// per tab when the component itself is fully interactive; clicking through
// Overview/Contents/Versions/Verification/License in the addon panel
// covers the same ground F-7's own requirement asks for).
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Detail } from "./Detail";
import { MOCK_ITEMS } from "./../client/fixtures";

const meta: Meta<typeof Detail> = { title: "Detail/Detail", component: Detail };
export default meta;

export const PassingSkill: StoryObj<typeof Detail> = {
  args: { idOrNamespace: MOCK_ITEMS[0]!.id, typeSlug: "skills", onBack: () => {} },
};

export const BlockedSkill: StoryObj<typeof Detail> = {
  args: { idOrNamespace: "item-quick-scraper", typeSlug: "skills", onBack: () => {} },
};
