# LLD — Legacy bridge

**Purpose**: surfaces pre-existing, already-governed content in the new marketplace catalog as read-only entries, without ever writing back to (or otherwise affecting the behavior of) the systems that actually own that content. Filled in by task B-4.

## Files / functions
_TBD — B-4._

## API and DB changes
_TBD._

## Sequence diagrams
_TBD._

## Edge cases and errors
_TBD — what happens when a mirrored legacy item fails the verification gate (it must only affect its visibility in this marketplace, never the legacy system itself), and how a legacy item is represented in a user's "Yours" list without fabricating an install action that never happened._

## Flags
_TBD._

## Tests
_TBD._

## How to extend
_TBD — this is the file to update if a future phase decides to bridge a write path in addition to the read path (a decision explicitly deferred, not assumed, as of this writing)._
