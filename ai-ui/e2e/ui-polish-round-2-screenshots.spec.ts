// SPDX-License-Identifier: MIT
// Real-screenshot verification for the M5 UI-polish round 2 fixes
// (2026-09-28): Yours list-view CSS-grid rewrite, standard button sizing,
// the removed stray toolbar divider, and a Delete-permanently end-to-end
// check in LIST view specifically (the real bug report was list-view-only).
//
// Uses the throwaway e2e-test-org fixture user/skill (helpers.ts) for the
// delete check -- deliberately NOT the real user-reported item
// (default/sravanan-personal-assistant) this round's report is actually
// about. That real item belongs to a real account this environment has no
// credentials for; destroying or even just driving real user data through
// an automated script would be irresponsible regardless of credentials.
// This spec instead proves the same code path (list-view Delete
// permanently, wired from allowed_actions) works end to end against a
// disposable item, which is the strongest verification available without
// real user credentials.
import { test, expect, type Page } from '@playwright/test';
import { loginAs, USER_A, createResolvedSkill } from './helpers';

const VIEWPORTS = [
  { name: '1366', width: 1366, height: 900 },
  { name: '1920', width: 1920, height: 1080 },
];

/** Real bug found writing this spec: `page.goto('/marketplace/skills')`
 * lands on this app's default view (Chat) instead -- Sidebar.jsx's own
 * client-side `view` state (not the URL) drives which screen renders, so
 * a cold navigation has to actually click the sidebar's "Marketplace" nav
 * item the way a real user would, not assume a direct URL works. */
async function goToMarketplace(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: /^Marketplace/ }).click();
  await expect(page.getByTestId('marketplace-toolbar')).toBeVisible({ timeout: 15_000 });
}

test.describe('UI-polish round 2 -- real screenshots', () => {
  for (const vp of VIEWPORTS) {
    test(`Discover + Yours (grid/list) render correctly at ${vp.name}px`, async ({ page, context }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await loginAs(context, USER_A);

      const { itemId, namespace } = await createResolvedSkill(context.request, {
        displayName: `UI Polish Round 2 Screenshot Skill ${Date.now()}`,
      });

      await goToMarketplace(page);

      // Discover
      const discoverToggle = page.getByTestId('view-toggle-discover');
      await discoverToggle.click();
      await expect(page.getByTestId('marketplace-toolbar-bar')).toBeVisible();
      // Real bug in this spec's own first draft: screenshotting immediately
      // after the click caught Discover's transient "Verifying..." loading
      // state instead of real content -- wait for that to clear first.
      await expect(page.getByTestId('discover-loading')).not.toBeVisible({ timeout: 15_000 });
      await page.screenshot({ path: `e2e/screenshots/discover-${vp.name}.png`, fullPage: true });

      // Yours -- grid (default)
      const yoursToggle = page.getByTestId('view-toggle-yours');
      await yoursToggle.click();
      const gridRow = page.locator(`[data-testid="yours-install-row"][data-install-id]`).first();
      await expect(gridRow).toBeVisible({ timeout: 15_000 });
      await expect(page.getByTestId('yours-layout-grid')).toBeVisible();
      await page.screenshot({ path: `e2e/screenshots/yours-grid-${vp.name}.png`, fullPage: true });

      // Yours -- list
      await page.getByTestId('yours-layout-list').click();
      await expect(page.locator('[data-testid="yours-install-row"]').first()).toHaveAttribute('data-layout', 'list');
      await page.screenshot({ path: `e2e/screenshots/yours-list-${vp.name}.png`, fullPage: true });

      // No horizontal overflow at either width -- the actual complaint
      // ("no horizontal page overflow at 1366 or 1920px").
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
      expect(overflow, `horizontal overflow detected at ${vp.width}px`).toBe(false);

      // Cleanup: this test's own throwaway item, not left behind for the
      // next run (namespace includes a timestamp so it never collides).
      await page.request.post(`/ainxt/v1/api/ecosystem/items/${encodeURIComponent(itemId)}/delete-draft`).catch(() => {});
      void namespace;
    });
  }

  test('Delete permanently works end to end in LIST view for a disposable item', async ({ page, context }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await loginAs(context, USER_A);

    const displayName = `Delete E2E List View ${Date.now()}`;
    await createResolvedSkill(context.request, { displayName });

    await goToMarketplace(page);
    await page.getByTestId('view-toggle-yours').click();
    await page.getByTestId('yours-layout-list').click();

    const row = page.locator('[data-testid="yours-install-row"]', { hasText: displayName });
    await expect(row).toBeVisible({ timeout: 15_000 });

    // The actions column (Installed + kebab) must actually be present in
    // LIST view -- the exact thing the user's own report questioned
    // ("own skill shows no actions column in list view").
    await expect(row.getByTestId('detail-installed-trigger')).toBeVisible();
    await expect(row.getByTestId('kebab-trigger')).toBeVisible();

    await row.getByTestId('kebab-trigger').click();
    await page.getByText('Delete permanently', { exact: true }).click();
    await expect(page.getByTestId('confirm-dialog')).toBeVisible();
    await page.getByTestId('confirm-dialog-confirm').click();

    await expect(row).not.toBeVisible({ timeout: 15_000 });
  });
});
