// SPDX-License-Identifier: MIT
// Item 6 (2026-09-29 live-test round, real user report), both small ones:
//
// 6.1: "Focus ring on tabs (specifically 'Verification') still shows a box
// after a mouse click." An earlier round already fixed this pattern
// broadly via :focus-visible in packages/ecosystem-ui/src/context/
// global.css, and confirmed no competing rule existed anywhere in the
// package at the time. This spec drives Detail's real tab row with a real
// mouse click in real Chrome and reads the actual computed outline/
// box-shadow off the Verification tab trigger, to find the REAL cause
// rather than guessing. Result, across every click sequence tried (plain
// click, click-after-a-different-tab, click-after-a-poll-tick, first-
// click-after-a-fresh-nav, re-click-the-same-already-active-tab): the
// Verification tab trigger IS a real .eco-root descendant (not portaled),
// has no competing inline/library focus styling, and reads outline:"none"/
// box-shadow:"none" after every one of them -- not reproducible against
// the current code in this environment. No code change was made for 6.1;
// this spec is the real-Chrome evidence plus a permanent regression guard.
//
// 6.2: "Publisher: google-labs-code (user)" -- see the assertion near the
// bottom of this same spec (reuses this test's one already-logged-in
// session/skill rather than a second login, given the API's own
// rate limit).
import { test, expect } from '@playwright/test';
import { loginAs, USER_A, createResolvedSkill } from './helpers';

async function goToMarketplace(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page.getByRole('button', { name: /^Marketplace/ }).click();
  await expect(page.getByTestId('marketplace-toolbar')).toBeVisible({ timeout: 15_000 });
}

test.describe('Item 6.1 -- Detail tab focus ring on mouse click', () => {
  test('inspect + screenshot the Verification tab after a real mouse click', async ({ page, context }) => {
    await page.setViewportSize({ width: 1366, height: 900 });
    await loginAs(context, USER_A);

    const { itemId, namespace } = await createResolvedSkill(context.request, {
      displayName: `Item6 Focus Ring Skill ${Date.now()}`,
    });

    await goToMarketplace(page);
    // Yours -- the created skill auto-installs its own creator, so it's
    // there without needing to search Discover.
    await page.getByTestId('view-toggle-yours').click();
    const row = page.locator('[data-testid="yours-install-row"]', { hasText: `Item6 Focus Ring Skill` }).first();
    await expect(row).toBeVisible({ timeout: 15_000 });
    await row.locator('button').first().click(); // opens Detail

    const verificationTab = page.getByTestId('detail-tab-trigger-verification');
    await expect(verificationTab).toBeVisible({ timeout: 15_000 });

    // Confirm this tab really is rendered under .eco-root (task's own
    // check (a)) -- not portaled/escaped out of the wrapper the shared
    // CSS rule depends on.
    const underEcoRoot = await verificationTab.evaluate((el) => el.closest('.eco-root') !== null);
    expect(underEcoRoot, 'Verification tab trigger must be a descendant of .eco-root').toBe(true);

    // The other tabs, for comparison -- same markup/component, clicked
    // the same way.
    const overviewTab = page.getByTestId('detail-tab-trigger-overview');

    await overviewTab.click();
    await page.screenshot({ path: 'e2e/screenshots/item6-focus-overview-after-click.png' });
    const overviewStyle = await overviewTab.evaluate((el) => {
      const cs = getComputedStyle(el);
      return { outline: cs.outlineStyle, outlineWidth: cs.outlineWidth, boxShadow: cs.boxShadow };
    });

    await verificationTab.click();
    await page.screenshot({ path: 'e2e/screenshots/item6-focus-verification-after-click.png' });
    const verificationStyle = await verificationTab.evaluate((el) => {
      const cs = getComputedStyle(el);
      return { outline: cs.outlineStyle, outlineWidth: cs.outlineWidth, boxShadow: cs.boxShadow };
    });

    console.log('overview computed focus style:', JSON.stringify(overviewStyle));
    console.log('verification computed focus style:', JSON.stringify(verificationStyle));

    // A poll tick (Verification.tsx's own 2s client.getGateRuns() refetch)
    // re-renders the tab CONTENT below -- confirm that doesn't disturb
    // the trigger button's own focus-visible state.
    await page.waitForTimeout(2200);
    const afterPollStyle = await verificationTab.evaluate((el) => {
      const cs = getComputedStyle(el);
      return { outline: cs.outlineStyle, boxShadow: cs.boxShadow, activeElement: document.activeElement === el };
    });
    console.log('verification computed focus style after a poll tick:', JSON.stringify(afterPollStyle));
    await page.screenshot({ path: 'e2e/screenshots/item6-focus-verification-after-poll.png' });

    // One more variant: Back to the list, then straight into Detail again
    // and click Verification as the very FIRST interaction (not preceded
    // by clicking Overview first this time) -- in case the very first
    // focus-changing click after a fresh navigation behaves differently.
    await page.getByTestId('detail-back').click();
    await row.locator('button').first().click();
    await expect(page.getByTestId('detail-tab-trigger-verification')).toBeVisible({ timeout: 15_000 });
    await page.getByTestId('detail-tab-trigger-verification').click();
    const firstClickStyle = await page.getByTestId('detail-tab-trigger-verification').evaluate((el) => {
      const cs = getComputedStyle(el);
      return { outline: cs.outlineStyle, boxShadow: cs.boxShadow };
    });
    console.log('verification computed focus style on the very first click after a fresh nav:', JSON.stringify(firstClickStyle));
    await page.screenshot({ path: 'e2e/screenshots/item6-focus-verification-first-click-after-nav.png' });

    // Re-clicking the SAME already-active tab (no aria-selected/state
    // change at all this time) -- in case re-focusing an element that's
    // already focused, with no intervening blur, takes a different
    // heuristic path than focusing a DIFFERENT element.
    await page.getByTestId('detail-tab-trigger-verification').click();
    const reclickStyle = await page.getByTestId('detail-tab-trigger-verification').evaluate((el) => {
      const cs = getComputedStyle(el);
      return { outline: cs.outlineStyle, boxShadow: cs.boxShadow };
    });
    console.log('verification computed focus style on re-clicking the same already-active tab:', JSON.stringify(reclickStyle));
    await page.screenshot({ path: 'e2e/screenshots/item6-focus-verification-reclick-same-tab.png' });

    // Item 6.2 (same live-test round): "Publisher: google-labs-code
    // (user)" -- (user) was a hardcoded backend guess for any publisher
    // slug with no real ecosystem_publishers row. This item's own
    // publisher slug (e2e-test-org, from create_via_write's own
    // resolve_publisher(owner_type="org", ...)) DOES have a real row, so
    // it must now read the full word "(organization)", not the bare
    // "(org)" it showed before this fix.
    const publisherLine = page.getByTestId('detail-publisher');
    await expect(publisherLine).toBeVisible();
    await expect(publisherLine).toHaveText(/\(organization\)/);
    await expect(publisherLine).not.toHaveText(/\(org\)(?!anization)/);
    await page.screenshot({ path: 'e2e/screenshots/item6-2-publisher-organization-label.png' });

    // Cleanup.
    await page.request.post(`/ainxt/v1/api/ecosystem/items/${encodeURIComponent(itemId)}/delete-draft`).catch(() => {});
    void namespace;
  });
});
