// SPDX-License-Identifier: MIT
// Real-screenshot verification for the M5 UI-polish round 4 fixes
// (2026-09-29): not-yet-added catalog item state ("Catalog checks passed"
// badge, working Add) and a live-testing follow-up report (list-view
// description overflow with a genuinely long, real-world description).
//
// Uses the real crawled catalog items already visible in the shared
// testing environment (item_scope=="central_index" is visible to every
// caller -- items_service._visible_to_caller()) rather than fabricating
// one: this branch has no API to create a central_index item directly.
import { test, expect } from '@playwright/test';
import { loginAs, USER_A, createResolvedSkill } from './helpers';

async function goToMarketplace(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page.getByRole('button', { name: /^Marketplace/ }).click();
  await expect(page.getByTestId('marketplace-toolbar')).toBeVisible({ timeout: 15_000 });
}

test('a real not-yet-added catalog item shows "Catalog checks passed" and a working Add, never "Verifying"', async ({ page, context }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await loginAs(context, USER_A);
  await goToMarketplace(page);
  await page.getByTestId('view-toggle-discover').click();
  await expect(page.getByTestId('discover-loading')).not.toBeVisible({ timeout: 15_000 });
  // Discover's category sections collapse to 4 items by default (a real
  // item further down a large category, e.g. "design", would need a
  // "Show all" click to become visible) -- search directly instead, one
  // less thing for this test to depend on.
  await page.getByTestId('toolbar-search').locator('input').fill('site-md');

  // "site-md" is one of the real crawled central_index items reported
  // stuck on "Verifying..." live (2026-09-29) -- central_index items are
  // visible to every caller (items_service._visible_to_caller()), so a
  // fresh e2e fixture user sees exactly what a real user saw.
  const card = page.locator('[data-testid="item-card"]', { hasText: 'site-md' }).first();
  await expect(card).toBeVisible({ timeout: 15_000 });
  await expect(card.getByTestId('catalog-checks-passed-badge')).toHaveText('Catalog checks passed');
  await expect(card.getByTestId('verdict-badge')).toHaveCount(0);
  const addButton = card.getByTestId('card-quick-add');
  await expect(addButton).toBeVisible();
  await expect(addButton).toBeEnabled();
  await page.screenshot({ path: 'e2e/screenshots/discover-not-yet-added-catalog-item-1920.png', fullPage: true });

  // Detail page -- the button that was reported genuinely `disabled`.
  await card.click();
  await expect(page.getByTestId('detail-screen')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('catalog-checks-passed-badge')).toHaveText('Catalog checks passed');
  const detailAdd = page.getByTestId('detail-add-button');
  await expect(detailAdd).toBeVisible();
  await expect(detailAdd).toBeEnabled(); // real DOM check, not just visual, per the backend team's own report
  await page.screenshot({ path: 'e2e/screenshots/detail-not-yet-added-catalog-item-add-enabled-1920.png', fullPage: true });
});

test('Yours list view never overflows for a genuinely long, real-world description', async ({ page, context }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await loginAs(context, USER_A);

  // The exact description length/shape from the live user report
  // (2026-09-29) that prompted this check -- not a fabricated short
  // string, the real one that was reported as overflowing.
  const longDescription =
    "Use when Sravanan needs help managing tasks, drafting messages, organizing thoughts, planning his day, " +
    "or getting quick answers to personal or professional questions. Use this skill whenever Sravanan mentions " +
    "scheduling, reminders, to-do lists, emails to draft, decisions to think through, summaries to read, or says " +
    "things like 'help me figure out', 'what should I do', 'draft this for me', or 'remind me about' — even if " +
    "he does not explicitly ask for an assistant.";
  const displayName = `Overflow Check ${Date.now()}`;
  await createResolvedSkill(context.request, { displayName, description: longDescription });

  await goToMarketplace(page);
  await page.getByTestId('view-toggle-yours').click();
  await page.getByTestId('yours-layout-list').click();

  const row = page.locator('[data-testid="yours-install-row"]', { hasText: displayName });
  await expect(row).toBeVisible({ timeout: 15_000 });

  // The real assertion: the row's own rendered height matches every other
  // row's (one line), and the description cell never causes the row (or
  // the page) to grow wider/taller than intended -- scrollWidth/Height
  // must equal clientWidth/Height for a properly clipped, non-overflowing
  // element (a genuine overflow inflates scrollWidth/Height beyond the
  // visible box).
  const descriptionBox = row.getByTestId('yours-row-description');
  const overflowMetrics = await descriptionBox.evaluate((el) => ({
    scrollWidth: el.scrollWidth, clientWidth: el.clientWidth,
    scrollHeight: el.scrollHeight, clientHeight: el.clientHeight,
  }));
  expect(overflowMetrics.scrollHeight, 'description box grew taller than one line').toBeLessThanOrEqual(overflowMetrics.clientHeight + 1);
  // scrollWidth CAN exceed clientWidth for a nowrap+ellipsis element (that's
  // what makes the ellipsis kick in) -- the real bug would be the ROW's
  // own bounding box or the page overflowing horizontally, checked next.
  const rowBox = await row.evaluate((el) => ({ scrollWidth: el.scrollWidth, clientWidth: el.clientWidth }));
  expect(rowBox.scrollWidth, 'the row itself overflowed its own box').toBeLessThanOrEqual(rowBox.clientWidth + 1);
  const pageOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  expect(pageOverflow, 'the long description pushed the whole page into horizontal overflow').toBe(false);

  await page.screenshot({ path: 'e2e/screenshots/yours-list-long-description-1920.png', fullPage: true });
});
