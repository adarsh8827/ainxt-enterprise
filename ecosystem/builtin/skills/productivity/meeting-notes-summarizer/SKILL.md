---
name: Meeting Notes Summarizer
description: Turns raw meeting notes or a transcript into a short summary plus a clear action-item list with owners.
license: MIT
category: productivity
---

# Meeting Notes Summarizer

Use this skill when the user pastes raw meeting notes, a transcript, or a
rough set of bullet points from a meeting and wants a clean summary.

## What to produce

1. **Summary** — 3-6 sentences covering what was discussed and any
   decisions made. Do not simply restate every line; synthesize.
2. **Action items** — a bulleted list, one per concrete task that came out
   of the meeting. Each item should have:
   - The task itself, phrased as a clear instruction.
   - An owner, if one was mentioned or is obvious from context. If no
     owner is stated, write "Unassigned" rather than guessing a name.
   - A due date, only if one was explicitly mentioned.
3. **Open questions** — anything left unresolved that needs a follow-up,
   if any. Omit this section entirely if there were none.

## Rules

- Never invent information that wasn't in the notes. If the notes are too
  sparse to extract a clear action item, say so rather than fabricating one.
- Keep the summary and action items in the same language as the input.
- If the notes contain multiple unrelated topics, group action items under
  a short topic heading for each.
