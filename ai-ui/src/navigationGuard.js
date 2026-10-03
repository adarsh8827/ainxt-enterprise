// SPDX-License-Identifier: MIT
// User-flow QA round 8 (2026-10-03, real user question: "when user do
// create a skill using AI... user clicks any other sidemenu, what will
// happen?"): CreateSkillWithAiPage.jsx already guards its own Cancel
// button and tab-close (window.onbeforeunload) against losing an
// in-flight generation/save, but neither covers a SIDEBAR click --
// App.jsx's setView() calls react-router's navigate() directly, in a
// completely different component tree with zero knowledge of this page's
// own `phase` state, so a sidebar click used to abandon the draft
// silently with no warning at all.
//
// A real per-route "block navigation" hook (react-router's useBlocker)
// needs a data router (createBrowserRouter/RouterProvider) -- this app
// uses plain <BrowserRouter> (main.jsx) everywhere else, and switching
// that is a much bigger, riskier change than this one gap calls for. This
// module is the minimal alternative: any page that needs to block an
// in-app navigation attempt registers a guard function here; App.jsx's
// setView() (the one path every sidebar click goes through) awaits it
// before calling navigate(). Scoped deliberately to sidebar/setView
// navigation only -- the browser's own Back/Forward buttons are NOT
// covered by this (popstate has already happened by the time React can
// react to it without a data router), same limitation window.
// onbeforeunload already has for tab-close vs. in-app navigation.
let guard = null;

/** `fn` returns (or resolves to) true to allow the navigation, false to
 * stay put -- e.g. because it showed its own confirm dialog and the
 * caller chose not to leave. Only one guard is ever active at a time
 * (one in-flight-risk page at a time is the only real case today); a
 * newly registered guard replaces whatever was there. */
export function setNavigationGuard(fn) {
  guard = fn;
}

export function clearNavigationGuard() {
  guard = null;
}

export async function confirmNavigationAllowed() {
  if (!guard) return true;
  try {
    return await guard();
  } catch {
    // A guard that throws should never be able to trap the user on the
    // page forever -- fail open.
    return true;
  }
}
