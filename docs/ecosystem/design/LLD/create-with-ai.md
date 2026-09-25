# LLD — Guided creation ("Create with AI")

**Purpose**: a staged, conversational flow for drafting a new skill — the user describes what they want, a generation pipeline proposes a full draft, the user reviews/edits it, and only an explicit confirmation turns it into a real catalog item (which then goes through the same verification gate as anything else). Filled in by task B-14.

## Files / functions
_TBD — B-14. Note the adapter boundary: the drafting service never imports the generation pipeline's code directly — it goes through a small adapter interface, so the integration can change (e.g. from an in-process call to a network call) without touching any caller._

## API and DB changes
_TBD._

## Sequence diagrams
_TBD._

## Edge cases and errors
_TBD — an abandoned draft's cleanup, and duplicate-submission protection._

## Flags
_TBD._

## Tests
_TBD._

## How to extend
_TBD — this is the file to update if the process-model verification this task performed (documented here with its evidence once B-14 lands) is ever invalidated by an infrastructure change elsewhere._
