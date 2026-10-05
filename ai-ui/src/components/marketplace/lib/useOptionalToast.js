// SPDX-License-Identifier: MIT
// Toast wiring for install/uninstall/delete-style operations (2026-10-05,
// explicit product ask: "install, uninstall, delete like all the major
// operations success/failure should trigger toast message"). The app
// already has a global toast system -- ai-ui/src/components/ui/
// DialogProvider.jsx's useToast(), mounted once at the app root
// (App.jsx wraps everything in <ToastProvider>) -- so the real app needs
// zero new wiring, just calling it from here.
//
// useToast() throws if there's no <ToastProvider> ancestor. In the real
// app there always is one, but this package's own test suite
// (marketplace-tests/) renders these components in isolation under just
// HostProvider + EcosystemConfigProvider, with no ToastProvider at all --
// and this package is written to be host-embeddable in the first place
// (its own HostContext/useEcosystemClient abstraction exists exactly so it
// doesn't hard-depend on any one app shell). Throwing in either case would
// be wrong: it would crash every existing test that doesn't wrap in
// ToastProvider, and it would crash a future host that doesn't have this
// exact ai-ui toast system. useContext() itself never throws (it just
// returns the provider's default, null, with no provider) -- the throw
// inside useToast() is a plain `if` check AFTER that, so wrapping the
// whole call in try/catch does not skip or conditionally call any hook,
// it only decides whether that subsequent error propagates. Falls back to
// silent no-ops so a toast-less host degrades gracefully instead of
// crashing.
import { useToast } from "../../ui/DialogProvider";

const NOOP_TOAST = {
  success: () => {},
  error: () => {},
  warn: () => {},
  info: () => {}
};

export function useOptionalToast() {
  try {
    // eslint-disable-next-line react-hooks/rules-of-hooks
    return useToast().toast;
  } catch {
    return NOOP_TOAST;
  }
}
