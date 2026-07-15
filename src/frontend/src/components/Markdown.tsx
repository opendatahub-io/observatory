import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useState, useCallback, type ComponentPropsWithoutRef } from "react";
import { Copy, Check } from "lucide-react";

function CopyButton({ text }: { text: string }) {
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
      className="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
      aria-label={copied ? "Copied" : "Copy code"}
    >
      {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
    </button>
  );
}

function CodeBlock({ className, children, ...props }: ComponentPropsWithoutRef<"code">) {
  const match = /language-(\w+)/.exec(className ?? "");
  const lang = match?.[1];
  const text = String(children).replace(/\n$/, "");

  if (!className) {
    return (
      <code className="px-1 py-0.5 bg-gray-100 dark:bg-gray-700 rounded text-sm" {...props}>
        {children}
      </code>
    );
  }

  return (
    <div className="relative group my-2">
      <div className="flex items-center justify-between bg-gray-200 dark:bg-gray-700 rounded-t-lg px-3 py-1 text-xs text-gray-500 dark:text-gray-400">
        <span>{lang ?? "code"}</span>
        <CopyButton text={text} />
      </div>
      <pre className="bg-gray-100 dark:bg-gray-900 rounded-b-lg p-3 overflow-x-auto text-sm !mt-0">
        <code className={className} {...props}>
          {children}
        </code>
      </pre>
    </div>
  );
}

export default function Markdown({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        code: CodeBlock,
        a: ({ href, children, ...props }) => (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary-600 dark:text-primary-400 hover:underline"
            {...props}
          >
            {children}
          </a>
        ),
        table: ({ children, ...props }) => (
          <div className="overflow-x-auto my-2">
            <table className="min-w-full text-sm" {...props}>
              {children}
            </table>
          </div>
        ),
        pre: ({ children, ...props }) => <>{children || <pre {...props} />}</>,
      }}
    >
      {content}
    </ReactMarkdown>
  );
}
