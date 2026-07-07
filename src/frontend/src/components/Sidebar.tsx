import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  BarChart3,
  Box,
  FolderOpen,
  Shield,
  AlertTriangle,
  Workflow,
  Activity,
  Radio,
  Settings,
  ChevronLeft,
  ChevronRight,
  MessageSquare,
  BookOpen,
  Settings2,
} from "lucide-react";

interface NavItem {
  to: string;
  label: string;
  icon: React.ElementType;
  end?: boolean;
}

interface NavSection {
  label?: string;
  items: NavItem[];
}

const NAV_SECTIONS: NavSection[] = [
  {
    items: [
      { to: "/", label: "Status Board", icon: LayoutDashboard, end: true },
    ],
  },
  {
    label: "Observability",
    items: [
      { to: "/artifacts", label: "Artifacts", icon: FolderOpen },
      { to: "/telemetry", label: "Telemetry", icon: BarChart3 },
      { to: "/provenance", label: "Provenance", icon: Box },
      { to: "/vulnerabilities", label: "Vulnerabilities", icon: Shield },
      { to: "/hallucinations", label: "Hallucinations", icon: AlertTriangle },
      { to: "/agent-traces", label: "Traces", icon: Workflow },
      { to: "/otel-explorer", label: "OTEL Explorer", icon: Radio },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { to: "/chat", label: "Chat", icon: MessageSquare },
      { to: "/knowledge-base", label: "Knowledge Base", icon: BookOpen },
      { to: "/intelligence-settings", label: "Settings", icon: Settings2 },
    ],
  },
  {
    label: "Operations",
    items: [{ to: "/collector", label: "Collector", icon: Activity }],
  },
  {
    label: "Admin",
    items: [{ to: "/admin", label: "Admin", icon: Settings }],
  },
];

interface SidebarProps {
  collapsed: boolean;
  onToggleCollapse: () => void;
}

export default function Sidebar({ collapsed, onToggleCollapse }: SidebarProps) {
  return (
    <aside
      className={`fixed top-0 left-0 h-screen z-30 flex flex-col transition-all duration-300 ease-[cubic-bezier(0.25,0.1,0.25,1)] ${
        collapsed ? "w-[72px]" : "w-[260px]"
      }`}
    >
      {/* Collapse toggle */}
      <button
        onClick={onToggleCollapse}
        className="absolute top-7 -right-3.5 z-10 h-7 w-7 flex items-center justify-center rounded-full bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 text-gray-400 dark:text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-700 hover:text-gray-600 dark:hover:text-gray-300 shadow-sm transition-colors duration-200"
        title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
      >
        {collapsed ? (
          <ChevronRight size={14} strokeWidth={2} />
        ) : (
          <ChevronLeft size={14} strokeWidth={2} />
        )}
      </button>

      <div className="flex flex-col h-full m-2.5 bg-white/80 dark:bg-gray-800/80 backdrop-blur-xl border border-gray-200/60 dark:border-gray-700/60 rounded-2xl shadow-[0_1px_2px_rgba(0,0,0,0.04),0_4px_16px_rgba(0,0,0,0.03)] overflow-hidden">
        {/* Header */}
        <div
          className={`flex items-center py-5 border-b border-gray-100 dark:border-gray-700 transition-all duration-300 ${
            collapsed ? "justify-center px-0" : "gap-3 px-4"
          }`}
        >
          <div className="h-8 w-8 rounded-lg bg-primary-600 text-white flex items-center justify-center font-bold text-sm flex-shrink-0">
            O
          </div>
          {!collapsed && (
            <div className="overflow-hidden whitespace-nowrap flex-1">
              <h1 className="text-sm font-bold text-gray-900 dark:text-gray-100 leading-tight">
                Observatory
              </h1>
              <p className="text-xs text-gray-400 dark:text-gray-500">
                CI Pipeline Monitor
              </p>
            </div>
          )}
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          {NAV_SECTIONS.map((section, si) => (
            <div key={si}>
              {!collapsed && section.label && (
                <p className="px-3 mb-2 mt-4 first:mt-0 text-[10px] font-semibold uppercase tracking-widest text-gray-400 dark:text-gray-500">
                  {section.label}
                </p>
              )}
              {section.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    `group relative w-full flex items-center py-2.5 rounded-xl text-sm font-medium transition-all duration-200 ${
                      collapsed ? "justify-center px-0" : "gap-3 px-3"
                    } ${
                      isActive
                        ? "bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 shadow-sm"
                        : "text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 hover:text-gray-900 dark:hover:text-gray-100"
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      <item.icon
                        size={20}
                        strokeWidth={isActive ? 2 : 1.7}
                        className="flex-shrink-0"
                      />
                      {!collapsed && (
                        <span className="truncate">{item.label}</span>
                      )}
                      {collapsed && (
                        <span className="absolute left-full ml-3 px-2.5 py-1.5 bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 text-xs font-medium rounded-lg whitespace-nowrap opacity-0 pointer-events-none group-hover:opacity-100 transition-opacity duration-200 shadow-lg">
                          {item.label}
                        </span>
                      )}
                    </>
                  )}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
      </div>
    </aside>
  );
}
