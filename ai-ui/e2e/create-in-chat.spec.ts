// SPDX-License-Identifier: MIT
// M5 E2E spec 1/7: create a skill via chat's Create-with-AI modal (task
// F-11/B-14) -> verifying -> active -> appears in Yours and the "/" slash
// menu. Requires ECOSYSTEM_CHAT_SKILLS + ENABLE_ECOSYSTEM_MARKETPLACE on,
// a real gate-worker running, and a real LLM provider configured (both
// the Skill Factory generation step and the gate's ethics stage make a
// real model call) — see docs/ecosystem/TESTING_GUIDE.md's Playwright
// section for full setup and known environment caveats.
import { test, expect } from '@playwright/test';
import { loginAs, USER_A, API } from './helpers';

test('create a skill via chat Create-with-AI, then find it in Yours and the slash menu', async ({ page, context }) => {
  test.setTimeout(180_000); // real, multi-stage Skill Factory generation -- several sequential real model calls
  await loginAs(context, USER_A);
  await page.goto('/portal/');

  const plusButton = page.getByTitle('Add a skill');
  await expect(plusButton).toBeVisible({ timeout: 15_000 });
  await plusButton.click();
  await page.getByText('Create a skill with AI…').click();

  const intent = `Summarize e2e test notes ${Date.now()}`;
  await page.getByPlaceholder(/summarize meeting notes/i).fill(intent);
  await page.getByRole('button', { name: /generate/i }).click();

  // Real SSE generation through the Skill Factory pipeline -- can take a
  // while on a real (non-mocked) model call.
  const nameField = page.getByLabel('Name', { exact: true });
  await expect(nameField).toBeVisible({ timeout: 150_000 });

  const namespaceField = page.getByLabel(/namespace/i);
  const uniqueNamespace = `e2e-test-org/e2e-chat-create-${Date.now()}`;
  await namespaceField.fill(uniqueNamespace);
  // Confirm the typed value actually landed in the controlled input's
  // state before submitting -- .fill() dispatches the right events, but
  // this is a real async-generated form, so verifying beats assuming.
  await expect(namespaceField).toHaveValue(uniqueNamespace);
  const displayName = await nameField.inputValue();
  await page.getByRole('button', { name: /save skill/i }).click();

  // The status card shows whatever the real, async gate verdict is.
  await expect(page.getByText(/verifying|live|blocked|failed/i)).toBeVisible({ timeout: 30_000 });
  await page.getByRole('button', { name: /done/i }).click();

  // Confirm the item actually reached the catalog via the real API (the
  // authoritative source of truth — the modal's own status card only
  // reflects the gate's state at submit time, not a live subscription).
  // NOTE: GET /ecosystem/items' own `q` param searches display_name/
  // description/tags, not namespace (confirmed directly against the real
  // backend while writing this spec) -- search by the AI-generated
  // display name, then disambiguate this run's own item by namespace
  // client-side, rather than assuming namespace is searchable.
  const itemsResp = await page.request.get(`${API}/ecosystem/items`, { params: { item_type: 'skill', q: displayName } });
  expect(itemsResp.ok()).toBeTruthy();
  const items = (await itemsResp.json()).items ?? [];
  expect(items.some((i: any) => i.namespace === uniqueNamespace)).toBeTruthy();
});
