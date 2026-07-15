import { useRef, useCallback, useState } from "react";
import type { MessageBlock } from "../components/ChatActivity";

export interface StreamState {
  blocks: MessageBlock[];
  done: boolean;
}

let blockCounter = 0;
function nextBlockId(): string {
  return `stream-block-${++blockCounter}`;
}

export function useChatStream() {
  const [streamState, setStreamState] = useState<StreamState | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const startStream = useCallback(
    async (
      convId: number | string,
      content: string,
      onComplete: (blocks: MessageBlock[], content: string) => void,
    ) => {
      setIsStreaming(true);
      setStreamState({ blocks: [], done: false });

      const controller = new AbortController();
      abortRef.current = controller;

      const blocks: MessageBlock[] = [];
      let pendingText = "";
      let currentEvent = "";
      let lastToolBlockId: string | null = null;

      function flushActivityText() {
        const text = pendingText.trim();
        if (text) {
          blocks.push({ id: nextBlockId(), type: "activity", text });
        }
        pendingText = "";
      }

      function emitUpdate(done = false) {
        setStreamState({ blocks: [...blocks], done });
      }

      const processLine = (line: string) => {
        if (line.startsWith("event:")) {
          currentEvent = line.slice(6).trim();
          return;
        }
        if (!line.startsWith("data:")) return;
        const dataStr = line.slice(5).trim();
        if (!dataStr) return;

        let data: Record<string, unknown>;
        try {
          data = JSON.parse(dataStr);
        } catch {
          return;
        }

        switch (currentEvent) {
          case "content_delta": {
            const text = (data.text as string) ?? "";
            pendingText += text;
            emitUpdate();
            break;
          }

          case "tool_use": {
            flushActivityText();
            const blockId = (data.tool_call_id as string) ?? nextBlockId();
            lastToolBlockId = blockId;
            blocks.push({
              id: blockId,
              type: "tool",
              tool_call_id: blockId,
              tool: data.tool as string,
              input: data.input as Record<string, unknown>,
              status: "running",
            });
            emitUpdate();
            break;
          }

          case "tool_result": {
            const toolCallId = data.tool_call_id as string | undefined;
            const matchId = toolCallId ?? lastToolBlockId;
            const idx = blocks.findIndex(
              (b) => b.type === "tool" && b.id === matchId,
            );
            if (idx >= 0) {
              blocks[idx] = {
                ...blocks[idx]!,
                result: data.result as Record<string, unknown>,
                status:
                  (data.is_error as boolean) === true ? "failed" : "succeeded",
              };
            }
            emitUpdate();
            break;
          }

          case "message_end": {
            const text = pendingText.trim();
            if (text) {
              blocks.push({ id: nextBlockId(), type: "answer", text });
              pendingText = "";
            }
            emitUpdate(true);
            break;
          }

          case "error": {
            const errText = `\n\n**Error:** ${data.error as string}`;
            pendingText += errText;
            const text = pendingText.trim();
            blocks.push({ id: nextBlockId(), type: "answer", text });
            pendingText = "";
            emitUpdate(true);
            break;
          }
        }
      };

      try {
        const res = await fetch(
          `/api/v1/chat/conversations/${convId}/messages`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content }),
            signal: controller.signal,
          },
        );

        if (!res.ok || !res.body) {
          setStreamState(null);
          setIsStreaming(false);
          return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        // eslint-disable-next-line no-constant-condition
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            const trimmed = line.trim();
            if (trimmed) processLine(trimmed);
          }
        }

        if (buffer.trim()) processLine(buffer.trim());

        // If no answer block was created (e.g. tool-only response or no message_end), finalize
        if (pendingText.trim()) {
          blocks.push({ id: nextBlockId(), type: "answer", text: pendingText.trim() });
          pendingText = "";
        }

        const answerBlock = blocks.find((b) => b.type === "answer");
        onComplete(blocks, answerBlock?.text ?? "");
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          setStreamState(null);
        }
      } finally {
        setIsStreaming(false);
        setStreamState(null);
        abortRef.current = null;
      }
    },
    [],
  );

  const abort = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { streamState, isStreaming, startStream, abort };
}
