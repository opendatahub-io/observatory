import { Outlet, useLocation } from "react-router-dom";
import { Sun, Moon, Monitor } from "lucide-react";
import { useState } from "react";
import Sidebar from "./components/Sidebar";
import { useTheme } from "./hooks/useTheme";

const STORAGE_KEY = "observatory_sidebar_collapsed";

function getPageTitle(pathname: string): string {
  if (pathname === "/") return "Status Board";
  if (pathname === "/artifacts") return "Artifacts";
  if (pathname === "/telemetry") return "Telemetry";
  if (pathname === "/provenance") return "Provenance";
  if (pathname === "/vulnerabilities") return "Vulnerabilities";
  if (pathname === "/hallucinations") return "Hallucinations";
  if (pathname === "/agent-traces") return "Traces";
  if (pathname === "/otel-explorer") return "OTEL Explorer";
  if (pathname === "/chat") return "Chat";
  if (pathname === "/knowledge-base") return "Knowledge Base";
  if (pathname === "/intelligence-settings") return "Intelligence Settings";
  if (pathname === "/collector") return "Collector";
  if (pathname === "/admin") return "Admin";
  if (pathname.endsWith("/diff")) return "Provenance Diff";
  if (pathname.startsWith("/pipelines/")) return "Pipeline Detail";
  if (pathname.startsWith("/traces/")) return "Trace Explorer";
  if (pathname.startsWith("/sboms/")) return "SBOM Viewer";
  return "Observatory";
}

function Layout() {
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem(STORAGE_KEY) === "true",
  );
  const { mode, cycleTheme } = useTheme();
  const location = useLocation();
  const title = getPageTitle(location.pathname);

  function toggleCollapse() {
    setCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem(STORAGE_KEY, String(next));
      return next;
    });
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      <Sidebar collapsed={collapsed} onToggleCollapse={toggleCollapse} />

      <div
        className="min-h-screen transition-all duration-300 ease-[cubic-bezier(0.25,0.1,0.25,1)]"
        style={{ paddingLeft: collapsed ? 72 : 260 }}
      >
        {/* Top bar */}
        <header className="sticky top-0 z-10 bg-white/80 dark:bg-gray-800/80 backdrop-blur-xl border-b border-gray-200/60 dark:border-gray-700/60">
          <div className="flex items-center justify-between px-6 lg:px-8 h-16">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
              {title}
            </h2>
            <button
              onClick={cycleTheme}
              title={`Theme: ${mode}`}
              className="p-2 text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors duration-200"
            >
              {mode === "light" && <Sun size={18} />}
              {mode === "dark" && <Moon size={18} />}
              {mode === "system" && <Monitor size={18} />}
            </button>
          </div>
        </header>

        {/* Page content */}
        <main className="px-6 lg:px-8 py-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export default Layout;
