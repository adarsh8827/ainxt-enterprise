// SPDX-License-Identifier: MIT
// M5 E2E spec 3/7: disable a skill -> gone from the chat slash menu
// (task B-16/F-11). One install row covers every surface it's installed
// for (task B-1's own (item_id, org_id, installed_for) uniqueness --
// there is no separate "chat install" vs. "agent_studio install" row for
// the same user/item), so disabling it is enforced live by the resolver
// on every surface that install actually lists, not just chat -- this
// spec proves that by checking both the real chat slash menu (UI) and
// the exact GET /ecosystem/capabilities?surface=agent_studio call
// AgentStudio/frontend's CatalogPicker.jsx (task B-24) makes (API), so
// standing up a second whole frontend app isn't needed for this one
// assertion.
import { test, expect } from '@playwright/test';
import { loginAs, USER_A, API, createResolvedSkill, getInstallId } from './helpers';

test('disabling a skill removes it from both the chat slash menu and the agent_studio capabilities list', async ({ page, context }) => {
  await loginAs(context, USER_A);

  const displayName = `Disable Test ${Date.now()}`;
  const { itemId } = await createResolvedSkill(context.request, { displayName });

  const versionsResp = await context.request.get(`${API}/ecosystem/items/${itemId}/versions`);
  const versions = (await versionsResp.json()).versions ?? [];
  const versionId = versions[0]?.id;

  const installResp = await context.request.post(`${API}/ecosystem/items/${itemId}/install`, {
    data: { version_id: versionId, surfaces: ['chat', 'agent_studio'], scope: 'private', origin: 'added' },
  });
  expect(installResp.ok(), await installResp.text()).toBeTruthy();

  const chatCapsBefore = await context.request.get(`${API}/ecosystem/capabilities`, { params: { surface: 'chat' } });
  expect(((await chatCapsBefore.json()).skills ?? []).some((s: any) => s.display_name === displayName)).toBeTruthy();
  const asCapsBefore = await context.request.get(`${API}/ecosystem/capabilities`, { params: { surface: 'agent_studio' } });
  expect(((await asCapsBefore.json()).skills ?? []).some((s: any) => s.display_name === displayName)).toBeTruthy();

  await page.goto('/portal/');
  await page.locator('#chat-input').fill('/');
  await expect(page.getByText(displayName)).toBeVisible({ timeout: 15_000 });
  await page.locator('#chat-input').fill('');

  const installId = await getInstallId(context.request, itemId);
  const disableResp = await context.request.post(`${API}/ecosystem/installs/${installId}/set-enabled`, { data: { enabled: false } });
  expect(disableResp.ok(), await disableResp.text()).toBeTruthy();

  await page.reload();
  await page.locator('#chat-input').fill('/');
  await expect(page.getByText(displayName)).not.toBeVisible();
  await page.locator('#chat-input').fill('');

  const asCapsAfter = await context.request.get(`${API}/ecosystem/capabilities`, { params: { surface: 'agent_studio' } });
  expect(((await asCapsAfter.json()).skills ?? []).some((s: any) => s.display_name === displayName)).toBeFalsy();
});
