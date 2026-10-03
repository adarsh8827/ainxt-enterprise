// SPDX-License-Identifier: MIT
// Task F-6: a small lock glyph + label for scope='required' installs --
// no lucide-react (this package's own rule); @heroicons/react instead
// (verified MIT, see LLD/ui-package.md).
import { LockClosedIcon } from "@heroicons/react/24/solid";
export function RequiredLock() {
  return <span data-testid="required-lock" title="Required by your organization" className="inline-flex items-center gap-1 text-gray-400 text-xs">
      <LockClosedIcon width={12} height={12} aria-hidden="true" />
      Required
    </span>;
}