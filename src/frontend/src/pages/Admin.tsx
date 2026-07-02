import { useEffect, useState, useCallback, useRef } from "react";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface Pipeline {
  id: number;
  slug: string;
  name: string;
  repo_url: string;
  platform: string;
  description: string | null;
  owner: string | null;
  cron: string | null;
  expected_interval_minutes: number | null;
  timeout_minutes: number | null;
  status: string;
}

interface PipelineFormData {
  slug: string;
  name: string;
  repo_url: string;
  platform: string;
  description: string;
  owner: string;
  cron: string;
  expected_interval_minutes: string;
  timeout_minutes: string;
  status: string;
}

interface DbHealth {
  database_size_bytes: number;
  table_counts: Record<string, number>;
}

interface PurgeResult {
  telemetry_spans: number;
  run_commands: number;
  run_packages: number;
  run_containers: number;
}

type TableCountResult = Record<string, number>;

interface ApiKey {
  id: number;
  key_prefix: string;
  name: string;
  scopes: string[];
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  is_active: boolean;
}

interface ApiKeyCreateResponse extends ApiKey {
  key: string;
}

interface PlatformCredential {
  id: number;
  name: string;
  platform: string;
  base_url: string;
  scopes: string[];
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  is_active: boolean;
}

interface CredentialTestResult {
  success: boolean;
  message: string;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Convert an ISO timestamp to a human-readable "X ago" string. */
function timeAgo(dateString: string): string {
  const now = Date.now();
  const then = new Date(dateString).getTime();

  if (isNaN(then)) return "Invalid date";

  const diffMs = now - then;
  if (diffMs < 0) return "Just now";

  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return seconds <= 1 ? "Just now" : `${seconds} seconds ago`;

  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return minutes === 1 ? "1 minute ago" : `${minutes} minutes ago`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return hours === 1 ? "1 hour ago" : `${hours} hours ago`;

  const days = Math.floor(hours / 24);
  if (days < 30) return days === 1 ? "1 day ago" : `${days} days ago`;

  const months = Math.floor(days / 30);
  return months === 1 ? "1 month ago" : `${months} months ago`;
}

/** Format bytes into a human-readable string. */
function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  const value = bytes / Math.pow(1024, i);
  return `${value.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

const EMPTY_FORM: PipelineFormData = {
  slug: "",
  name: "",
  repo_url: "",
  platform: "github",
  description: "",
  owner: "",
  cron: "",
  expected_interval_minutes: "",
  timeout_minutes: "",
  status: "production",
};

/* ------------------------------------------------------------------ */
/*  Tailwind class helpers                                             */
/* ------------------------------------------------------------------ */

const tw = {
  btn: "text-sm font-medium px-4 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all cursor-pointer",
  btnPrimary: "bg-primary-600 text-white border-primary-600 hover:bg-primary-700",
  btnDanger: "bg-red-600 text-white border-red-600 hover:bg-red-700",
  btnSmall: "text-xs font-medium px-2.5 py-1 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer transition-all",
  btnTest: "bg-amber-500 text-white border-amber-500 hover:bg-amber-600",
  table: "w-full text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden",
  th: "text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700",
  td: "px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100",
  formInput: "text-sm px-3 py-2 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 disabled:bg-gray-100 dark:disabled:bg-gray-800 disabled:text-gray-400",
};

function statusBadgeClasses(status: string): string {
  const base = "inline-block text-xs font-semibold px-2.5 py-0.5 rounded-full";
  switch (status) {
    case "production":
      return `${base} bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300`;
    case "development":
      return `${base} bg-indigo-100 text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-300`;
    case "deprecated":
      return `${base} bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300`;
    default:
      return `${base} bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300`;
  }
}

function platformBadgeClasses(platform: string): string {
  const base = "inline-block text-xs font-semibold px-2.5 py-0.5 rounded-full";
  switch (platform) {
    case "gitlab":
      return `${base} bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300`;
    case "github":
      return `${base} bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300`;
    default:
      return `${base} bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300`;
  }
}

/* ------------------------------------------------------------------ */
/*  Scope Selector (shared by API Keys and Platform Credentials)       */
/* ------------------------------------------------------------------ */

function ScopeSelector({
  selectedScopes,
  allPipelinesChecked,
  pipelineSlugs,
  onToggleAll,
  onToggleSlug,
}: {
  selectedScopes: string[];
  allPipelinesChecked: boolean;
  pipelineSlugs: string[];
  onToggleAll: () => void;
  onToggleSlug: (slug: string) => void;
}) {
  return (
    <div className="mt-1">
      <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300 cursor-pointer">
        <input
          type="checkbox"
          checked={allPipelinesChecked}
          onChange={onToggleAll}
        />
        All Pipelines
      </label>
      {!allPipelinesChecked && (
        <div className="ml-6 mt-2 flex flex-col gap-1.5">
          {pipelineSlugs.length === 0 && (
            <span className="text-xs text-gray-400 dark:text-gray-500">No pipelines available</span>
          )}
          {pipelineSlugs.map((slug) => (
            <label key={slug} className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300 cursor-pointer">
              <input
                type="checkbox"
                checked={selectedScopes.includes(slug)}
                onChange={() => onToggleSlug(slug)}
              />
              {slug}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

/** Render scope badges */
function ScopeBadges({ scopes }: { scopes: string[] }) {
  if (scopes.length === 1 && scopes[0] === "*") {
    return <span className="inline-block text-xs font-semibold px-2.5 py-0.5 rounded-full bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300">All Pipelines</span>;
  }
  return (
    <span className="flex gap-1 flex-wrap">
      {scopes.map((s) => (
        <span key={s} className="inline-block text-xs font-medium px-2 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300">{s}</span>
      ))}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

function Admin() {
  /* ---------- Pipeline management state ---------- */
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [pipelinesLoading, setPipelinesLoading] = useState(true);
  const [pipelinesError, setPipelinesError] = useState<string | null>(null);
  const [pipelineMsg, setPipelineMsg] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editingSlug, setEditingSlug] = useState<string | null>(null);
  const [formData, setFormData] = useState<PipelineFormData>(EMPTY_FORM);

  const pipelineMsgTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  /* ---------- Database health state ---------- */
  const [dbHealth, setDbHealth] = useState<DbHealth | null>(null);
  const [dbHealthLoading, setDbHealthLoading] = useState(true);

  /* ---------- Purge state ---------- */
  const [purging, setPurging] = useState(false);
  const [purgeResult, setPurgeResult] = useState<PurgeResult | null>(null);
  const [wipingRuntimeData, setWipingRuntimeData] = useState(false);
  const [runtimeWipeResult, setRuntimeWipeResult] = useState<TableCountResult | null>(null);

  /* ---------- Claims clear state ---------- */
  const [clearingClaims, setClearingClaims] = useState(false);
  const [clearClaimsResult, setClearClaimsResult] = useState<Record<string, number> | null>(null);

  /* ---------- API Keys state ---------- */
  const [apiKeys, setApiKeys] = useState<ApiKey[]>([]);
  const [apiKeysLoading, setApiKeysLoading] = useState(true);
  const [apiKeysError, setApiKeysError] = useState<string | null>(null);
  const [apiKeysMsg, setApiKeysMsg] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [showApiKeyForm, setShowApiKeyForm] = useState(false);
  const [apiKeyName, setApiKeyName] = useState("");
  const [apiKeyAllScopes, setApiKeyAllScopes] = useState(true);
  const [apiKeyScopes, setApiKeyScopes] = useState<string[]>([]);
  const [apiKeyExpires, setApiKeyExpires] = useState("");
  const [createdApiKey, setCreatedApiKey] = useState<string | null>(null);
  const [apiKeyCopied, setApiKeyCopied] = useState(false);

  const apiKeysMsgTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  /* ---------- Platform Credentials state ---------- */
  const [credentials, setCredentials] = useState<PlatformCredential[]>([]);
  const [credentialsLoading, setCredentialsLoading] = useState(true);
  const [credentialsError, setCredentialsError] = useState<string | null>(null);
  const [credentialsMsg, setCredentialsMsg] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [showCredentialForm, setShowCredentialForm] = useState(false);
  const [editingCredentialId, setEditingCredentialId] = useState<number | null>(null);
  const [credName, setCredName] = useState("");
  const [credPlatform, setCredPlatform] = useState("gitlab");
  const [credBaseUrl, setCredBaseUrl] = useState("");
  const [credToken, setCredToken] = useState("");
  const [credAllScopes, setCredAllScopes] = useState(true);
  const [credScopes, setCredScopes] = useState<string[]>([]);
  const [credExpires, setCredExpires] = useState("");
  const [testResults, setTestResults] = useState<Record<number, CredentialTestResult>>({});
  const [testingId, setTestingId] = useState<number | null>(null);

  const credentialsMsgTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  /* ================================================================ */
  /*  Fetch functions                                                  */
  /* ================================================================ */

  /* ---------- Fetch pipelines ---------- */

  const fetchPipelines = useCallback(async () => {
    setPipelinesLoading(true);
    setPipelinesError(null);
    try {
      const res = await fetch("/api/pipelines");
      if (!res.ok) {
        setPipelinesError(`API returned ${res.status}`);
        return;
      }
      const json = await res.json();
      setPipelines(json.pipelines ?? []);
    } catch {
      setPipelinesError("Failed to load pipelines");
    } finally {
      setPipelinesLoading(false);
    }
  }, []);

  /* ---------- Fetch DB health ---------- */

  const fetchDbHealth = useCallback(async () => {
    setDbHealthLoading(true);
    try {
      const res = await fetch("/api/admin/db-health");
      if (res.ok) {
        setDbHealth(await res.json());
      }
    } catch {
      // Silently ignore — section just stays empty
    } finally {
      setDbHealthLoading(false);
    }
  }, []);

  /* ---------- Fetch API keys ---------- */

  const fetchApiKeys = useCallback(async () => {
    setApiKeysLoading(true);
    setApiKeysError(null);
    try {
      const res = await fetch("/api/admin/api-keys");
      if (!res.ok) {
        setApiKeysError(`API returned ${res.status}`);
        return;
      }
      const json: ApiKey[] = await res.json();
      setApiKeys(json);
    } catch {
      setApiKeysError("Failed to load API keys");
    } finally {
      setApiKeysLoading(false);
    }
  }, []);

  /* ---------- Fetch credentials ---------- */

  const fetchCredentials = useCallback(async () => {
    setCredentialsLoading(true);
    setCredentialsError(null);
    try {
      const res = await fetch("/api/admin/credentials");
      if (!res.ok) {
        setCredentialsError(`API returned ${res.status}`);
        return;
      }
      const json: PlatformCredential[] = await res.json();
      setCredentials(json);
    } catch {
      setCredentialsError("Failed to load credentials");
    } finally {
      setCredentialsLoading(false);
    }
  }, []);

  /* ================================================================ */
  /*  Effects                                                          */
  /* ================================================================ */

  /* ---------- Initial fetch ---------- */

  useEffect(() => {
    void fetchPipelines();
    void fetchDbHealth();
    void fetchApiKeys();
    void fetchCredentials();
  }, [fetchPipelines, fetchDbHealth, fetchApiKeys, fetchCredentials]);

  /* ---------- Cleanup ---------- */

  useEffect(() => {
    return () => {
      if (pipelineMsgTimerRef.current) clearTimeout(pipelineMsgTimerRef.current);
      if (apiKeysMsgTimerRef.current) clearTimeout(apiKeysMsgTimerRef.current);
      if (credentialsMsgTimerRef.current) clearTimeout(credentialsMsgTimerRef.current);
    };
  }, []);

  /* ================================================================ */
  /*  Actions                                                          */
  /* ================================================================ */

  /* ---------- Pipeline CRUD helpers ---------- */

  const showPipelineMsg = (type: "success" | "error", text: string) => {
    setPipelineMsg({ type, text });
    if (pipelineMsgTimerRef.current) clearTimeout(pipelineMsgTimerRef.current);
    pipelineMsgTimerRef.current = setTimeout(() => setPipelineMsg(null), 4000);
  };

  const resetForm = () => {
    setFormData(EMPTY_FORM);
    setEditingSlug(null);
    setShowForm(false);
  };

  const handleFormChange = (field: keyof PipelineFormData, value: string) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
  };

  const handleAddClick = () => {
    setFormData(EMPTY_FORM);
    setEditingSlug(null);
    setShowForm(true);
  };

  const handleEditClick = (p: Pipeline) => {
    setFormData({
      slug: p.slug,
      name: p.name,
      repo_url: p.repo_url,
      platform: p.platform,
      description: p.description ?? "",
      owner: p.owner ?? "",
      cron: p.cron ?? "",
      expected_interval_minutes: p.expected_interval_minutes?.toString() ?? "",
      timeout_minutes: p.timeout_minutes?.toString() ?? "",
      status: p.status ?? "production",
    });
    setEditingSlug(p.slug);
    setShowForm(true);
  };

  const handleDeleteClick = async (slug: string) => {
    if (!window.confirm(`Are you sure you want to delete pipeline "${slug}"?`)) return;
    try {
      const res = await fetch(`/api/pipelines/${encodeURIComponent(slug)}`, { method: "DELETE" });
      if (res.status === 204 || res.ok) {
        showPipelineMsg("success", `Pipeline "${slug}" deleted.`);
        void fetchPipelines();
      } else {
        showPipelineMsg("error", `Delete failed (${res.status})`);
      }
    } catch {
      showPipelineMsg("error", "Delete failed (network error)");
    }
  };

  const handleFormSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    const body: Record<string, unknown> = {
      slug: formData.slug,
      name: formData.name,
      repo_url: formData.repo_url,
      platform: formData.platform,
    };
    if (formData.description) body.description = formData.description;
    if (formData.owner) body.owner = formData.owner;
    if (formData.cron) body.cron = formData.cron;
    if (formData.expected_interval_minutes)
      body.expected_interval_minutes = parseInt(formData.expected_interval_minutes, 10);
    if (formData.timeout_minutes)
      body.timeout_minutes = parseInt(formData.timeout_minutes, 10);
    if (formData.status) body.status = formData.status;

    try {
      let res: Response;
      if (editingSlug) {
        res = await fetch(`/api/pipelines/${encodeURIComponent(editingSlug)}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
      } else {
        res = await fetch("/api/pipelines", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
      }

      if (res.ok || res.status === 201) {
        showPipelineMsg("success", editingSlug ? "Pipeline updated." : "Pipeline created.");
        resetForm();
        void fetchPipelines();
      } else {
        const errBody = await res.json().catch(() => null);
        const detail = errBody?.detail ?? `Error ${res.status}`;
        showPipelineMsg("error", typeof detail === "string" ? detail : JSON.stringify(detail));
      }
    } catch {
      showPipelineMsg("error", "Request failed (network error)");
    }
  };

  /* ---------- Purge ---------- */

  const handlePurge = async () => {
    setPurging(true);
    setPurgeResult(null);
    try {
      const res = await fetch("/api/admin/purge", { method: "POST" });
      if (res.ok) {
        const result: PurgeResult = await res.json();
        setPurgeResult(result);
        // Refresh DB health after purge
        void fetchDbHealth();
      }
    } catch {
      // Silently ignore
    } finally {
      setPurging(false);
    }
  };

  const handleRuntimeDataWipe = async () => {
    const confirmation = window.prompt(
      "This deletes all collected runtime data regardless of retention settings. Type WIPE to continue."
    );
    if (confirmation !== "WIPE") return;

    setWipingRuntimeData(true);
    setRuntimeWipeResult(null);
    try {
      const res = await fetch("/api/admin/wipe-runtime-data", { method: "POST" });
      if (res.ok) {
        setRuntimeWipeResult(await res.json());
        void fetchDbHealth();
      }
    } catch {
      // Silently ignore
    } finally {
      setWipingRuntimeData(false);
    }
  };

  /* ---------- Clear claims ---------- */

  const handleClearClaims = async () => {
    if (!window.confirm("Delete ALL hallucination data? This removes all claims, verdicts, explanations, and jira key links. This cannot be undone.")) return;
    setClearingClaims(true);
    setClearClaimsResult(null);
    try {
      const res = await fetch("/api/hallucinations/all", { method: "DELETE" });
      if (res.ok) {
        setClearClaimsResult(await res.json());
        void fetchDbHealth();
      }
    } catch { /* ignore */ }
    finally { setClearingClaims(false); }
  };

  /* ---------- API Key helpers ---------- */

  const showApiKeysMsg = (type: "success" | "error", text: string) => {
    setApiKeysMsg({ type, text });
    if (apiKeysMsgTimerRef.current) clearTimeout(apiKeysMsgTimerRef.current);
    apiKeysMsgTimerRef.current = setTimeout(() => setApiKeysMsg(null), 4000);
  };

  const resetApiKeyForm = () => {
    setApiKeyName("");
    setApiKeyAllScopes(true);
    setApiKeyScopes([]);
    setApiKeyExpires("");
    setShowApiKeyForm(false);
  };

  const handleCreateApiKey = async (e: React.FormEvent) => {
    e.preventDefault();
    const scopes = apiKeyAllScopes ? ["*"] : apiKeyScopes;
    if (scopes.length === 0) {
      showApiKeysMsg("error", "Select at least one scope.");
      return;
    }
    const body: Record<string, unknown> = { name: apiKeyName, scopes };
    if (apiKeyExpires) body.expires_at = apiKeyExpires;

    try {
      const res = await fetch("/api/admin/api-keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.status === 201 || res.ok) {
        const created: ApiKeyCreateResponse = await res.json();
        setCreatedApiKey(created.key);
        setApiKeyCopied(false);
        resetApiKeyForm();
        void fetchApiKeys();
      } else {
        const errBody = await res.json().catch(() => null);
        showApiKeysMsg("error", errBody?.detail ?? `Error ${res.status}`);
      }
    } catch {
      showApiKeysMsg("error", "Request failed (network error)");
    }
  };

  const handleRevokeApiKey = async (id: number, name: string) => {
    if (!window.confirm(`Revoke API key "${name}"? This cannot be undone.`)) return;
    try {
      const res = await fetch(`/api/admin/api-keys/${id}`, { method: "DELETE" });
      if (res.status === 204 || res.ok) {
        showApiKeysMsg("success", `API key "${name}" revoked.`);
        void fetchApiKeys();
      } else {
        showApiKeysMsg("error", `Revoke failed (${res.status})`);
      }
    } catch {
      showApiKeysMsg("error", "Revoke failed (network error)");
    }
  };

  const handleCopyApiKey = async () => {
    if (!createdApiKey) return;
    try {
      await navigator.clipboard.writeText(createdApiKey);
      setApiKeyCopied(true);
    } catch {
      // Fallback: select the text for manual copy
    }
  };

  /* ---------- Credential helpers ---------- */

  const showCredentialsMsg = (type: "success" | "error", text: string) => {
    setCredentialsMsg({ type, text });
    if (credentialsMsgTimerRef.current) clearTimeout(credentialsMsgTimerRef.current);
    credentialsMsgTimerRef.current = setTimeout(() => setCredentialsMsg(null), 4000);
  };

  const resetCredentialForm = () => {
    setCredName("");
    setCredPlatform("gitlab");
    setCredBaseUrl("");
    setCredToken("");
    setCredAllScopes(true);
    setCredScopes([]);
    setCredExpires("");
    setEditingCredentialId(null);
    setShowCredentialForm(false);
  };

  const handleAddCredentialClick = () => {
    resetCredentialForm();
    setShowCredentialForm(true);
  };

  const handleEditCredentialClick = (c: PlatformCredential) => {
    setCredName(c.name);
    setCredPlatform(c.platform);
    setCredBaseUrl(c.base_url);
    setCredToken(""); // never pre-fill the token
    if (c.scopes.length === 1 && c.scopes[0] === "*") {
      setCredAllScopes(true);
      setCredScopes([]);
    } else {
      setCredAllScopes(false);
      setCredScopes([...c.scopes]);
    }
    setCredExpires(c.expires_at ? c.expires_at.slice(0, 10) : "");
    setEditingCredentialId(c.id);
    setShowCredentialForm(true);
  };

  const handleCredentialSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const scopes = credAllScopes ? ["*"] : credScopes;
    if (scopes.length === 0) {
      showCredentialsMsg("error", "Select at least one scope.");
      return;
    }

    try {
      let res: Response;
      if (editingCredentialId !== null) {
        const body: Record<string, unknown> = { name: credName, scopes };
        if (credToken) body.token = credToken;
        if (credExpires) body.expires_at = credExpires;
        res = await fetch(`/api/admin/credentials/${editingCredentialId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
      } else {
        const body: Record<string, unknown> = {
          name: credName,
          platform: credPlatform,
          base_url: credBaseUrl,
          token: credToken,
          scopes,
        };
        if (credExpires) body.expires_at = credExpires;
        res = await fetch("/api/admin/credentials", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
      }

      if (res.ok || res.status === 201) {
        showCredentialsMsg("success", editingCredentialId ? "Credential updated." : "Credential created.");
        resetCredentialForm();
        void fetchCredentials();
      } else {
        const errBody = await res.json().catch(() => null);
        const detail = errBody?.detail ?? `Error ${res.status}`;
        showCredentialsMsg("error", typeof detail === "string" ? detail : JSON.stringify(detail));
      }
    } catch {
      showCredentialsMsg("error", "Request failed (network error)");
    }
  };

  const handleTestCredential = async (id: number) => {
    setTestingId(id);
    try {
      const res = await fetch(`/api/admin/credentials/${id}/test`, { method: "POST" });
      if (res.ok) {
        const result: CredentialTestResult = await res.json();
        setTestResults((prev) => ({ ...prev, [id]: result }));
      } else {
        setTestResults((prev) => ({ ...prev, [id]: { success: false, message: `HTTP ${res.status}` } }));
      }
    } catch {
      setTestResults((prev) => ({ ...prev, [id]: { success: false, message: "Network error" } }));
    } finally {
      setTestingId(null);
    }
  };

  const handleRevokeCredential = async (id: number, name: string) => {
    if (!window.confirm(`Revoke credential "${name}"? This cannot be undone.`)) return;
    try {
      const res = await fetch(`/api/admin/credentials/${id}`, { method: "DELETE" });
      if (res.status === 204 || res.ok) {
        showCredentialsMsg("success", `Credential "${name}" revoked.`);
        void fetchCredentials();
      } else {
        showCredentialsMsg("error", `Revoke failed (${res.status})`);
      }
    } catch {
      showCredentialsMsg("error", "Revoke failed (network error)");
    }
  };

  /* Pipeline slugs for scope selectors */
  const pipelineSlugs = pipelines.map((p) => p.slug);

  /* ================================================================ */
  /*  Render                                                           */
  /* ================================================================ */

  return (
    <div>
      {/* ============================================================ */}
      {/* Header                                                        */}
      {/* ============================================================ */}
      <div className="flex justify-between items-center mb-2 flex-wrap gap-3">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Admin</h1>
      </div>

      <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
        Pipeline management, database health, and system configuration.
      </p>

      {/* ============================================================ */}
      {/* Pipeline Management                                           */}
      {/* ============================================================ */}
      <div className="mb-10">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Pipeline Management</h2>
          <button
            className={`${tw.btn} ${tw.btnPrimary}`}
            onClick={handleAddClick}
          >
            Add Pipeline
          </button>
        </div>

        {/* Feedback message */}
        {pipelineMsg && (
          <div
            className={
              pipelineMsg.type === "success"
                ? "text-sm text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-lg px-4 py-2 mb-4"
                : "text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg px-4 py-2 mb-4"
            }
          >
            {pipelineMsg.text}
          </div>
        )}

        {/* Inline form */}
        {showForm && (
          <form className="bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700 rounded-xl p-5 mb-4" onSubmit={(e) => void handleFormSubmit(e)}>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3.5">
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-gray-700 dark:text-gray-300">Slug</span>
                <input
                  type="text"
                  className={tw.formInput}
                  value={formData.slug}
                  onChange={(e) => handleFormChange("slug", e.target.value)}
                  required
                  disabled={editingSlug !== null}
                  placeholder="my-pipeline"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-gray-700 dark:text-gray-300">Name</span>
                <input
                  type="text"
                  className={tw.formInput}
                  value={formData.name}
                  onChange={(e) => handleFormChange("name", e.target.value)}
                  required
                  placeholder="My Pipeline"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-gray-700 dark:text-gray-300">Repository URL</span>
                <input
                  type="url"
                  className={tw.formInput}
                  value={formData.repo_url}
                  onChange={(e) => handleFormChange("repo_url", e.target.value)}
                  required
                  placeholder="https://github.com/org/repo"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-gray-700 dark:text-gray-300">Platform</span>
                <select
                  className={tw.formInput}
                  value={formData.platform}
                  onChange={(e) => handleFormChange("platform", e.target.value)}
                >
                  <option value="github">github</option>
                  <option value="gitlab">gitlab</option>
                </select>
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-gray-700 dark:text-gray-300">Description</span>
                <input
                  type="text"
                  className={tw.formInput}
                  value={formData.description}
                  onChange={(e) => handleFormChange("description", e.target.value)}
                  placeholder="Optional description"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-gray-700 dark:text-gray-300">Owner</span>
                <input
                  type="text"
                  className={tw.formInput}
                  value={formData.owner}
                  onChange={(e) => handleFormChange("owner", e.target.value)}
                  placeholder="team-name"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-gray-700 dark:text-gray-300">Cron</span>
                <input
                  type="text"
                  className={tw.formInput}
                  value={formData.cron}
                  onChange={(e) => handleFormChange("cron", e.target.value)}
                  placeholder="0 */6 * * *"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-gray-700 dark:text-gray-300">Expected Interval (min)</span>
                <input
                  type="number"
                  className={tw.formInput}
                  value={formData.expected_interval_minutes}
                  onChange={(e) => handleFormChange("expected_interval_minutes", e.target.value)}
                  placeholder="360"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-gray-700 dark:text-gray-300">Timeout (min)</span>
                <input
                  type="number"
                  className={tw.formInput}
                  value={formData.timeout_minutes}
                  onChange={(e) => handleFormChange("timeout_minutes", e.target.value)}
                  placeholder="60"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-gray-700 dark:text-gray-300">Status</span>
                <select
                  className={tw.formInput}
                  value={formData.status}
                  onChange={(e) => handleFormChange("status", e.target.value)}
                >
                  <option value="production">production</option>
                  <option value="development">development</option>
                  <option value="deprecated">deprecated</option>
                </select>
              </label>
            </div>
            <div className="flex gap-3 mt-4">
              <button type="submit" className={`${tw.btn} ${tw.btnPrimary}`}>
                {editingSlug ? "Update Pipeline" : "Create Pipeline"}
              </button>
              <button type="button" className={tw.btn} onClick={resetForm}>
                Cancel
              </button>
            </div>
          </form>
        )}

        {/* Pipelines table */}
        {pipelinesLoading && pipelines.length === 0 && (
          <div className="text-center py-8 text-gray-500 dark:text-gray-400">Loading pipelines...</div>
        )}
        {pipelinesError && (
          <div className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg px-4 py-2 mb-4">{pipelinesError}</div>
        )}
        {!pipelinesLoading && !pipelinesError && pipelines.length === 0 && (
          <div className="text-center py-8 text-gray-500 dark:text-gray-400">No pipelines found.</div>
        )}
        {pipelines.length > 0 && (
          <table className={tw.table}>
            <thead>
              <tr>
                <th className={tw.th}>Name</th>
                <th className={tw.th}>Slug</th>
                <th className={tw.th}>Platform</th>
                <th className={tw.th}>Owner</th>
                <th className={tw.th}>Status</th>
                <th className={tw.th}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {pipelines.map((p) => (
                <tr key={p.id}>
                  <td className={tw.td}>{p.name}</td>
                  <td className={tw.td}><code>{p.slug}</code></td>
                  <td className={tw.td}>{p.platform}</td>
                  <td className={tw.td}>{p.owner ?? "-"}</td>
                  <td className={tw.td}>
                    <span className={statusBadgeClasses(p.status)}>
                      {p.status}
                    </span>
                  </td>
                  <td className={tw.td}>
                    <div className="flex gap-1.5">
                      <button
                        className={tw.btnSmall}
                        onClick={() => handleEditClick(p)}
                      >
                        Edit
                      </button>
                      <button
                        className={`${tw.btnSmall} ${tw.btnDanger}`}
                        onClick={() => void handleDeleteClick(p.slug)}
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ============================================================ */}
      {/* Database Health                                                */}
      {/* ============================================================ */}
      <div className="mb-10">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Database Health</h2>
          <button className={tw.btn} onClick={() => void fetchDbHealth()}>
            Refresh
          </button>
        </div>

        {dbHealthLoading && !dbHealth && (
          <div className="text-center py-8 text-gray-500 dark:text-gray-400">Loading database health...</div>
        )}

        {dbHealth && (
          <>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
              Database size: <strong>{formatBytes(dbHealth.database_size_bytes)}</strong>
            </p>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
              {Object.entries(dbHealth.table_counts).map(([table, count]) => (
                <div key={table} className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-3 text-center">
                  <div className="text-xl font-bold text-gray-900 dark:text-gray-100">{count.toLocaleString()}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400 capitalize">{table.replace(/_/g, " ")}</div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {/* ============================================================ */}
      {/* Data Retention Settings                                       */}
      {/* ============================================================ */}
      <div className="mb-10">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Data Retention Settings</h2>

        <table className={tw.table}>
          <thead>
            <tr>
              <th className={tw.th}>Data</th>
              <th className={tw.th}>Retention</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className={tw.td}>telemetry_spans</td>
              <td className={tw.td}>90 days</td>
            </tr>
            <tr>
              <td className={tw.td}>run_commands</td>
              <td className={tw.td}>180 days</td>
            </tr>
            <tr>
              <td className={tw.td}>run_packages</td>
              <td className={tw.td}>180 days</td>
            </tr>
            <tr>
              <td className={tw.td}>run_containers</td>
              <td className={tw.td}>180 days</td>
            </tr>
            <tr>
              <td className={tw.td}>Everything else</td>
              <td className={tw.td}>Kept indefinitely</td>
            </tr>
          </tbody>
        </table>

        <p className="mt-3 text-sm text-gray-600 dark:text-gray-300">
          Retention purge only deletes rows older than their retention windows.
        </p>

        <div className="flex items-center gap-4 mt-4">
          <button
            className={`${tw.btn} ${tw.btnDanger}`}
            onClick={() => void handlePurge()}
            disabled={purging}
          >
            {purging ? "Purging..." : "Run Purge Now"}
          </button>

          {purgeResult && (
            <span className="text-sm text-emerald-600 dark:text-emerald-400">
              Deleted {purgeResult.telemetry_spans} spans,{" "}
              {purgeResult.run_commands} commands,{" "}
              {purgeResult.run_packages} packages,{" "}
              {purgeResult.run_containers} containers
            </span>
          )}
        </div>

        <div className="flex items-center gap-4 mt-4">
          <button
            className={`${tw.btn} ${tw.btnDanger}`}
            onClick={() => void handleRuntimeDataWipe()}
            disabled={wipingRuntimeData}
          >
            {wipingRuntimeData ? "Wiping..." : "Wipe All Runtime Data"}
          </button>

          {runtimeWipeResult && (
            <span className="text-sm text-emerald-600 dark:text-emerald-400">
              Deleted {Object.values(runtimeWipeResult).reduce((sum, count) => sum + count, 0)} rows
            </span>
          )}
        </div>

        <div className="flex items-center gap-4 mt-4">
          <button
            className={`${tw.btn} ${tw.btnDanger}`}
            onClick={() => void handleClearClaims()}
            disabled={clearingClaims}
          >
            {clearingClaims ? "Clearing..." : "Clear All Hallucination Data"}
          </button>

          {clearClaimsResult && (
            <span className="text-sm text-emerald-600 dark:text-emerald-400">
              Deleted {clearClaimsResult.claims ?? 0} claims,{" "}
              {clearClaimsResult.claim_verdicts ?? 0} verdicts,{" "}
              {clearClaimsResult.claim_explanations ?? 0} explanations,{" "}
              {clearClaimsResult.claim_sources ?? 0} sources
            </span>
          )}
        </div>
      </div>

      {/* ============================================================ */}
      {/* API Keys                                                      */}
      {/* ============================================================ */}
      <div className="mb-10">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">API Keys</h2>
          <button
            className={`${tw.btn} ${tw.btnPrimary}`}
            onClick={() => { resetApiKeyForm(); setShowApiKeyForm(true); }}
          >
            Create API Key
          </button>
        </div>

        {/* Feedback message */}
        {apiKeysMsg && (
          <div className={apiKeysMsg.type === "success"
            ? "text-sm text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-lg px-4 py-2 mb-4"
            : "text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg px-4 py-2 mb-4"
          }>
            {apiKeysMsg.text}
          </div>
        )}

        {/* Created key modal */}
        {createdApiKey && (
          <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setCreatedApiKey(null)}>
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl max-w-md w-full mx-4 p-6 text-center" onClick={(e) => e.stopPropagation()}>
              <div className="text-3xl mb-2">&#x1f511;</div>
              <div className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-1">API Key Created</div>
              <div className="text-sm text-amber-600 dark:text-amber-400 mb-4">
                Copy this key now. It will not be shown again.
              </div>
              <div className="flex items-center gap-2 bg-gray-50 dark:bg-gray-700 rounded-lg p-3">
                <code className="font-mono text-xs text-gray-900 dark:text-gray-100 break-all flex-1 text-left">{createdApiKey}</code>
                <button
                  className={`${tw.btn} ${tw.btnPrimary}`}
                  onClick={() => void handleCopyApiKey()}
                >
                  {apiKeyCopied ? "Copied!" : "Copy"}
                </button>
              </div>
              <button
                className={tw.btn}
                onClick={() => setCreatedApiKey(null)}
                style={{ marginTop: 16 }}
              >
                Close
              </button>
            </div>
          </div>
        )}

        {/* Inline create form */}
        {showApiKeyForm && (
          <form className="bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700 rounded-xl p-5 mb-4" onSubmit={(e) => void handleCreateApiKey(e)}>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3.5">
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-gray-700 dark:text-gray-300">Name</span>
                <input
                  type="text"
                  className={tw.formInput}
                  value={apiKeyName}
                  onChange={(e) => setApiKeyName(e.target.value)}
                  required
                  placeholder="My integration key"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-gray-700 dark:text-gray-300">Expiration Date (optional)</span>
                <input
                  type="date"
                  className={tw.formInput}
                  value={apiKeyExpires}
                  onChange={(e) => setApiKeyExpires(e.target.value)}
                />
              </label>
            </div>
            <div className="flex flex-col gap-1" style={{ marginTop: 14 }}>
              <span className="text-xs font-medium text-gray-700 dark:text-gray-300">Scopes</span>
              <ScopeSelector
                selectedScopes={apiKeyScopes}
                allPipelinesChecked={apiKeyAllScopes}
                pipelineSlugs={pipelineSlugs}
                onToggleAll={() => { setApiKeyAllScopes((v) => !v); setApiKeyScopes([]); }}
                onToggleSlug={(slug) =>
                  setApiKeyScopes((prev) =>
                    prev.includes(slug) ? prev.filter((s) => s !== slug) : [...prev, slug]
                  )
                }
              />
            </div>
            <div className="flex gap-3 mt-4">
              <button type="submit" className={`${tw.btn} ${tw.btnPrimary}`}>
                Create Key
              </button>
              <button type="button" className={tw.btn} onClick={resetApiKeyForm}>
                Cancel
              </button>
            </div>
          </form>
        )}

        {/* API Keys table */}
        {apiKeysLoading && apiKeys.length === 0 && (
          <div className="text-center py-8 text-gray-500 dark:text-gray-400">Loading API keys...</div>
        )}
        {apiKeysError && (
          <div className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg px-4 py-2 mb-4">{apiKeysError}</div>
        )}
        {!apiKeysLoading && !apiKeysError && apiKeys.length === 0 && (
          <div className="text-center py-8 text-gray-500 dark:text-gray-400">No API keys configured.</div>
        )}
        {apiKeys.length > 0 && (
          <table className={tw.table}>
            <thead>
              <tr>
                <th className={tw.th}>Name</th>
                <th className={tw.th}>Key Prefix</th>
                <th className={tw.th}>Scopes</th>
                <th className={tw.th}>Created</th>
                <th className={tw.th}>Expires</th>
                <th className={tw.th}>Last Used</th>
                <th className={tw.th}>Status</th>
                <th className={tw.th}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {apiKeys.map((k) => (
                <tr key={k.id}>
                  <td className={tw.td}>{k.name}</td>
                  <td className={tw.td}><code className="font-mono text-xs">{k.key_prefix}</code></td>
                  <td className={tw.td}><ScopeBadges scopes={k.scopes} /></td>
                  <td className={tw.td}>{timeAgo(k.created_at)}</td>
                  <td className={tw.td}>{k.expires_at ? new Date(k.expires_at).toLocaleDateString() : "Never"}</td>
                  <td className={tw.td}>{k.last_used_at ? timeAgo(k.last_used_at) : "Never"}</td>
                  <td className={tw.td}>
                    <span className={statusBadgeClasses(k.is_active ? "production" : "deprecated")}>
                      {k.is_active ? "Active" : "Revoked"}
                    </span>
                  </td>
                  <td className={tw.td}>
                    <div className="flex gap-1.5">
                      {k.is_active && (
                        <button
                          className={`${tw.btnSmall} ${tw.btnDanger}`}
                          onClick={() => void handleRevokeApiKey(k.id, k.name)}
                        >
                          Revoke
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ============================================================ */}
      {/* Platform Credentials                                          */}
      {/* ============================================================ */}
      <div className="mb-10">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Platform Credentials</h2>
          <button
            className={`${tw.btn} ${tw.btnPrimary}`}
            onClick={handleAddCredentialClick}
          >
            Add Credential
          </button>
        </div>

        {/* Feedback message */}
        {credentialsMsg && (
          <div className={credentialsMsg.type === "success"
            ? "text-sm text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-lg px-4 py-2 mb-4"
            : "text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg px-4 py-2 mb-4"
          }>
            {credentialsMsg.text}
          </div>
        )}

        {/* Inline form */}
        {showCredentialForm && (
          <form className="bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700 rounded-xl p-5 mb-4" onSubmit={(e) => void handleCredentialSubmit(e)}>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3.5">
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-gray-700 dark:text-gray-300">Name</span>
                <input
                  type="text"
                  className={tw.formInput}
                  value={credName}
                  onChange={(e) => setCredName(e.target.value)}
                  required
                  placeholder="Production GitLab"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-gray-700 dark:text-gray-300">Platform</span>
                <select
                  className={tw.formInput}
                  value={credPlatform}
                  onChange={(e) => setCredPlatform(e.target.value)}
                  disabled={editingCredentialId !== null}
                >
                  <option value="gitlab">gitlab</option>
                  <option value="github">github</option>
                </select>
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-gray-700 dark:text-gray-300">Base URL</span>
                <input
                  type="url"
                  className={tw.formInput}
                  value={credBaseUrl}
                  onChange={(e) => setCredBaseUrl(e.target.value)}
                  required={editingCredentialId === null}
                  disabled={editingCredentialId !== null}
                  placeholder="https://gitlab.com"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-gray-700 dark:text-gray-300">
                  Token{editingCredentialId !== null ? " (leave blank to keep current)" : ""}
                </span>
                <input
                  type="password"
                  className={tw.formInput}
                  value={credToken}
                  onChange={(e) => setCredToken(e.target.value)}
                  required={editingCredentialId === null}
                  placeholder={editingCredentialId !== null ? "unchanged" : "glpat-xxxxxxxxxxxx"}
                  autoComplete="off"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-gray-700 dark:text-gray-300">Expiration Date (optional)</span>
                <input
                  type="date"
                  className={tw.formInput}
                  value={credExpires}
                  onChange={(e) => setCredExpires(e.target.value)}
                />
              </label>
            </div>
            <div className="flex flex-col gap-1" style={{ marginTop: 14 }}>
              <span className="text-xs font-medium text-gray-700 dark:text-gray-300">Scopes</span>
              <ScopeSelector
                selectedScopes={credScopes}
                allPipelinesChecked={credAllScopes}
                pipelineSlugs={pipelineSlugs}
                onToggleAll={() => { setCredAllScopes((v) => !v); setCredScopes([]); }}
                onToggleSlug={(slug) =>
                  setCredScopes((prev) =>
                    prev.includes(slug) ? prev.filter((s) => s !== slug) : [...prev, slug]
                  )
                }
              />
            </div>
            <div className="flex gap-3 mt-4">
              <button type="submit" className={`${tw.btn} ${tw.btnPrimary}`}>
                {editingCredentialId !== null ? "Update Credential" : "Create Credential"}
              </button>
              <button type="button" className={tw.btn} onClick={resetCredentialForm}>
                Cancel
              </button>
            </div>
          </form>
        )}

        {/* Credentials table */}
        {credentialsLoading && credentials.length === 0 && (
          <div className="text-center py-8 text-gray-500 dark:text-gray-400">Loading credentials...</div>
        )}
        {credentialsError && (
          <div className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg px-4 py-2 mb-4">{credentialsError}</div>
        )}
        {!credentialsLoading && !credentialsError && credentials.length === 0 && (
          <div className="text-center py-8 text-gray-500 dark:text-gray-400">No platform credentials configured.</div>
        )}
        {credentials.length > 0 && (
          <table className={tw.table}>
            <thead>
              <tr>
                <th className={tw.th}>Name</th>
                <th className={tw.th}>Platform</th>
                <th className={tw.th}>Base URL</th>
                <th className={tw.th}>Scopes</th>
                <th className={tw.th}>Last Used</th>
                <th className={tw.th}>Expires</th>
                <th className={tw.th}>Status</th>
                <th className={tw.th}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {credentials.map((c) => (
                <tr key={c.id}>
                  <td className={tw.td}>{c.name}</td>
                  <td className={tw.td}>
                    <span className={platformBadgeClasses(c.platform)}>
                      {c.platform}
                    </span>
                  </td>
                  <td className={tw.td}><code className="font-mono text-xs">{c.base_url}</code></td>
                  <td className={tw.td}><ScopeBadges scopes={c.scopes} /></td>
                  <td className={tw.td}>{c.last_used_at ? timeAgo(c.last_used_at) : "Never"}</td>
                  <td className={tw.td}>{c.expires_at ? new Date(c.expires_at).toLocaleDateString() : "Never"}</td>
                  <td className={tw.td}>
                    <span className={statusBadgeClasses(c.is_active ? "production" : "deprecated")}>
                      {c.is_active ? "Active" : "Revoked"}
                    </span>
                  </td>
                  <td className={tw.td}>
                    <div className="flex gap-1.5">
                      {c.is_active && (
                        <>
                          <button
                            className={tw.btnSmall}
                            onClick={() => handleEditCredentialClick(c)}
                          >
                            Edit
                          </button>
                          <button
                            className={`${tw.btnSmall} ${tw.btnTest}`}
                            onClick={() => void handleTestCredential(c.id)}
                            disabled={testingId === c.id}
                          >
                            {testingId === c.id ? "Testing..." : "Test"}
                          </button>
                          <button
                            className={`${tw.btnSmall} ${tw.btnDanger}`}
                            onClick={() => void handleRevokeCredential(c.id, c.name)}
                          >
                            Revoke
                          </button>
                        </>
                      )}
                    </div>
                    {(() => {
                      const tr = testResults[c.id];
                      if (!tr) return null;
                      return (
                        <div className={tr.success ? "text-xs text-emerald-600 dark:text-emerald-400 mt-1" : "text-xs text-red-600 dark:text-red-400 mt-1"}>
                          {tr.success ? "Connected" : `Failed: ${tr.message}`}
                        </div>
                      );
                    })()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export default Admin;
