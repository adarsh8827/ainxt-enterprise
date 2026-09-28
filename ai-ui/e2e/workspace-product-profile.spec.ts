// SPDX-License-Identifier: MIT
// M5 E2E spec 6/7: with a workspace-shaped config, only that profile's
// entitled features render (task F-12). Targets the F-12 example host
// (packages/ecosystem-ui/examples/workspace-host, `npm run
// example:workspace`, default port 5174) directly -- a *different* app
// from ai-ui, so this spec overrides the shared baseURL with an
// absolute URL rather than relying on playwright.config.ts's default.
// Zero backend dependency: the host defaults to an in-memory
// MockEcosystemClient seeded with MOCK_CONFIG_WORKSPACE (the real
// `workspace` product-profile shape, CONFIG_AND_PRODUCTS.md §3).
import { test, expect } from '@playwright/test';

const WORKSPACE_HOST = process.env.WORKSPACE_HOST_URL || 'http://localhost:5174';

test.describe('workspace product profile (F-12 example host)', () => {
  test('the skills catalog renders in compact layout with only the entitled item type available', async ({ page }) => {
    await page.goto(`${WORKSPACE_HOST}/skills`);
    await expect(page.getByTestId('marketplace-root')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId('catalog-screen')).toBeVisible();

    // Add menu: "Write"/"Upload" on (workspace's own features.write/upload),
    // "Import from URL" off (features.import_url: false for every profile
    // this phase, not just workspace-specific -- still worth asserting).
    await page.getByTestId('add-menu-trigger').click();
    await expect(page.getByTestId('add-menu-new')).toBeEnabled();
    await expect(page.getByTestId('add-menu-upload')).toBeEnabled();
    await expect(page.getByTestId('add-menu-import')).toBeDisabled();
  });

  test('admin screens are unreachable under the workspace profile (admin_policies: false)', async ({ page }) => {
    await page.goto(`${WORKSPACE_HOST}/admin/policies`);
    await expect(page.getByTestId('admin-not-available')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId('admin-policies')).not.toBeVisible();
  });

  test('the other item types still render as coming-soon, not hidden', async ({ page }) => {
    await page.goto(`${WORKSPACE_HOST}/plugins`);
    await expect(page.getByTestId('marketplace-root')).toBeVisible({ timeout: 15_000 });
    // ComingSoonTab.tsx renders for a "coming_soon" item_types[].state entry
    // -- present in every profile's item_types this phase, workspace
    // included (ECOSYSTEM_TYPE_PLUGIN etc. are off repo-wide, not a
    // per-product distinction).
    await expect(page.getByTestId('coming-soon-tab')).toBeVisible();
  });
});
