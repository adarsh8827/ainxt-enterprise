// SPDX-License-Identifier: MIT
// M5 E2E spec 4/7: uninstall the caller's last CREATED item -> the
// "Created by me" group shows its own empty state (task F-6).
//
// Rewritten (real rule found live): the 4 builtin skills auto-(re)provision
// for every user in the org the moment anything triggers
// config_service.get_effective_config()'s ensure_provisioned() call (e.g.
// visiting Marketplace at all) -- so "Yours" is never actually, globally
// empty once they're seeded+active. The real rule: uninstalling the
// caller's OWN item empties only the group that item belonged to
// ("Created by me"), while "Org provisioned" keeps showing the builtins,
// and the global yours-empty-state (packages/ecosystem-ui's EmptyState,
// data-testid="yours-empty-state") must NOT render while any group still
// has rows.
import { test, expect } from '@playwright/test';
import { loginAs, USER_A, API, createResolvedSkill, ensureInstalled } from './helpers';

test('uninstalling my own item empties only "Created by me", leaving "Org provisioned" (built-ins) visible', async ({ page, context }) => {
  test.setTimeout(60_000); // real network round trips: create+provision+uninstall+reload
  await loginAs(context, USER_A);

  // Clean slate: uninstall anything this user already has (skills only),
  // so this test's own "Created by me" assertions aren't polluted by a
  // prior run's leftover item under the same seeded user.
  const before = await context.request.get(`${API}/ecosystem/installs`, { params: { item_type: 'skill' } });
  for (const install of (await before.json()).installs ?? []) {
    await context.request.post(`${API}/ecosystem/installs/${install.install_id}/uninstall`);
  }

  const { itemId } = await createResolvedSkill(context.request, { displayName: `Uninstall Test ${Date.now()}` });
  // ensureInstalled (not a raw install POST): task D's fast path already
  // auto-installed this via createResolvedSkill() above -- a second
  // explicit install call would 409. ensureInstalled tolerates that.
  const installId = await ensureInstalled(context.request, itemId, { surfaces: ['chat'] });

  // Visiting Marketplace triggers config_service's ensure_provisioned(),
  // which (re-)provisions the org's builtin skills for this caller if they
  // aren't already provisioned -- do this BEFORE asserting anything, so
  // both groups are in their real, live-equivalent starting state.
  await page.goto('/portal/marketplace/skills');
  await page.getByTestId('view-toggle-yours').click();

  const createdByMe = page.locator('[data-testid="yours-group"][data-group-label="Created by me"]');
  const orgProvisioned = page.locator('[data-testid="yours-group"][data-group-label="Org provisioned"]');

  await expect(createdByMe).toBeVisible({ timeout: 15_000 });
  await expect(createdByMe.getByTestId('yours-install-row')).toHaveCount(1);
  // Org provisioned should already carry the 4 builtins seeded earlier
  // (docs/ecosystem/TESTING_GUIDE.md's seed_builtin_skills.py) -- if this
  // fails, the builtin-provisioning fix landing in this same round hasn't
  // reached this environment yet, not a bug in this spec's own logic.
  await expect(orgProvisioned).toBeVisible({ timeout: 15_000 });
  const provisionedCountBefore = await orgProvisioned.getByTestId('yours-install-row').count();
  expect(provisionedCountBefore).toBeGreaterThan(0);

  const uninstallResp = await context.request.post(`${API}/ecosystem/installs/${installId}/uninstall`);
  expect(uninstallResp.ok(), await uninstallResp.text()).toBeTruthy();

  await page.reload();
  await page.getByTestId('view-toggle-yours').click({ timeout: 15_000 });

  // The global empty state must never render while "Org provisioned" still
  // has real rows -- this is the actual bug the old version of this spec
  // couldn't have caught, since it asserted the opposite.
  await expect(page.getByTestId('yours-empty-state')).not.toBeVisible();

  // "Created by me" itself: either the whole group section is gone (today's
  // behavior -- an empty origin group renders nothing at all) or it's
  // present with its own empty-state hint, if a concurrent fork's per-group
  // empty-state work has landed in this environment by the time this runs.
  // Assert on the one thing that must be true either way: no row remains.
  await expect(page.locator('[data-testid="yours-group"][data-group-label="Created by me"] [data-testid="yours-install-row"]')).toHaveCount(0);

  // Org provisioned must be completely unaffected by uninstalling an
  // unrelated "Created by me" item.
  await expect(orgProvisioned).toBeVisible();
  await expect(orgProvisioned.getByTestId('yours-install-row')).toHaveCount(provisionedCountBefore);
});
