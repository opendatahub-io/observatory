import { useState } from "react";
import { ChevronDown, ChevronRight, Activity, Loader2 } from "lucide-react";
import ChatToolCall, { type ToolCallData } from "./ChatToolCall";

export interface MessageBlock {
  id: string;
  type: "activity" | "tool" | "answer";
  text?: string;
  tool_call_id?: string;
  tool?: string;
  input?: Record<string, unknown>;
  result?: Record<string, unknown> | unknown;
  status?: "running" | "succeeded" | "failed";
  started_at?: string;
  completed_at?: string;
}

interface ChatActivityProps {
  blocks: MessageBlock[];
  isStreaming?: boolean;
  defaultExpanded?: boolean;
  activityOrder?: string;
}

function groupToolCalls(toolBlocks: MessageBlock[]): { tool: string; count: number; items: MessageBlock[] }[] {
  const groups: { tool: string; count: number; items: MessageBlock[] }[] = [];
  for (const block of toolBlocks) {
    const last = groups[groups.length - 1];
    if (last && last.tool === block.tool) {
      last.count++;
      last.items.push(block);
    } else {
      groups.push({ tool: block.tool!, count: 1, items: [block] });
    }
  }
  return groups;
}

export default function ChatActivity({ blocks, isStreaming, defaultExpanded, activityOrder }: ChatActivityProps) {
  const toolBlocks = blocks.filter((b) => b.type === "tool");
  const activityBlocks = blocks.filter((b) => b.type === "activity");
  const allDone = toolBlocks.every((b) => b.status !== "running");
  const hasFailed = toolBlocks.some((b) => b.status === "failed");

  const [expanded, setExpanded] = useState(defaultExpanded ?? (isStreaming === true));
  const [expandedTools, setExpandedTools] = useState<Set<string>>(new Set());

  if (toolBlocks.length === 0 && activityBlocks.length === 0) return null;

  const statusText = isStreaming && !allDone
    ? "running"
    : hasFailed
      ? "completed with errors"
      : "completed";

  const toggleTool = (id: string) => {
    setExpandedTools((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const groups = groupToolCalls(toolBlocks);

  return (
    <div className="bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700 rounded-lg">
      <button
        className="flex items-center gap-2 w-full text-left px-3 py-2 text-xs text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700/50 rounded-lg transition-colors"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
      >
        {isStreaming && !allDone ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-500 flex-shrink-0" />
        ) : (
          <Activity className="w-3.5 h-3.5 flex-shrink-0" />
        )}
        <span className="font-medium">Work log</span>
        <span className="text-gray-400 dark:text-gray-500">
          {toolBlocks.length} tool {toolBlocks.length === 1 ? "call" : "calls"}
          {" · "}
          {statusText}
        </span>
        {activityOrder === "legacy_unavailable" && (
          <span className="text-gray-400 dark:text-gray-500 text-[10px]">(original order unavailable)</span>
        )}
        <span className="ml-auto flex-shrink-0">
          {expanded ? (
            <ChevronDown className="w-3.5 h-3.5" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5" />
          )}
        </span>
      </button>
      {expanded && (
        <div className="px-3 pb-2 border-t border-gray-200 dark:border-gray-700">
          {activityOrder === "legacy_unavailable" ? (
            /* Legacy: show all tool calls without interleaved activity text */
            <div className="space-y-0.5 mt-1">
              {groups.map((group, gi) =>
                group.count > 1 ? (
                  <div key={gi}>
                    <div className="text-[10px] text-gray-400 dark:text-gray-500 px-2 py-1 font-medium">
                      {group.tool.replace(/_/g, " ")} x{group.count}
                    </div>
                    {group.items.map((block) => (
                      <ChatToolCall
                        key={block.id}
                        tc={block as ToolCallData}
                        expanded={expandedTools.has(block.id)}
                        onToggle={() => toggleTool(block.id)}
                      />
                    ))}
                  </div>
                ) : (
                  <ChatToolCall
                    key={group.items[0]!.id}
                    tc={group.items[0]! as ToolCallData}
                    expanded={expandedTools.has(group.items[0]!.id)}
                    onToggle={() => toggleTool(group.items[0]!.id)}
                  />
                ),
              )}
            </div>
          ) : (
            /* Ordered: show blocks in original sequence */
            <div className="space-y-0.5 mt-1">
              {blocks
                .filter((b) => b.type !== "answer")
                .map((block) =>
                  block.type === "activity" ? (
                    <div
                      key={block.id}
                      className="text-xs text-gray-500 dark:text-gray-400 italic px-2 py-1"
                    >
                      {block.text}
                    </div>
                  ) : (
                    <ChatToolCall
                      key={block.id}
                      tc={block as ToolCallData}
                      expanded={expandedTools.has(block.id)}
                      onToggle={() => toggleTool(block.id)}
                    />
                  ),
                )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
