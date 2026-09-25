# LLD — Chat runtime integration

**Purpose**: makes installed, enabled skills actually usable inside a live conversation — a short index entry always present, full content fetched on demand, invocable by name. Entirely inert until an explicit flag is on, and even then scoped to one specific conversation path only. Filled in by tasks B-15, B-16.

## Files / functions
_TBD — B-15, B-16. Note the isolation boundary: the two runtime tools live in their own module, never inside the pre-existing tool-composition registry, and the system-prompt injection only happens in the non-default conversation branch — a separate, unrelated conversation mode is explicitly never touched by this work._

## API and DB changes
_TBD._

## Sequence diagrams
_TBD._

## Edge cases and errors
_TBD — what a tool call does when the referenced item was disabled since the conversation started (pinned-version behavior, not a live re-check every call)._

## Flags
_TBD._

## Tests
_TBD — the flag-off regression suite proving zero behavior change is the most important test in this file; document its exact scope here once it exists._

## How to extend
_TBD._
