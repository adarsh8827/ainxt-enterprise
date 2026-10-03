// SPDX-License-Identifier: MIT
// User-flow QA round 3 (2026-10-03): no shared Button component existed
// anywhere in this package before this -- every primary/secondary action
// button across AddDialog.tsx, ConfirmDialog.tsx, CreateForm.tsx, Card.tsx,
// Detail.tsx hand-rolled its own near-identical inline style object, which
// is exactly the kind of duplication that lets small inconsistencies (a
// missing font-weight, a missing busy state) drift in at one call site and
// not another. This is additive -- existing bespoke buttons elsewhere in
// the package (menu items, icon-only triggers, the Card's compact
// post-install control) are deliberately left alone; this is for the
// primary/secondary/danger ACTION buttons (dialog confirms, form submits,
// Add/Install) that were the actual target of the "button design" complaint.
//
// Full Tailwind pass (2026-10-03, user ask: "take a reference from
// KnowledgeBase.jsx"): rewritten to literal Tailwind utility classes
// matching that file's/ProductManager.jsx's own buttons exactly --
// `brand-grad hover:opacity-70` solid fill for primary, `bg-white border
// border-gray-300 hover:bg-gray-100` for secondary -- instead of the
// var(--eco-*) CSS-custom-property + dedicated Button.css pseudo-class
// stylesheet this used before. No separate CSS file needed any more:
// Tailwind's hover:/focus:/disabled: variants are the same mechanism ai-ui's
// own native components already use everywhere else.
import { Spinner } from "./Spinner";
const VARIANT_CLASS = {
  primary: "text-white brand-grad hover:opacity-70",
  secondary: "text-gray-700 bg-white border border-gray-300 hover:bg-gray-100",
  danger: "text-white bg-red-600 hover:opacity-70"
};
export function Button({
  variant = "primary",
  loading = false,
  disabled,
  className,
  children,
  ...rest
}) {
  const isDisabled = Boolean(disabled) || loading;
  return <button type="button" disabled={isDisabled} aria-busy={loading || undefined} className={["inline-flex items-center justify-center gap-1.5 px-4 py-2 rounded text-sm font-medium transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-default", VARIANT_CLASS[variant], className].filter(Boolean).join(" ")} {...rest}>
      {loading && <Spinner />}
      {children}
    </button>;
}
