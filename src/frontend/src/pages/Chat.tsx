import { useEffect, useState, useCallback, useRef } from "react";
import {
  MessageSquare,
  Plus,
  Send,
  Trash2,
  X,
  ChevronDown,
  ChevronRight,
  Wrench,
  Loader2,
  Sparkles,
} from "lucide-react";

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
  tool_calls?: ToolCall[];
  created_at: string;
}

interface ToolCall {
  tool: string;
  input: Record<string, unknown>;
  result?: Record<string, unknown> | unknown;
  collapsed?: boolean;
}

/* Represents a message being built up during SSE streaming */
interface StreamingMessage {
  id: number | null;
  role: "assistant";
  content: string;
  toolCalls: ToolCall[];
  done: boolean;
}

/* ------------------------------------------------------------------ */
/*  Markdown renderer                                                  */
/* ------------------------------------------------------------------ */

function renderMarkdown(md: string): string {
  return md
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(
      /```([\s\S]*?)```/g,
      '<pre class="bg-gray-100 dark:bg-gray-900 rounded-lg p-3 my-2 overflow-x-auto text-sm"><code>$1</code></pre>',
    )
    .replace(/^### (.+)$/gm, '<h3 class="text-sm font-semibold mt-3 mb-1">$1</h3>')
    .replace(/^## (.+)$/gm, '<h2 class="text-base font-semibold mt-4 mb-2">$1</h2>')
    .replace(/^# (.+)$/gm, '<h1 class="text-lg font-bold mt-4 mb-2">$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong class="font-semibold">$1</strong>')
    .replace(
      /`([^`]+)`/g,
      '<code class="px-1 py-0.5 bg-gray-100 dark:bg-gray-700 rounded text-sm">$1</code>',
    )
    .replace(/^- (.+)$/gm, '<li class="ml-4 list-disc">$1</li>')
    .replace(/\n/g, "<br>");
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

function Chat() {
  /* --- Conversation list state --- */
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [convsLoading, setConvsLoading] = useState(true);
  const [activeConvId, setActiveConvId] = useState<number | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  /* --- Messages state --- */
  const [messages, setMessages] = useState<Message[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);

  /* --- Streaming state --- */
  const [streaming, setStreaming] = useState<StreamingMessage | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);

  /* --- Input state --- */
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  /* --- Tool call collapse state (for already-committed messages) --- */
  const [collapsedTools, setCollapsedTools] = useState<Set<string>>(new Set());

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
    setStreaming(null);
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
          setStreaming(null);
        }
      } catch {
        /* ignore */
      }
    },
    [activeConvId],
  );

  /* ================================================================ */
  /*  SSE streaming                                                    */
  /* ================================================================ */

  const sendMessage = useCallback(
    async (convId: number, content: string) => {
      /* Optimistically add user message */
      const userMsg: Message = {
        id: Date.now(),
        role: "user",
        content,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMsg]);
      setIsStreaming(true);
      setStreaming({ id: null, role: "assistant", content: "", toolCalls: [], done: false });

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const res = await fetch(`/api/v1/chat/conversations/${convId}/messages`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content }),
          signal: controller.signal,
        });

        if (!res.ok || !res.body) {
          setStreaming(null);
          setIsStreaming(false);
          return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let currentEvent = "";
        let accContent = "";
        let accToolCalls: ToolCall[] = [];

        const processLine = (line: string) => {
          if (line.startsWith("event:")) {
            currentEvent = line.slice(6).trim();
            return;
          }
          if (line.startsWith("data:")) {
            const dataStr = line.slice(5).trim();
            if (!dataStr) return;

            let data: Record<string, unknown>;
            try {
              data = JSON.parse(dataStr);
            } catch {
              return;
            }

            switch (currentEvent) {
              case "message_start":
                /* nothing to accumulate yet */
                break;

              case "content_delta":
                accContent += (data.text as string) ?? "";
                setStreaming((prev) =>
                  prev ? { ...prev, content: accContent, toolCalls: [...accToolCalls] } : prev,
                );
                break;

              case "tool_use":
                accToolCalls = [
                  ...accToolCalls,
                  {
                    tool: data.tool as string,
                    input: data.input as Record<string, unknown>,
                    collapsed: true,
                  },
                ];
                setStreaming((prev) =>
                  prev ? { ...prev, content: accContent, toolCalls: [...accToolCalls] } : prev,
                );
                break;

              case "tool_result": {
                const toolName = data.tool as string;
                accToolCalls = accToolCalls.map((tc) =>
                  tc.tool === toolName && tc.result === undefined
                    ? { ...tc, result: data.result as Record<string, unknown> }
                    : tc,
                );
                setStreaming((prev) =>
                  prev ? { ...prev, content: accContent, toolCalls: [...accToolCalls] } : prev,
                );
                break;
              }

              case "message_end":
                setStreaming((prev) =>
                  prev ? { ...prev, content: accContent, toolCalls: [...accToolCalls], done: true } : prev,
                );
                break;

              case "error":
                accContent += `\n\n**Error:** ${data.error as string}`;
                setStreaming((prev) =>
                  prev ? { ...prev, content: accContent, toolCalls: [...accToolCalls], done: true } : prev,
                );
                break;
            }
          }
        };

        // eslint-disable-next-line no-constant-condition
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          /* Keep the last partial line in the buffer */
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            const trimmed = line.trim();
            if (trimmed) {
              processLine(trimmed);
            }
          }
        }

        /* Process any remaining data in the buffer */
        if (buffer.trim()) {
          processLine(buffer.trim());
        }

        /* Commit streaming message to the messages array */
        setMessages((prev) => [
          ...prev,
          {
            id: Date.now() + 1,
            role: "assistant" as const,
            content: accContent,
            tool_calls: accToolCalls.length > 0 ? accToolCalls : undefined,
            created_at: new Date().toISOString(),
          },
        ]);
        setStreaming(null);
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          setStreaming(null);
        }
      } finally {
        setIsStreaming(false);
        abortRef.current = null;
        /* Refresh conversation list to get updated titles / timestamps */
        void fetchConversations();
      }
    },
    [fetchConversations],
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
      /* Auto-create a new conversation */
      convId = await createConversation(content.slice(0, 80));
      if (convId === null) return;
    }

    void sendMessage(convId, content);
  }, [input, isStreaming, activeConvId, createConversation, sendMessage]);

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
  /*  Auto-scroll                                                      */
  /* ================================================================ */

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming]);

  /* ================================================================ */
  /*  Tool call collapse toggle                                        */
  /* ================================================================ */

  const toggleToolCollapse = (key: string) => {
    setCollapsedTools((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  /* ================================================================ */
  /*  Render helpers                                                    */
  /* ================================================================ */

  const renderToolCall = (tc: ToolCall, key: string, isCollapsed: boolean, onToggle: () => void) => (
    <div
      key={key}
      className="max-w-[80%] bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700 rounded-lg p-3 text-xs"
    >
      <button
        className="flex items-center gap-1.5 font-medium text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-gray-100 w-full text-left"
        onClick={onToggle}
      >
        <Wrench className="w-3.5 h-3.5 text-gray-500" />
        <span>{tc.tool}</span>
        {isCollapsed ? (
          <ChevronRight className="w-3.5 h-3.5 ml-auto" />
        ) : (
          <ChevronDown className="w-3.5 h-3.5 ml-auto" />
        )}
      </button>
      {!isCollapsed && (
        <div className="mt-2 space-y-2">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-1">
              Input
            </div>
            <pre className="bg-gray-100 dark:bg-gray-900 rounded p-2 overflow-x-auto whitespace-pre-wrap text-gray-700 dark:text-gray-300">
              {JSON.stringify(tc.input, null, 2)}
            </pre>
          </div>
          {tc.result !== undefined && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-1">
                Result
              </div>
              <pre className="bg-gray-100 dark:bg-gray-900 rounded p-2 overflow-x-auto whitespace-pre-wrap text-gray-700 dark:text-gray-300 max-h-60 overflow-y-auto">
                {JSON.stringify(tc.result, null, 2)}
              </pre>
            </div>
          )}
          {tc.result === undefined && (
            <div className="flex items-center gap-1.5 text-gray-400">
              <Loader2 className="w-3 h-3 animate-spin" />
              <span>Running...</span>
            </div>
          )}
        </div>
      )}
    </div>
  );

  const renderMessage = (msg: Message, idx: number) => {
    if (msg.role === "user") {
      return (
        <div key={msg.id ?? idx} className="flex justify-end">
          <div className="max-w-[80%] ml-auto bg-primary-600 text-white rounded-2xl rounded-br-md px-4 py-3">
            <p className="whitespace-pre-wrap text-sm">{msg.content}</p>
          </div>
        </div>
      );
    }

    /* Assistant message — show tool calls (thinking/progress) above the text answer */
    return (
      <div key={msg.id ?? idx} className="flex flex-col gap-2">
        {msg.tool_calls?.map((tc, i) => {
          const key = `${msg.id}-tool-${i}`;
          const collapsed = !collapsedTools.has(key);
          return renderToolCall(tc, key, collapsed, () => toggleToolCollapse(key));
        })}
        {msg.content && (
          <div className="max-w-[80%] bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl rounded-bl-md px-4 py-3">
            <div
              className="prose prose-sm dark:prose-invert max-w-none text-sm text-gray-800 dark:text-gray-200"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }}
            />
          </div>
        )}
      </div>
    );
  };

  const renderStreamingMessage = () => {
    if (!streaming) return null;
    return (
      <div className="flex flex-col gap-2">
        {/* Render any tool calls that arrived during streaming */}
        {streaming.toolCalls.map((tc, i) => {
          const key = `streaming-tool-${i}`;
          const collapsed = tc.collapsed ?? true;
          return renderToolCall(tc, key, collapsed, () => {
            setStreaming((prev) => {
              if (!prev) return prev;
              const updated: ToolCall[] = prev.toolCalls.map((t, j) =>
                j === i ? { ...t, collapsed: !collapsed } : t,
              );
              return { ...prev, toolCalls: updated };
            });
          });
        })}
        {/* Streaming text content */}
        {streaming.content && (
          <div className="max-w-[80%] bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl rounded-bl-md px-4 py-3">
            <div
              className="prose prose-sm dark:prose-invert max-w-none text-sm text-gray-800 dark:text-gray-200"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(streaming.content) }}
            />
            {!streaming.done && (
              <span className="inline-block w-2 h-4 bg-primary-500 animate-pulse ml-0.5 align-text-bottom rounded-sm" />
            )}
          </div>
        )}
        {!streaming.content && !streaming.done && (
          <div className="max-w-[80%] bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl rounded-bl-md px-4 py-3">
            <Loader2 className="w-4 h-4 animate-spin text-gray-400" />
          </div>
        )}
      </div>
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
        <div className="w-72 border-r border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 flex flex-col flex-shrink-0">
          {/* Sidebar header */}
          <div className="p-3 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Conversations</h2>
            <div className="flex items-center gap-1">
              <button
                className="p-1.5 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-400 transition-colors"
                title="New chat"
                onClick={() => {
                  setActiveConvId(null);
                  setMessages([]);
                  setStreaming(null);
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

          {/* Conversation list */}
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
        {/* Top bar (only show sidebar toggle when collapsed) */}
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
        <div className="flex-1 overflow-y-auto px-4 py-4">
          {activeConvId === null && !isStreaming ? (
            /* ---- Empty / welcome state ---- */
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
                      /* Focus textarea so user can just hit Enter */
                      textareaRef.current?.focus();
                    }}
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            /* ---- Message list ---- */
            <div className="max-w-3xl mx-auto space-y-4">
              {messagesLoading && (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
                </div>
              )}
              {!messagesLoading && messages.map((msg, idx) => renderMessage(msg, idx))}
              {renderStreamingMessage()}
              <div ref={messagesEndRef} />
            </div>
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
