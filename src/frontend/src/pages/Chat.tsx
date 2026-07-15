import { useEffect, useState, useCallback, useRef } from "react";
import {
  MessageSquare,
  Plus,
  Send,
  Trash2,
  X,
  Loader2,
  Sparkles,
  ArrowDown,
} from "lucide-react";
import ChatMessage from "../components/ChatMessage";
import type { MessageBlock } from "../components/ChatActivity";
import { useChatStream } from "../hooks/useChatStream";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface Conversation {
  id: number;
  title: string | null;
  created_at: string;
  updated_at: string;
  message_count?: number;
}

interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  blocks?: MessageBlock[];
  activity_order?: string;
  tool_calls?: { tool: string; input: Record<string, unknown>; result?: unknown }[];
  created_at: string;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function legacyToolCallsToBlocks(
  toolCalls: { tool: string; input: Record<string, unknown>; result?: unknown }[],
): MessageBlock[] {
  return toolCalls.map((tc, i) => ({
    id: `legacy-tool-${i}`,
    type: "tool" as const,
    tool: tc.tool,
    input: tc.input,
    result: tc.result,
    status: tc.result !== undefined ? ("succeeded" as const) : ("running" as const),
  }));
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

const NARROW_BREAKPOINT = 640;

function Chat() {
  /* --- Conversation list state --- */
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [convsLoading, setConvsLoading] = useState(true);
  const [activeConvId, setActiveConvId] = useState<number | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  /* --- Messages state --- */
  const [messages, setMessages] = useState<Message[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);

  /* --- Input state --- */
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  /* --- Scroll state --- */
  const [showJumpToLatest, setShowJumpToLatest] = useState(false);
  const isNearBottomRef = useRef(true);

  /* --- Streaming hook --- */
  const { streamState, isStreaming, startStream } = useChatStream();

  /* ================================================================ */
  /*  Responsive sidebar management                                    */
  /* ================================================================ */

  useEffect(() => {
    const checkWidth = () => {
      if (window.innerWidth < NARROW_BREAKPOINT) {
        setSidebarOpen(false);
      }
    };
    checkWidth();
    window.addEventListener("resize", checkWidth);
    return () => window.removeEventListener("resize", checkWidth);
  }, []);

  /* ================================================================ */
  /*  Scroll handling                                                  */
  /* ================================================================ */

  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    const onScroll = () => {
      const threshold = 100;
      const atBottom =
        container.scrollHeight - container.scrollTop - container.clientHeight < threshold;
      isNearBottomRef.current = atBottom;
      setShowJumpToLatest(!atBottom);
    };

    container.addEventListener("scroll", onScroll, { passive: true });
    return () => container.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (isNearBottomRef.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, streamState]);

  const jumpToLatest = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  /* ================================================================ */
  /*  Data fetching                                                    */
  /* ================================================================ */

  const fetchConversations = useCallback(async () => {
    setConvsLoading(true);
    try {
      const res = await fetch("/api/v1/chat/conversations?limit=50&offset=0");
      if (res.ok) {
        const data = await res.json();
        setConversations(data ?? []);
      }
    } catch {
      /* ignore */
    } finally {
      setConvsLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchConversations();
  }, [fetchConversations]);

  const loadConversation = useCallback(async (id: number) => {
    setActiveConvId(id);
    setMessagesLoading(true);
    try {
      const res = await fetch(`/api/v1/chat/conversations/${id}`);
      if (res.ok) {
        const data = await res.json();
        setMessages(data.messages ?? []);
      }
    } catch {
      /* ignore */
    } finally {
      setMessagesLoading(false);
    }
  }, []);

  /* ================================================================ */
  /*  Conversation CRUD                                                */
  /* ================================================================ */

  const createConversation = useCallback(
    async (title?: string): Promise<number | null> => {
      try {
        const res = await fetch("/api/v1/chat/conversations", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: title ?? undefined }),
        });
        if (res.ok) {
          const conv: Conversation = await res.json();
          setConversations((prev) => [conv, ...prev]);
          setActiveConvId(conv.id);
          setMessages([]);
          return conv.id;
        }
      } catch {
        /* ignore */
      }
      return null;
    },
    [],
  );

  const deleteConversation = useCallback(
    async (id: number) => {
      if (!confirm("Delete this conversation?")) return;
      try {
        await fetch(`/api/v1/chat/conversations/${id}`, { method: "DELETE" });
        setConversations((prev) => prev.filter((c) => c.id !== id));
        if (activeConvId === id) {
          setActiveConvId(null);
          setMessages([]);
        }
      } catch {
        /* ignore */
      }
    },
    [activeConvId],
  );

  /* ================================================================ */
  /*  Submit handler                                                   */
  /* ================================================================ */

  const handleSubmit = useCallback(async () => {
    const content = input.trim();
    if (!content || isStreaming) return;
    setInput("");

    let convId = activeConvId;
    if (convId === null) {
      convId = await createConversation(content.slice(0, 80));
      if (convId === null) return;
    }

    const userMsg: Message = {
      id: Date.now(),
      role: "user",
      content,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);

    void startStream(convId, content, (blocks, answerContent) => {
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          role: "assistant" as const,
          content: answerContent,
          blocks,
          created_at: new Date().toISOString(),
        },
      ]);
      void fetchConversations();
    });
  }, [input, isStreaming, activeConvId, createConversation, startStream, fetchConversations]);

  /* ================================================================ */
  /*  Keyboard handling                                                */
  /* ================================================================ */

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSubmit();
    }
  };

  /* ================================================================ */
  /*  Auto-resize textarea                                             */
  /* ================================================================ */

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";
  }, [input]);

  /* ================================================================ */
  /*  Render helpers                                                    */
  /* ================================================================ */

  const renderMessage = (msg: Message) => {
    const blocks =
      msg.blocks ??
      (msg.tool_calls ? legacyToolCallsToBlocks(msg.tool_calls) : undefined);
    const activityOrder = msg.blocks ? msg.activity_order : msg.tool_calls ? "legacy_unavailable" : undefined;

    return (
      <ChatMessage
        key={msg.id}
        role={msg.role}
        content={msg.content}
        blocks={blocks}
        activityOrder={activityOrder}
      />
    );
  };

  const renderStreamingMessage = () => {
    if (!streamState) return null;

    const hasAnswer = streamState.blocks.some((b) => b.type === "answer");
    const answerBlock = streamState.blocks.find((b) => b.type === "answer");

    return (
      <ChatMessage
        role="assistant"
        content={answerBlock?.text ?? ""}
        isStreaming={!streamState.done}
        streamBlocks={streamState.blocks}
        activityOrder={hasAnswer ? undefined : undefined}
      />
    );
  };

  /* ================================================================ */
  /*  Suggested questions for empty state                              */
  /* ================================================================ */

  const suggestions = [
    "Which pipelines failed most this week?",
    "Show me the flakiest tests across all pipelines",
    "What are the most common failure patterns?",
    "Summarize the health of our CI/CD system",
  ];

  /* ================================================================ */
  /*  Render                                                           */
  /* ================================================================ */

  return (
    <div className="-mx-6 lg:-mx-8 -my-6 flex" style={{ height: "calc(100vh - 64px)" }}>
      {/* ---- Sidebar ---- */}
      {sidebarOpen && (
        <div className="w-72 max-w-[70vw] border-r border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 flex flex-col flex-shrink-0">
          <div className="p-3 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Conversations</h2>
            <div className="flex items-center gap-1">
              <button
                className="p-1.5 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-400 transition-colors"
                title="New chat"
                onClick={() => {
                  setActiveConvId(null);
                  setMessages([]);
                }}
              >
                <Plus className="w-4 h-4" />
              </button>
              <button
                className="p-1.5 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-400 transition-colors"
                title="Close sidebar"
                onClick={() => setSidebarOpen(false)}
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto">
            {convsLoading && (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
              </div>
            )}
            {!convsLoading && conversations.length === 0 && (
              <div className="text-center py-8 text-sm text-gray-400 dark:text-gray-500">
                No conversations yet
              </div>
            )}
            {conversations.map((conv) => (
              <div
                key={conv.id}
                className={`group flex items-center gap-2 px-3 py-2.5 cursor-pointer border-b border-gray-100 dark:border-gray-800 transition-colors ${
                  activeConvId === conv.id
                    ? "bg-primary-50 dark:bg-primary-900/20 border-l-2 border-l-primary-500"
                    : "hover:bg-gray-100 dark:hover:bg-gray-800 border-l-2 border-l-transparent"
                }`}
                onClick={() => void loadConversation(conv.id)}
              >
                <MessageSquare className="w-4 h-4 text-gray-400 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-gray-800 dark:text-gray-200 truncate">
                    {conv.title || "Untitled"}
                  </div>
                  <div className="text-[10px] text-gray-400 dark:text-gray-500">
                    {conv.message_count != null ? `${conv.message_count} messages` : ""}
                  </div>
                </div>
                <button
                  className="p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-red-100 dark:hover:bg-red-900/30 text-gray-400 hover:text-red-500 transition-all"
                  title="Delete"
                  onClick={(e) => {
                    e.stopPropagation();
                    void deleteConversation(conv.id);
                  }}
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ---- Main chat area ---- */}
      <div className="flex-1 flex flex-col min-w-0">
        {!sidebarOpen && (
          <div className="border-b border-gray-200 dark:border-gray-700 px-4 py-2">
            <button
              className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 dark:text-gray-400 transition-colors"
              title="Open sidebar"
              onClick={() => setSidebarOpen(true)}
            >
              <MessageSquare className="w-4 h-4" />
            </button>
          </div>
        )}

        {/* Messages area */}
        <div className="flex-1 overflow-y-auto px-4 py-4 relative" ref={scrollContainerRef}>
          {activeConvId === null && !isStreaming ? (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <div className="p-4 rounded-full bg-primary-50 dark:bg-primary-900/20 mb-4">
                <Sparkles className="w-8 h-8 text-primary-500" />
              </div>
              <h2 className="text-xl font-semibold text-gray-800 dark:text-gray-200 mb-2">
                Ask about your CI/CD data
              </h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 max-w-md mb-6">
                Chat with an AI assistant that can query your pipeline runs, test results, and
                artifacts to answer questions and surface insights.
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-w-lg w-full">
                {suggestions.map((q) => (
                  <button
                    key={q}
                    className="text-left text-sm px-4 py-3 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:border-primary-300 dark:hover:border-primary-600 hover:bg-primary-50 dark:hover:bg-primary-900/10 transition-colors"
                    onClick={() => {
                      setInput(q);
                      textareaRef.current?.focus();
                    }}
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="max-w-3xl mx-auto space-y-4">
              {messagesLoading && (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
                </div>
              )}
              {!messagesLoading && messages.map((msg) => renderMessage(msg))}
              {renderStreamingMessage()}
              <div ref={messagesEndRef} />
            </div>
          )}

          {showJumpToLatest && (
            <button
              className="fixed bottom-24 left-1/2 -translate-x-1/2 z-10 flex items-center gap-1.5 px-3 py-1.5 bg-gray-800 dark:bg-gray-200 text-white dark:text-gray-800 rounded-full shadow-lg text-xs font-medium hover:bg-gray-700 dark:hover:bg-gray-300 transition-colors"
              onClick={jumpToLatest}
            >
              <ArrowDown className="w-3.5 h-3.5" />
              Jump to latest
            </button>
          )}
        </div>

        {/* ---- Input area ---- */}
        <div className="border-t border-gray-200 dark:border-gray-700 p-4">
          <div className="max-w-3xl mx-auto flex gap-2 items-end">
            <textarea
              ref={textareaRef}
              className="flex-1 px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-xl bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 resize-none focus:ring-2 focus:ring-primary-500 outline-none text-sm placeholder-gray-400 dark:placeholder-gray-500"
              rows={1}
              placeholder="Ask a question about your CI/CD data..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isStreaming}
            />
            <button
              className="p-3 bg-primary-600 hover:bg-primary-700 text-white rounded-xl transition-colors disabled:opacity-50"
              disabled={isStreaming || !input.trim()}
              onClick={() => void handleSubmit()}
              title="Send message"
            >
              {isStreaming ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <Send className="w-5 h-5" />
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default Chat;
