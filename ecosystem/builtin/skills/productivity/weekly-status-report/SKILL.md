---
name: Weekly Status Report
description: Drafts a short weekly status update (done / doing / blockers) from a rough list of what happened this week.
license: MIT
category: productivity
---

# Weekly Status Report

Use this skill when the user gives a rough, unstructured list of what they
worked on this week and wants a clean status-report draft.

## Format

Produce exactly three sections, in this order:

```
## Done
- ...

## In progress
- ...

## Blockers / needs help
- ...
```

Omit the "Blockers / needs help" section entirely if nothing in the input
suggests a blocker — don't invent one to fill the template.

## Rules

- Each bullet is one line, specific enough that someone outside the
  immediate work would understand it without extra context (name the
  thing worked on, not just "made progress").
- Group closely related items into one bullet rather than listing every
  small step separately.
- Preserve any concrete numbers, dates, or links the user already gave —
  never drop them for brevity.
- If the input is too vague to produce a real bullet (e.g. "worked on
  stuff"), ask a clarifying question instead of inventing specifics.
