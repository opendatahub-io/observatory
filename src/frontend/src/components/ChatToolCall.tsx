import { useState, useCallback } from "react";
import {
  ChevronDown,
  ChevronRight,
  Wrench,
  Loader2,
  CheckCircle2,
  XCircle,
  Copy,
  Check,
} from "lucide-react";

export interface ToolCallData {
  id?: string;
  tool: string;
  input: Record<string, unknown>;
  result?: Record<string, unknown> | unknown;
  status?: "running" | "succeeded" | "failed";
  started_at?: string;
  completed_at?: string;
}

function toolSummary(tc: ToolCallData): string {
  const inp = tc.input;
  if (typeof inp.path === "string") return inp.path;
  if (typeof inp.query === "string") return inp.query.slice(0, 60);
  if (typeof inp.pattern === "string") return inp.pattern;
  if (typeof inp.directory === "string") return inp.directory;
  if (typeof inp.repository === "string") return inp.repository;
  if (typeof inp.action === "string") return inp.action;
  if (typeof inp.slug === "string") return inp.slug;
  const first = Object.values(inp).find((v) => typeof v === "string");
  if (typeof first === "string") return first.slice(0, 50);
  return "";
}

function humanToolName(name: string): string {
  return name.replace(/_/g, " ");
}

function CopyJsonButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(() => {
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [text]);

  return (
    <button
      onClick={handleCopy}
      className="p-0.5 rounded hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
      aria-label={copied ? "Copied" : "Copy JSON"}
    >
      {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
    </button>
  );
}

function StatusIcon({ status }: { status?: string }) {
  switch (status) {
    case "succeeded":
      return <CheckCircle2 className="w-3.5 h-3.5 text-green-500 flex-shrink-0" />;
    case "failed":
      return <XCircle className="w-3.5 h-3.5 text-red-500 flex-shrink-0" />;
    case "running":
      return <Loader2 className="w-3.5 h-3.5 text-blue-500 animate-spin flex-shrink-0" />;
    default:
      return <Wrench className="w-3.5 h-3.5 text-gray-500 flex-shrink-0" />;
  }
}

export default function ChatToolCall({
  tc,
  expanded,
  onToggle,
}: {
  tc: ToolCallData;
  expanded: boolean;
  onToggle: () => void;
}) {
  const summary = toolSummary(tc);

  return (
    <div className="min-h-[40px]">
      <button
        className="flex items-center gap-2 w-full text-left py-1.5 px-2 rounded hover:bg-gray-100 dark:hover:bg-gray-700/50 transition-colors text-xs"
        onClick={onToggle}
        aria-expanded={expanded}
      >
        <StatusIcon status={tc.status} />
        <span className="font-medium text-gray-700 dark:text-gray-300">
          {humanToolName(tc.tool)}
        </span>
        {summary && (
          <span className="text-gray-400 dark:text-gray-500 truncate max-w-[200px]">{summary}</span>
        )}
        <span className="ml-auto flex-shrink-0">
          {expanded ? (
            <ChevronDown className="w-3.5 h-3.5 text-gray-400" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5 text-gray-400" />
          )}
        </span>
      </button>
      {expanded && (
        <div className="ml-6 mt-1 space-y-2 text-xs">
          <div>
            <div className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-1">
              <span>Input</span>
              <CopyJsonButton text={JSON.stringify(tc.input, null, 2)} />
            </div>
            <pre className="bg-gray-100 dark:bg-gray-900 rounded p-2 overflow-x-auto whitespace-pre-wrap text-gray-700 dark:text-gray-300 max-h-40 overflow-y-auto">
              {JSON.stringify(tc.input, null, 2)}
            </pre>
          </div>
          {tc.result !== undefined && (
            <div>
              <div className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-1">
                <span>Result</span>
                <CopyJsonButton text={JSON.stringify(tc.result, null, 2)} />
              </div>
              <pre className="bg-gray-100 dark:bg-gray-900 rounded p-2 overflow-x-auto whitespace-pre-wrap text-gray-700 dark:text-gray-300 max-h-60 overflow-y-auto">
                {JSON.stringify(tc.result, null, 2)}
              </pre>
            </div>
          )}
          {tc.status === "running" && (
            <div className="flex items-center gap-1.5 text-gray-400 py-1">
              <Loader2 className="w-3 h-3 animate-spin" />
              <span>Running...</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
