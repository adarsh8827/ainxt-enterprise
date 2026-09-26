// SPDX-License-Identifier: MIT
// Item 6 E2E spec: "added in Marketplace -> appears in chat '/' menu
// without reload." Before this task, useEcosystemChatSkills.js only ever
// fetched capabilities once, on mount -- disable-in-chat.spec.ts (task
// B-16/F-11) needed an explicit page.reload() to observe a state change.
// This task adds a live SSE subscription (GET /ecosystem/events/stream,
// task B-13) so an ecosystem.changed event anywhere refetches the "/"
// menu's skill list without a reload. Proven here by opening the chat
// page ONCE, confirming the skill is absent, installing it via the API
// (the same real effect a Marketplace-UI Add click has), and checking
// the already-open page's own slash menu again -- no navigation, no
// page.reload() call anywhere in this spec.
import { test, expect } from '@playwright/test';
import { loginAs, USER_A, API, createResolvedSkill } from './helpers';

test('installing a skill (e.g. from Marketplace) shows it in the already-open chat slash menu live', async ({ page, context }) => {
  await loginAs(context, USER_A);

  const displayName = `Live Update Test ${Date.now()}`;
  const { itemId } = await createResolvedSkill(context.request, { displayName });

  await page.goto('/portal/');
  await page.locator('#chat-input').fill('/');
  await expect(page.getByText(displayName)).not.toBeVisible();
  await page.locator('#chat-input').fill('');

  const versionsResp = await context.request.get(`${API}/ecosystem/items/${itemId}/versions`);
  const versionId = ((await versionsResp.json()).versions ?? [])[0]?.id;
  const installResp = await context.request.post(`${API}/ecosystem/items/${itemId}/install`, {
    data: { version_id: versionId, surfaces: ['chat'], scope: 'private', origin: 'added' },
  });
  expect(installResp.ok(), await installResp.text()).toBeTruthy();

  // No page.reload() / page.goto() between the install above and the
  // check below -- this is the same page instance, still open.
  await page.locator('#chat-input').fill('/');
  await expect(page.getByText(displayName)).toBeVisible({ timeout: 10_000 });
});
