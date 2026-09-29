// SPDX-License-Identifier: MIT
// Install-state-consistency round (2026-09-29): real bug reported live --
// "installed a catalog skill, uninstalled it from Yours (worked), went
// back to Discover -> it still shows Installed and can't be removed
// there." Real-Chrome verification against the real backend, using a
// REAL crawled catalog item (matching the user's own exact repro --
// "I installed a catalog skill", not a self-authored private item, which
// items_service.list_items() deliberately never surfaces in Discover at
// all regardless of this fix, found live while writing this spec).
// Discover picks up a mutation made on Yours (and vice versa) with NO
// manual reload, and Discover's own card can now uninstall directly too.
import { test, expect } from '@playwright/test';
import { loginAs, USER_A } from './helpers';

async function goToMarketplace(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page.getByRole('button', { name: /^Marketplace/ }).click();
  await expect(page.getByTestId('marketplace-toolbar')).toBeVisible({ timeout: 15_000 });
}

/** Finds a real catalog item this caller hasn't installed yet, uniquely
 * searchable by its own display_name -- this shared test org's catalog
 * has accumulated hundreds of items over this session's many rounds, so
 * Discover's default browse view (limit 200, sorted featured) can't be
 * relied on to include any one specific item; every lookup here goes
 * through the same search box the UI itself uses. */
async function findAnUninstalledCatalogItem(request: import('@playwright/test').APIRequestContext): Promise<string> {
  const resp = await request.get('/ainxt/v1/api/ecosystem/items?item_type=skill&limit=50&sort=name');
  expect(resp.ok(), await resp.text()).toBeTruthy();
  const body = await resp.json();
  const candidate = (body.items ?? []).find((i: any) => !i.install_id && (i.allowed_actions ?? []).includes('install'));
  if (!candidate) throw new Error('no not-yet-installed catalog item found in this org -- cannot run this spec');
  return candidate.display_name as string;
}

test.describe('Install state stays consistent between Discover and Yours -- real screenshots', () => {
  test('add -> uninstall from Yours -> Discover shows + Add, with no reload', async ({ page, context }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await loginAs(context, USER_A);
    const displayName = await findAnUninstalledCatalogItem(context.request);

    await goToMarketplace(page);
    await page.getByTestId('view-toggle-discover').click();
    await expect(page.getByTestId('discover-screen')).toBeVisible({ timeout: 15_000 });
    await page.getByTestId('toolbar-search').locator('input').fill(displayName);

    const discoverCard = page.locator('[data-testid="item-card"]', { hasText: displayName });
    await expect(discoverCard).toBeVisible({ timeout: 15_000 });
    await discoverCard.getByTestId('card-quick-add').click();

    // Real gap this round closes: Discover's own card used to show a
    // read-only "Added" badge with no way to remove it at all.
    await expect(discoverCard.getByTestId('card-uninstall')).toBeVisible({ timeout: 15_000 });
    await page.screenshot({ path: 'e2e/screenshots/install-consistency-discover-shows-added.png', fullPage: true });

    // Discover -> Yours: uninstall it from there instead (the user's own
    // real repro path).
    await page.getByTestId('view-toggle-yours').click();
    await expect(page.getByTestId('yours-screen')).toBeVisible({ timeout: 15_000 });
    const yoursRow = page.locator('[data-testid="yours-install-row"]', { hasText: displayName });
    await expect(yoursRow).toBeVisible({ timeout: 15_000 });
    await yoursRow.getByTestId('detail-installed-trigger').click();
    await page.getByRole('menuitem', { name: 'Uninstall' }).click();
    await expect(yoursRow).toHaveCount(0, { timeout: 10_000 });
    await page.screenshot({ path: 'e2e/screenshots/install-consistency-yours-after-uninstall.png', fullPage: true });

    // Yours -> Discover: the real assertion. No manual reload anywhere in
    // this spec -- a plain tab switch (CatalogScreen.tsx's own conditional
    // render, a real remount) must show "+ Add" immediately, never a
    // stale "Added" badge or an uninstall button pointed at a now-gone
    // install id.
    await page.getByTestId('view-toggle-discover').click();
    await page.getByTestId('toolbar-search').locator('input').fill(displayName);
    const discoverCardAgain = page.locator('[data-testid="item-card"]', { hasText: displayName });
    await expect(discoverCardAgain).toBeVisible({ timeout: 15_000 });
    await expect(discoverCardAgain.getByTestId('card-quick-add')).toBeVisible({ timeout: 15_000 });
    await expect(discoverCardAgain.getByTestId('card-installed-badge')).toHaveCount(0);
    await expect(discoverCardAgain.getByTestId('card-uninstall')).toHaveCount(0);
    await page.screenshot({ path: 'e2e/screenshots/install-consistency-discover-corrected.png', fullPage: true });
  });

  test('uninstall from Discover itself works', async ({ page, context }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await loginAs(context, USER_A);
    const displayName = await findAnUninstalledCatalogItem(context.request);

    await goToMarketplace(page);
    await page.getByTestId('view-toggle-discover').click();
    await page.getByTestId('toolbar-search').locator('input').fill(displayName);
    const card = page.locator('[data-testid="item-card"]', { hasText: displayName });
    await expect(card).toBeVisible({ timeout: 15_000 });
    await card.getByTestId('card-quick-add').click();
    await expect(card.getByTestId('card-uninstall')).toBeVisible({ timeout: 15_000 });

    await card.getByTestId('card-uninstall').click();
    await expect(card.getByTestId('card-quick-add')).toBeVisible({ timeout: 10_000 });
    await expect(card.getByTestId('card-uninstall')).toHaveCount(0);
    await page.screenshot({ path: 'e2e/screenshots/install-consistency-uninstalled-from-discover.png', fullPage: true });
  });
});
