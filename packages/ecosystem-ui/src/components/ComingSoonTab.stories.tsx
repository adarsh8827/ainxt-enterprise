// SPDX-License-Identifier: MIT
import type { Meta, StoryObj } from "@storybook/react-vite";
import { ComingSoonTab } from "./ComingSoonTab";

const meta: Meta<typeof ComingSoonTab> = { title: "Discover/ComingSoonTab", component: ComingSoonTab };
export default meta;

export const Plugin: StoryObj<typeof ComingSoonTab> = { args: { itemType: "plugin" } };
export const Connector: StoryObj<typeof ComingSoonTab> = { args: { itemType: "connector" } };
export const McpServer: StoryObj<typeof ComingSoonTab> = { args: { itemType: "mcp_server" } };
