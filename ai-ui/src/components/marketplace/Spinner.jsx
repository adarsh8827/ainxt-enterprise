// SPDX-License-Identifier: MIT
// User-flow QA round 3 (2026-10-03): no busy/spinner indicator existed
// anywhere in this package before this -- every in-flight button only
// swapped its own text (e.g. "Add" -> "Adding…"), which a real double-click
// could still slip past visually before the disabled attribute registers
// in slower conditions. A self-contained inline SVG with an SMIL
// <animateTransform> (not a CSS @keyframes class) is deliberate: this
// package injects no global stylesheet of its own (every style is inline,
// scoped per element, host-agnostic by design -- see theme.ts's own
// header), so a CSS-keyframe-based spinner would need a one-off <style>
// tag injection this package doesn't do anywhere else. SMIL needs nothing
// external and uses currentColor, so it inherits whatever text color the
// surrounding button already set (works unmodified on a filled primary
// button and an outlined secondary button alike).
export function Spinner({
  size = 14
}) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true" style={{
    flexShrink: 0
  }}>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" opacity="0.25" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round">
        <animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur="0.7s" repeatCount="indefinite" />
      </path>
    </svg>;
}