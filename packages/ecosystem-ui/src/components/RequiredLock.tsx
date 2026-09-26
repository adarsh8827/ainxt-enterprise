// SPDX-License-Identifier: MIT
// Task F-6: a small lock glyph + label for scope='required' installs --
// no lucide-react (this package's own rule); @heroicons/react instead
// (verified MIT, see LLD/ui-package.md).
import { LockClosedIcon } from "@heroicons/react/24/solid";

export function RequiredLock() {
  return (
    <span
      data-testid="required-lock"
      title="Required by your organization"
      style={{ display: "inline-flex", alignItems: "center", gap: "4px", color: "var(--eco-color-textMuted)", fontSize: "var(--eco-font-sizeXs)" }}
    >
      <LockClosedIcon width={12} height={12} aria-hidden="true" />
      Required
    </span>
  );
}
