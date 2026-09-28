// SPDX-License-Identifier: MIT
// Item 6 E2E spec: "added in Marketplace -> appears in chat '/' menu
// without reload." Before this task, useEcosystemChatSkills.js only ever
// fetched capabilities once, on mount -- disable-in-chat.spec.ts (task
// B-16/F-11) needed an explicit page.reload() to observe a state change.
// This task adds a live SSE subscription (GET /ecosystem/events/stream,
// task B-13) so an ecosystem.changed event anywhere refetches the "/"
// menu's skill list without a reload.
//
// Reworked (task D): createResolvedSkill() now auto-installs a private,
// no-script skill synchronously via the fast path, so "confirm absent,
// then install, then confirm present" no longer has an absent starting
// point to test from -- the item is already installed+enabled by the
// time the page loads. Enable/disable (task 4's set-enabled, the same
// live-update mechanism, triggered the other direction) reaches the same
// "no page.reload() anywhere in this spec" proof: disable the
// auto-install first, confirm absent, re-enable, confirm present live.
import { test, expect } from '@playwright/test';
import { loginAs, USER_A, API, createResolvedSkill, getInstallId } from './helpers';

test('enabling a skill (e.g. from Marketplace) shows it in the already-open chat slash menu live', async ({ page, context }) => {
  await loginAs(context, USER_A);

  const displayName = `Live Update Test ${Date.now()}`;
  const { itemId } = await createResolvedSkill(context.request, { displayName });
  const installId = await getInstallId(context.request, itemId);

  const disableResp = await context.request.post(`${API}/ecosystem/installs/${installId}/set-enabled`, { data: { enabled: false } });
  expect(disableResp.ok(), await disableResp.text()).toBeTruthy();

  await page.goto('/portal/');
  await page.locator('#chat-input').fill('/');
  await expect(page.getByText(displayName)).not.toBeVisible();
  await page.locator('#chat-input').fill('');

  const enableResp = await context.request.post(`${API}/ecosystem/installs/${installId}/set-enabled`, { data: { enabled: true } });
  expect(enableResp.ok(), await enableResp.text()).toBeTruthy();

  // No page.reload() / page.goto() between the enable above and the
  // check below -- this is the same page instance, still open.
  await page.locator('#chat-input').fill('/');
  await expect(page.getByText(displayName)).toBeVisible({ timeout: 10_000 });
});
