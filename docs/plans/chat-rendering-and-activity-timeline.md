# Plan: Chat Rendering and Activity Timeline

## Context

The chat UI exposes useful execution evidence, but the current presentation
mixes the assistant's working narration with its answer and loses the original
ordering between text and tool calls.

The most recent production conversation inspected on 2026-07-14 showed the
failure mode clearly:

- a single assistant turn contained 19 tool calls;
- progress phrases such as "Let me check..." and "Perfect!" were stored in the
  same `content` field as the conclusion;
- every tool call was rendered before the entire text response rather than at
  the point where it occurred;
- valid GitHub-flavored Markdown tables were displayed as pipe-delimited text;
- repeated tool calls formed a long stack of nearly identical controls;
- the two sidebars left too little message width at a narrow desktop viewport.

This is not solely a CSS issue. `Chat.tsx` accumulates `content_delta` events
into one string and `tool_use` events into a separate array. The API persists
the same split as `chat_messages.content` plus `metadata.tool_calls`. Neither
representation retains the sequence needed to reconstruct an inline trace.

## Goals

1. Make the final answer the primary reading surface.
2. Preserve tool activity for audit and diagnosis without making raw execution
   output dominate the conversation.
3. Retain the original order of progress text, tool calls, tool results, and
   the final answer during streaming and after reload.
4. Render standard Markdown, including tables, lists, links, and fenced code,
   consistently and safely.
5. Keep long and narrow conversations usable and accessible.

## Non-goals

- Hiding tool activity or removing forensic detail.
- Exposing hidden model chain-of-thought. The UI should show observable
  activity and concise progress text emitted by the assistant, not describe it
  as privileged internal reasoning.
- Redesigning the overall Observatory navigation shell.
- Changing the chat agent's available tools or authorization policy.

## Terminology

Use **Activity** or **Work log** in the interface. Avoid **Thinking** because
the stored text is an execution narration, not a reliable representation of a
model's internal reasoning.

## Proposal

Implement the work in two increments. The first improves the current UI without
changing persistence. The second introduces the ordered model required for a
correct activity timeline.

### Increment 1: Rendering and responsive cleanup

#### Markdown

Replace the regular-expression renderer in `src/frontend/src/pages/Chat.tsx`
with `react-markdown` and `remark-gfm`.

- Do not enable raw HTML.
- Provide explicit renderers for links, fenced code, inline code, and tables.
- Open external links with safe `rel` attributes.
- Give tables horizontal overflow inside the message rather than on the page.
- Give code blocks horizontal overflow, a language label when available, and a
  Copy action.
- Reuse the same Markdown component in Knowledge Base instead of maintaining
  two independent regular-expression renderers.

#### Activity summary

For messages that have tool calls, replace the stack of individual collapsed
cards with one summary row:

```text
Activity · 19 tool calls · completed                         [Expand]
```

When expanded, show the existing calls as a vertical timeline. Each compact
row should contain:

- status icon (`running`, `succeeded`, or `failed`);
- human-readable tool name;
- a short parameter summary, such as a path, query, repository, or action;
- duration when available;
- disclosure control for full input and result.

Repeated adjacent calls may be visually grouped, for example
`search_files × 8`, while preserving access to each individual call.

Expanded JSON should remain available for auditing, with syntax highlighting,
a Copy action, a bounded height, and internal scrolling. Values that match the
credential-redaction policy must be redacted before reaching the frontend.

#### Layout and navigation

- Increase interactive tool rows to a minimum 40-pixel height.
- Automatically close the conversation drawer when the available chat pane is
  too narrow; keep an obvious control to reopen it.
- Use the full message pane at small widths and avoid combining two persistent
  sidebars with a sub-300-pixel conversation area.
- Add a **Jump to latest** control when the reader scrolls away from the end.
- Auto-scroll only while the reader is already near the bottom. Streaming must
  not pull a reader away from earlier content.
- Allow completed assistant turns to be collapsed when they are unusually
  long.

This increment improves historical conversations, but it cannot correctly
interleave their prose and tool calls because that ordering was not persisted.

### Increment 2: Ordered message blocks

#### Data model

Add an ordered block representation for assistant messages. A message response
should expose a single `blocks` array rather than independent `content` and
`tool_calls` collections.

```json
{
  "id": "message-id",
  "role": "assistant",
  "blocks": [
    {
      "id": "block-1",
      "type": "activity",
      "text": "I will inspect the recorded trace."
    },
    {
      "id": "block-2",
      "type": "tool",
      "tool_call_id": "toolu_123",
      "tool": "parse_strace",
      "input": {"path": "..."},
      "status": "succeeded",
      "result": {"matches": []},
      "started_at": "...",
      "completed_at": "..."
    },
    {
      "id": "block-3",
      "type": "answer",
      "text": "The trace shows a four-second race."
    }
  ],
  "usage": {
    "input_tokens": 100,
    "output_tokens": 50
  }
}
```

Store the blocks as a dedicated JSON column on `chat_messages` unless querying
individual blocks becomes a product requirement. The block list is an ordered
message document and does not currently need relational queries. Keep token
usage in metadata or promote it to typed fields separately; do not mix it into
the block sequence.

Create a one-time migration for existing messages. Historical assistant
messages cannot be reconstructed exactly, so migrate them deterministically as
zero or more tool blocks followed by one answer block. Mark migrated messages
with `activity_order: "legacy_unavailable"` so the UI can state that original
ordering was not recorded. Do not keep dual read/write paths after migration.

#### Streaming state machine

Preserve SSE event order in both backend persistence and frontend state.

1. `message_start` creates an empty ordered block list.
2. Text emitted before a tool call is accumulated as an `activity` block.
3. `tool_use` appends a tool block with a stable provider tool-call ID and
   `running` status.
4. `tool_result` updates the block by tool-call ID, never by tool name.
5. Text after the last tool result remains pending until either another tool
   call arrives or the message ends.
6. If another tool call arrives, that pending text becomes `activity`.
7. At `message_end`, the final pending text becomes the `answer` block. If no
   tools were called, all text is the answer.

Stable tool-call IDs are required because matching results by tool name is
ambiguous when the same tool is called repeatedly.

Persist the same ordered blocks sent to the client. Reloading a conversation
must produce the same visible ordering as the live stream.

#### Presentation

Render the ordered blocks as two related surfaces:

- **Answer:** always visible and visually primary.
- **Activity:** collapsed by default after completion, expandable into an
  ordered timeline containing activity text and tool blocks.

While a response is streaming, keep the activity section open enough to show
the current operation. Collapse it automatically when the final answer is
complete unless the user explicitly expanded it.

Do not display tool results twice. The timeline owns tool input/result detail;
the answer should contain only the assistant's synthesis and citations or links
that are useful to the reader.

## Recommended component boundaries

Split the current chat page into focused components:

- `Chat.tsx` — conversation loading, selection, and send lifecycle;
- `ChatMessage.tsx` — user/assistant message composition;
- `ChatActivity.tsx` — activity summary and ordered timeline;
- `ChatToolCall.tsx` — compact and expanded tool presentation;
- `Markdown.tsx` — shared safe Markdown rendering;
- `useChatStream.ts` — SSE parsing and ordered-block state machine.

The exact names may follow existing frontend conventions, but Markdown parsing,
SSE state, and tool-detail rendering should not remain embedded in the page
component.

## Accessibility requirements

- Tool and activity disclosures use native buttons with `aria-expanded` and an
  associated controlled region.
- Running and completion states are conveyed by text as well as color.
- Streaming status uses a polite live region; token-by-token content does not
  repeatedly interrupt screen readers.
- Keyboard focus remains stable when new blocks arrive.
- All interactive targets meet the project's minimum touch-target size.
- Code and JSON Copy actions provide visible success feedback.

## Testing

### Backend

- Unit-test event sequences with no tools, one tool, repeated calls to the same
  tool, a tool error, and the tool-round limit.
- Assert block order and stable tool-call/result association.
- Assert the persisted conversation response matches the completed SSE state.
- Test the one-time historical-message migration.

### Frontend

- Render GFM tables, nested lists, links, inline code, and fenced code.
- Verify raw HTML is not executed.
- Test activity collapsed, expanded, running, succeeded, and failed states.
- Test repeated tool grouping without losing individual detail.
- Test that manual scrolling disables forced auto-scroll and exposes Jump to
  latest.
- Test narrow layouts with the conversation drawer open and closed.
- Test a long synthetic turn with at least 20 tool calls.

### Browser acceptance

Use Playwright against a seeded conversation matching the observed occurrence
69 shape:

1. Open the most recent conversation.
2. Confirm the final answer is visible without expanding activity.
3. Expand Activity and verify tools and progress appear in execution order.
4. Expand a repeated tool call and verify the correct input/result pair.
5. Confirm a Markdown table produces semantic table elements.
6. Confirm code and JSON remain inside the message width.
7. Repeat at 1440x900, 780x900, and a mobile viewport.

## Acceptance criteria

- A completed assistant turn presents one clear final answer and one collapsed
  activity summary.
- New conversations retain exact text/tool/result ordering across reloads.
- Repeated calls to the same tool receive the correct results.
- GFM tables, lists, links, and fenced code render semantically.
- Tool details remain available without making a 20-call turn dominate the
  conversation.
- Streaming does not force-scroll a reader who is inspecting earlier content.
- The chat remains usable with less than 800 pixels of viewport width.
- Frontend unit tests, backend chat tests, lint, and the frontend production
  build pass.

## Suggested delivery order

1. Shared safe Markdown renderer and GFM tests.
2. Responsive layout, scroll behavior, and current-schema activity summary.
3. Ordered-block schema and migration.
4. Backend SSE persistence state machine with stable tool-call IDs.
5. Frontend ordered activity timeline.
6. Seeded Playwright regression coverage.

Increment 1 is independently releasable. Increment 2 should be implemented as
one coordinated backend/frontend change so live streaming and reloaded history
never use different message models.
