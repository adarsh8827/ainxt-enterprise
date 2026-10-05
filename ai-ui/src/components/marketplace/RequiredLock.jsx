// SPDX-License-Identifier: MIT
// Task F-6: a small lock glyph + label for scope='required' installs --
// no lucide-react (this package's own rule); @heroicons/react instead
// (verified MIT, see LLD/ui-package.md).
import { LockClosedIcon } from "@heroicons/react/24/solid";
// Card density pass (2026-10-05): icon + tooltip only, "Required" moves to
// an sr-only span -- the lock glyph alone already reads clearly next to a
// skill name, and this keeps it consistent with VerdictIcon/StatusChip's
// own icon-plus-sr-only-text convention elsewhere in this redesign.
export function RequiredLock() {
  return <span data-testid="required-lock" title="Required by your organization" className="inline-flex items-center text-gray-400 flex-shrink-0">
      <LockClosedIcon width={13} height={13} aria-hidden="true" />
      <span className="sr-only">Required</span>
    </span>;
}