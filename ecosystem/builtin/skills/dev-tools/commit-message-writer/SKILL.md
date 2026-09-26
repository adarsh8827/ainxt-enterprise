---
name: Commit Message Writer
description: Writes a Conventional Commits-style commit message from a description of a code change or a diff.
license: MIT
category: dev-tools
---

# Commit Message Writer

Use this skill when the user describes a code change (in prose, or by
pasting a diff) and wants a commit message for it.

## Format

Follow the Conventional Commits shape:

```
<type>(<scope>): <short summary, imperative mood, under 72 chars>

<optional body, wrapped at ~72 chars, explaining WHY not WHAT>
```

`<type>` is one of: `feat`, `fix`, `docs`, `style`, `refactor`, `test`,
`chore`, `ci`. Pick the one that best matches the change; if genuinely
unclear, ask rather than guessing. `<scope>` is a short, lowercase
identifier for the affected area (a module, package, or feature name) —
omit the scope entirely (`<type>: <summary>`) if the change is broad or a
single clear scope doesn't apply.

## Rules

- The summary line is imperative ("add", "fix", "remove" — not "added",
  "fixes", "removes") and never ends with a period.
- Only write a body if there's a real "why" to explain that the summary
  line doesn't already cover — a one-line change rarely needs one.
- Never mention tooling, assistants, or how the message was produced,
  anywhere in the message.
- If given a diff, base the message on what the diff actually changes —
  don't speculate about intent the diff doesn't support.
