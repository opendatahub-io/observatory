import { useState } from "react";
import { ChevronDown, ChevronUp, Loader2 } from "lucide-react";
import Markdown from "./Markdown";
import ChatActivity, { type MessageBlock } from "./ChatActivity";

interface ChatMessageProps {
  role: "user" | "assistant";
  content: string;
  blocks?: MessageBlock[];
  activityOrder?: string;
  isStreaming?: boolean;
  streamBlocks?: MessageBlock[];
}

export default function ChatMessage({
  role,
  content,
  blocks,
  activityOrder,
  isStreaming,
  streamBlocks,
}: ChatMessageProps) {
  const [collapsed, setCollapsed] = useState(false);

  if (role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] ml-auto bg-primary-600 text-white rounded-2xl rounded-br-md px-4 py-3">
          <p className="whitespace-pre-wrap text-sm">{content}</p>
        </div>
      </div>
    );
  }

  const activeBlocks = streamBlocks ?? blocks ?? [];
  const hasActivity = activeBlocks.some((b) => b.type === "tool" || b.type === "activity");
  const answerBlock = activeBlocks.find((b) => b.type === "answer");
  const answerText = answerBlock?.text ?? content;

  // During streaming, compute pending text from blocks that haven't become an answer yet
  const streamingPendingText =
    isStreaming && !answerBlock
      ? activeBlocks
          .filter((b) => b.type === "activity")
          .map((b) => b.text)
          .join("")
      : null;

  const isLong = answerText.length > 2000;

  return (
    <div className="flex flex-col gap-2">
      {hasActivity && (
        <div className="max-w-[90%]">
          <ChatActivity
            blocks={activeBlocks}
            isStreaming={isStreaming}
            defaultExpanded={isStreaming}
            activityOrder={activityOrder}
          />
        </div>
      )}
      {answerText ? (
        <div className="max-w-[80%] bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl rounded-bl-md px-4 py-3">
          {isLong && !isStreaming && (
            <button
              className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 mb-2"
              onClick={() => setCollapsed(!collapsed)}
            >
              {collapsed ? (
                <>
                  <ChevronDown className="w-3 h-3" /> Expand
                </>
              ) : (
                <>
                  <ChevronUp className="w-3 h-3" /> Collapse
                </>
              )}
            </button>
          )}
          {collapsed ? (
            <div className="text-sm text-gray-400 dark:text-gray-500 italic">
              Message collapsed ({Math.ceil(answerText.length / 100)} lines)
            </div>
          ) : (
            <div className="prose prose-sm dark:prose-invert max-w-none text-sm text-gray-800 dark:text-gray-200">
              <Markdown content={answerText} />
              {isStreaming && (
                <span className="inline-block w-2 h-4 bg-primary-500 animate-pulse ml-0.5 align-text-bottom rounded-sm" />
              )}
            </div>
          )}
        </div>
      ) : isStreaming && !streamingPendingText ? (
        <div className="max-w-[80%] bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl rounded-bl-md px-4 py-3">
          <Loader2 className="w-4 h-4 animate-spin text-gray-400" />
        </div>
      ) : null}
    </div>
  );
}
