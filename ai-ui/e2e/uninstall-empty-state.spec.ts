// SPDX-License-Identifier: MIT
// M5 E2E spec 4/7: uninstall the caller's last item of a type -> the
// Yours empty state renders (task F-6).
import { test, expect } from '@playwright/test';
import { loginAs, USER_A, API, createResolvedSkill, ensureInstalled } from './helpers';

test('uninstalling the only installed skill shows the Yours empty state', async ({ page, context }) => {
  await loginAs(context, USER_A);

  // Start from a clean slate: uninstall anything this user already has,
  // so "empty state" is genuinely reachable regardless of prior test runs
  // against the same seeded user.
  const before = await context.request.get(`${API}/ecosystem/installs`, { params: { item_type: 'skill' } });
  for (const install of (await before.json()).installs ?? []) {
    await context.request.post(`${API}/ecosystem/installs/${install.install_id}/uninstall`);
  }

  const { itemId } = await createResolvedSkill(context.request, { displayName: `Uninstall Test ${Date.now()}` });

  // ensureInstalled (not a raw install POST): task D's fast path
  // auto-installs a private, no-script skill synchronously at creation
  // time -- createResolvedSkill() above has already done this by the
  // time control returns here, so a second explicit install call would
  // conflict. ensureInstalled tolerates that and returns the existing
  // install_id.
  const installId = await ensureInstalled(context.request, itemId, { surfaces: ['chat'] });

  await page.goto('/portal/marketplace/skills');
  await page.getByTestId('view-toggle-yours').click();
  await expect(page.getByTestId('yours-install-row')).toBeVisible({ timeout: 15_000 });

  const uninstallResp = await context.request.post(`${API}/ecosystem/installs/${installId}/uninstall`);
  expect(uninstallResp.ok(), await uninstallResp.text()).toBeTruthy();

  await page.reload();
  await page.getByTestId('view-toggle-yours').click();
  await expect(page.getByTestId('yours-empty-state')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('yours-install-row')).not.toBeVisible();
});
