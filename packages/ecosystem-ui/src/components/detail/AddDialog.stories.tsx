// SPDX-License-Identifier: MIT
import type { Meta, StoryObj } from "@storybook/react-vite";
import { AddDialog } from "./AddDialog";
import { MOCK_DETAILS } from "../../client/fixtures";

const meta: Meta<typeof AddDialog> = { title: "Detail/AddDialog", component: AddDialog };
export default meta;

const ITEM = Object.values(MOCK_DETAILS)[0]!;

// Renders under the global Storybook decorator's own MOCK_CONFIG, whose
// caller_permissions default to {can_share:true, can_provision:true} --
// showing the full scope option set (matching an admin caller, per
// AddDialog.tsx's own gating).
export const Default: StoryObj<typeof AddDialog> = {
  args: { item: ITEM, versionId: "v1", defaultSurfaces: ["chat"], onClose: () => {}, onInstalled: () => {} },
};

export const WarnVerdict: StoryObj<typeof AddDialog> = {
  args: { item: { ...ITEM, latest_verdict: "warn" }, versionId: "v1", defaultSurfaces: ["chat"], onClose: () => {}, onInstalled: () => {} },
};
