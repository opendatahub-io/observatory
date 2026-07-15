export interface OccurrenceFilters {
  limit: number;
  offset: number;
  typeFilter: string;
  verdictFilter: string;
  jiraFilter: string;
  searchFilter: string;
  sourceFilter: string;
  sort: string;
  sortDir: "asc" | "desc";
}

export function buildOccurrenceParams(filters: OccurrenceFilters): string {
  const params = new URLSearchParams({
    limit: String(filters.limit), offset: String(filters.offset),
    sort: filters.sort, sort_dir: filters.sortDir,
  });
  if (filters.typeFilter !== "all") params.set("type", filters.typeFilter);
  if (filters.verdictFilter !== "all") params.set("verdict", filters.verdictFilter);
  if (filters.jiraFilter.trim()) params.set("jira_key", filters.jiraFilter.trim());
  if (filters.searchFilter.trim()) params.set("search", filters.searchFilter.trim());
  if (filters.sourceFilter.trim()) params.set("source", filters.sourceFilter.trim());
  return params.toString();
}

export function processingStateLabel(state: string): string {
  const labels: Record<string, string> = {
    not_verified: "not verified",
    verified_without_explanation: "verified without explanation",
    explanation_requires_human_review: "explanation requires human review",
    explained: "explained",
  };
  return labels[state] ?? state.replace(/_/g, " ");
}

export function verdictClass(verdict: string): string {
  const classes: Record<string, string> = {
    supported: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
    contradicted: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
    insufficient_evidence: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
    not_applicable: "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300",
  };
  return classes[verdict] ?? "bg-gray-100 text-gray-700";
}
