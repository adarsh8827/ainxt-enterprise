// SPDX-License-Identifier: MIT
// M5 E2E spec 4/7: uninstall the caller's last item of a type -> the
// Yours empty state renders (task F-6).
import { test, expect } from '@playwright/test';
import { loginAs, USER_A, API, createResolvedSkill, getInstallId } from './helpers';

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

  // createResolvedSkill's real gate run auto-installs this item only on
  // a pass/warn verdict (task B-10) -- explicitly install if that didn't
  // happen, so this spec doesn't depend on which verdict the real gate
  // reached.
  let installs = (await (await context.request.get(`${API}/ecosystem/installs`)).json()).installs ?? [];
  if (!installs.some((i: any) => i.item_id === itemId)) {
    const versionsResp = await context.request.get(`${API}/ecosystem/items/${itemId}/versions`);
    const versionId = ((await versionsResp.json()).versions ?? [])[0]?.id;
    const installResp = await context.request.post(`${API}/ecosystem/items/${itemId}/install`, {
      data: { version_id: versionId, surfaces: ['chat'], scope: 'private', origin: 'added' },
    });
    expect(installResp.ok(), await installResp.text()).toBeTruthy();
  }
  const installId = await getInstallId(context.request, itemId);

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
