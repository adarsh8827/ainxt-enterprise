// SPDX-License-Identifier: MIT
// Task 3a: admin Sources screen -- real-render story, backed by the
// default MockEcosystemClient (fixtures.ts's MOCK_ADMIN_SOURCES).
import type { Meta, StoryObj } from "@storybook/react-vite";
import { AdminSources } from "./AdminSources";

const meta: Meta<typeof AdminSources> = { title: "Admin/Sources", component: AdminSources };
export default meta;

export const Default: StoryObj = { render: () => <AdminSources /> };
