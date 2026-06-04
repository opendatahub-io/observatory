type HealthLevel = "green" | "yellow" | "red" | "grey";

const HEALTH_BG: Record<HealthLevel, string> = {
  green: "bg-emerald-500",
  yellow: "bg-amber-500",
  red: "bg-red-500",
  grey: "bg-gray-400",
};

const HEALTH_LABELS: Record<HealthLevel, string> = {
  green: "Healthy",
  yellow: "Degraded",
  red: "Failing",
  grey: "Unknown",
};

interface HealthDotProps {
  health: string;
  size?: number;
}

function HealthDot({ health, size = 12 }: HealthDotProps) {
  const level = (
    ["green", "yellow", "red", "grey"].includes(health) ? health : "grey"
  ) as HealthLevel;

  const bg = HEALTH_BG[level];
  const label = HEALTH_LABELS[level];

  return (
    <span className="relative inline-flex items-center group">
      <span
        className={`inline-block rounded-full flex-shrink-0 ${bg}`}
        style={{ width: size, height: size }}
        aria-label={label}
      />
      <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 text-xs px-2 py-1 rounded whitespace-nowrap pointer-events-none z-20 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
        {label}
      </span>
    </span>
  );
}

export default HealthDot;
