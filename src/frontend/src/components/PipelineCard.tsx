import { useNavigate } from "react-router-dom";
import { ExternalLink } from "lucide-react";
import HealthDot from "./HealthDot";
import type { Pipeline } from "../pages/StatusBoard";

const PLATFORM_CLASSES: Record<string, string> = {
  gitlab: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  github: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
};

const STATUS_CLASSES: Record<string, string> = {
  production: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  development: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-300",
  deprecated: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
};

const DEFAULT_BADGE = "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300";

function cronToHuman(cron: string | null): string {
  if (!cron) return "On demand";
  const parts = cron.split(/\s+/);
  if (parts.length < 5) return cron;
  const minute = parts[0] ?? "";
  const hour = parts[1] ?? "";
  const dayOfMonth = parts[2] ?? "";
  const dayOfWeek = parts[4] ?? "";
  if (minute === "*" && hour === "*") return "Every minute";
  if (hour === "*") {
    const interval = minute.startsWith("*/") ? minute.slice(2) : null;
    if (interval) return `Every ${interval} min`;
    return `At minute ${minute}`;
  }
  if (hour.startsWith("*/")) return `Every ${hour.slice(2)}h`;
  if (dayOfMonth === "*" && dayOfWeek === "*" && !hour.includes("/") && !hour.includes(",")) {
    return `Daily at ${hour.padStart(2, "0")}:${minute.padStart(2, "0")}`;
  }
  return cron;
}

interface PipelineCardProps {
  pipeline: Pipeline;
}

function PipelineCard({ pipeline }: PipelineCardProps) {
  const navigate = useNavigate();

  return (
    <div
      onClick={() => navigate(`/pipelines/${pipeline.slug}`)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          navigate(`/pipelines/${pipeline.slug}`);
        }
      }}
      role="link"
      tabIndex={0}
      className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-5 cursor-pointer transition-all duration-200 hover:border-primary-300 dark:hover:border-primary-600 hover:shadow-md flex flex-col gap-3"
    >
      {/* Top row: health dot + name + repo link */}
      <div className="flex items-center gap-2.5">
        <HealthDot health={pipeline.health} size={14} />
        <span className="text-base font-semibold text-gray-900 dark:text-gray-100 truncate flex-1">
          {pipeline.name}
        </span>
        {pipeline.repo_url && (
          <a
            href={pipeline.repo_url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            title="Open repository"
            className="text-gray-400 dark:text-gray-500 hover:text-primary-600 dark:hover:text-primary-400 flex-shrink-0 transition-colors"
          >
            <ExternalLink size={14} />
          </a>
        )}
      </div>

      {/* Badges */}
      <div className="flex gap-2 flex-wrap">
        <span
          className={`text-[0.7rem] font-semibold px-2 py-0.5 rounded-full uppercase tracking-wide ${
            PLATFORM_CLASSES[pipeline.platform] ?? DEFAULT_BADGE
          }`}
        >
          {pipeline.platform}
        </span>
        <span
          className={`text-[0.7rem] font-semibold px-2 py-0.5 rounded-full uppercase tracking-wide ${
            STATUS_CLASSES[pipeline.status] ?? DEFAULT_BADGE
          }`}
        >
          {pipeline.status}
        </span>
      </div>

      {/* Description */}
      {pipeline.description && (
        <p className="text-sm text-gray-500 dark:text-gray-400 leading-relaxed line-clamp-2">
          {pipeline.description}
        </p>
      )}

      {/* Footer: schedule + owner */}
      <div className="flex justify-between items-center text-xs text-gray-500 dark:text-gray-400 mt-auto">
        <span>{cronToHuman(pipeline.cron)}</span>
        {pipeline.owner && <span>{pipeline.owner}</span>}
      </div>
    </div>
  );
}

export default PipelineCard;
