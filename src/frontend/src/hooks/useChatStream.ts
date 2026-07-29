import { useRef, useCallback, useState } from "react";
import type { MessageBlock } from "../components/ChatActivity";

export interface StreamState {
  blocks: MessageBlock[];
  done: boolean;
}

type OnComplete = (blocks: MessageBlock[], content: string) => void;

let blockCounter = 0;
function nextBlockId(): string {
  return `stream-block-${++blockCounter}`;
}

export function useChatStream() {
  const [streamState, setStreamState] = useState<StreamState | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  /**
   * Read an SSE response body to completion, rebuilding the block list as it
   * goes. Shared by both the initial POST (startStream) and reconnects
   * (attachStream) — a reconnect replays the whole buffer first, so building
   * from scratch reconstructs the full in-progress message either way.
   */
  const consumeResponse = useCallback(
    async (res: Response, onComplete: OnComplete) => {
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
        if (!res.body) {
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

        // If no answer block was created (e.g. tool-only response or no
        // message_end), finalize any trailing text.
        if (pendingText.trim()) {
          blocks.push({ id: nextBlockId(), type: "answer", text: pendingText.trim() });
          pendingText = "";
        }

        const answerBlock = blocks.find((b) => b.type === "answer");
        onComplete(blocks, answerBlock?.text ?? "");
      } catch (err) {
        // AbortError means the client tore down the reader (unmount / switch);
        // the backend keeps generating and persists, so don't finalize here.
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

  /**
   * Re-attach to an in-flight generation for a conversation. Returns true if a
   * live stream was found and consumed, false if the conversation is idle (204)
   * or the request failed.
   */
  const attachStream = useCallback(
    async (convId: number | string, onComplete: OnComplete): Promise<boolean> => {
      const controller = new AbortController();
      abortRef.current = controller;

      let res: Response;
      try {
        res = await fetch(`/api/v1/chat/conversations/${convId}/stream`, {
          signal: controller.signal,
        });
      } catch {
        abortRef.current = null;
        return false;
      }

      if (res.status === 204 || !res.ok || !res.body) {
        abortRef.current = null;
        return false;
      }

      setIsStreaming(true);
      setStreamState({ blocks: [], done: false });
      await consumeResponse(res, onComplete);
      return true;
    },
    [consumeResponse],
  );

  const startStream = useCallback(
    async (convId: number | string, content: string, onComplete: OnComplete) => {
      setIsStreaming(true);
      setStreamState({ blocks: [], done: false });

      const controller = new AbortController();
      abortRef.current = controller;

      let res: Response;
      try {
        res = await fetch(`/api/v1/chat/conversations/${convId}/messages`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content }),
          signal: controller.signal,
        });
      } catch (err) {
        if ((err as Error).name !== "AbortError") setStreamState(null);
        setIsStreaming(false);
        abortRef.current = null;
        return;
      }

      // A generation is already running (e.g. sent from another tab) — attach
      // to it rather than starting a second.
      if (res.status === 409) {
        await attachStream(convId, onComplete);
        return;
      }

      if (!res.ok || !res.body) {
        setStreamState(null);
        setIsStreaming(false);
        abortRef.current = null;
        return;
      }

      await consumeResponse(res, onComplete);
    },
    [consumeResponse, attachStream],
  );

  const abort = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { streamState, isStreaming, startStream, attachStream, abort };
}
