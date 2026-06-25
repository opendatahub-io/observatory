import { useEffect, useState, useCallback } from "react";
import { Plus, Pencil, Trash2, Database, X, Check } from "lucide-react";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface DataSource {
  id: string;
  name: string;
  source_type: string;
  endpoint: string | null;
  description: string | null;
  config: Record<string, unknown>;
  status: string;
  last_health_check: string | null;
  last_health_status: string | null;
  created_at: string;
  updated_at: string;
}

interface FormData {
  name: string;
  source_type: string;
  endpoint: string;
  description: string;
  config: string;
  status: string;
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const SOURCE_TYPES = [
  { value: "mlflow", label: "MLflow" },
  { value: "kubernetes", label: "Kubernetes" },
  { value: "jira", label: "Jira" },
  { value: "artifact_storage", label: "Artifact Storage" },
  { value: "observatory_api", label: "Observatory API" },
  { value: "custom", label: "Custom" },
];

const EMPTY_FORM: FormData = {
  name: "",
  source_type: "mlflow",
  endpoint: "",
  description: "",
  config: "{}",
  status: "active",
};

/* ------------------------------------------------------------------ */
/*  Tailwind class helpers                                             */
/* ------------------------------------------------------------------ */

const tw = {
  btn: "text-sm font-medium px-4 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all cursor-pointer",
  btnPrimary:
    "bg-primary-600 text-white border-primary-600 hover:bg-primary-700",
  btnDanger: "bg-red-600 text-white border-red-600 hover:bg-red-700",
  btnSmall:
    "text-xs font-medium px-2.5 py-1 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer transition-all",
  table:
    "w-full text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden",
  th: "text-left px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700",
  td: "px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-gray-900 dark:text-gray-100",
  formInput:
    "text-sm px-3 py-2 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 disabled:bg-gray-100 dark:disabled:bg-gray-800 disabled:text-gray-400",
};

function typeBadgeClasses(sourceType: string): string {
  const base = "inline-block text-xs font-semibold px-2.5 py-0.5 rounded-full";
  switch (sourceType) {
    case "mlflow":
      return `${base} bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300`;
    case "kubernetes":
      return `${base} bg-indigo-100 text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-300`;
    case "jira":
      return `${base} bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300`;
    case "artifact_storage":
      return `${base} bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300`;
    case "observatory_api":
      return `${base} bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300`;
    default:
      return `${base} bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300`;
  }
}

function statusBadgeClasses(status: string): string {
  const base = "inline-block text-xs font-semibold px-2.5 py-0.5 rounded-full";
  if (status === "active") {
    return `${base} bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300`;
  }
  return `${base} bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300`;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

function IntelligenceSettings() {
  const [sources, setSources] = useState<DataSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState<{
    text: string;
    type: "success" | "error";
  } | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [formData, setFormData] = useState<FormData>(EMPTY_FORM);
  const [configError, setConfigError] = useState<string | null>(null);

  const flash = (text: string, type: "success" | "error" = "success") => {
    setMsg({ text, type });
    setTimeout(() => setMsg(null), 4000);
  };

  const fetchSources = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/v1/data-sources");
      if (res.ok) setSources(await res.json());
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchSources();
  }, [fetchSources]);

  const openCreateForm = () => {
    setEditingId(null);
    setFormData(EMPTY_FORM);
    setConfigError(null);
    setShowForm(true);
  };

  const openEditForm = (src: DataSource) => {
    setEditingId(src.id);
    setFormData({
      name: src.name,
      source_type: src.source_type,
      endpoint: src.endpoint ?? "",
      description: src.description ?? "",
      config: JSON.stringify(src.config, null, 2),
      status: src.status,
    });
    setConfigError(null);
    setShowForm(true);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    let parsedConfig: Record<string, unknown> = {};
    if (formData.config.trim()) {
      try {
        parsedConfig = JSON.parse(formData.config);
      } catch {
        setConfigError("Invalid JSON");
        return;
      }
    }
    setConfigError(null);

    const payload = {
      name: formData.name,
      source_type: formData.source_type,
      endpoint: formData.endpoint || null,
      description: formData.description || null,
      config: parsedConfig,
      status: formData.status,
    };

    try {
      const url = editingId
        ? `/api/v1/data-sources/${editingId}`
        : "/api/v1/data-sources";
      const method = editingId ? "PUT" : "POST";
      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        flash(editingId ? "Data source updated" : "Data source created");
        setShowForm(false);
        setEditingId(null);
        setFormData(EMPTY_FORM);
        void fetchSources();
      } else {
        const err = await res.json().catch(() => ({ detail: "Request failed" }));
        flash(err.detail ?? "Request failed", "error");
      }
    } catch {
      flash("Network error", "error");
    }
  };

  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`Delete data source "${name}"?`)) return;
    try {
      const res = await fetch(`/api/v1/data-sources/${id}`, {
        method: "DELETE",
      });
      if (res.ok || res.status === 204) {
        flash("Data source deleted");
        void fetchSources();
      } else {
        flash("Delete failed", "error");
      }
    } catch {
      flash("Network error", "error");
    }
  };

  const updateField = (field: keyof FormData, value: string) =>
    setFormData((prev) => ({ ...prev, [field]: value }));

  /* ================================================================ */
  /*  Render                                                           */
  /* ================================================================ */

  return (
    <div className="space-y-6">
      {/* Feedback banner */}
      {msg && (
        <div
          className={`p-3 rounded-lg text-sm font-medium ${
            msg.type === "success"
              ? "bg-emerald-50 text-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-300"
              : "bg-red-50 text-red-800 dark:bg-red-900/20 dark:text-red-300"
          }`}
        >
          {msg.text}
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            Data Sources
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
            External systems the chat agent knows about (MLflow, Kubernetes,
            Jira, etc.)
          </p>
        </div>
        {!showForm && (
          <button
            className={`${tw.btn} ${tw.btnPrimary} flex items-center gap-1.5`}
            onClick={openCreateForm}
          >
            <Plus className="w-4 h-4" />
            Add Source
          </button>
        )}
      </div>

      {/* Create / Edit form */}
      {showForm && (
        <form
          onSubmit={(e) => void handleSubmit(e)}
          className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-5 space-y-4"
        >
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
              {editingId ? "Edit Data Source" : "New Data Source"}
            </h3>
            <button
              type="button"
              className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400"
              onClick={() => {
                setShowForm(false);
                setEditingId(null);
              }}
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Name */}
            <div>
              <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
                Name
              </label>
              <input
                className={`${tw.formInput} w-full`}
                placeholder="e.g. MLflow Tracking Server"
                value={formData.name}
                onChange={(e) => updateField("name", e.target.value)}
                required
              />
            </div>

            {/* Type */}
            <div>
              <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
                Type
              </label>
              <select
                className={`${tw.formInput} w-full`}
                value={formData.source_type}
                onChange={(e) => updateField("source_type", e.target.value)}
              >
                {SOURCE_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Endpoint */}
            <div>
              <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
                Endpoint / URL
              </label>
              <input
                className={`${tw.formInput} w-full`}
                placeholder="e.g. http://mlflow.ai-pipeline.svc.cluster.local:5000"
                value={formData.endpoint}
                onChange={(e) => updateField("endpoint", e.target.value)}
              />
            </div>

            {/* Status */}
            <div>
              <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
                Status
              </label>
              <select
                className={`${tw.formInput} w-full`}
                value={formData.status}
                onChange={(e) => updateField("status", e.target.value)}
              >
                <option value="active">Active</option>
                <option value="inactive">Inactive</option>
              </select>
            </div>
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
              Description
            </label>
            <textarea
              className={`${tw.formInput} w-full`}
              rows={2}
              placeholder="What does this data source provide? The chat agent sees this."
              value={formData.description}
              onChange={(e) => updateField("description", e.target.value)}
            />
          </div>

          {/* Config JSON */}
          <div>
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
              Config (JSON)
            </label>
            <textarea
              className={`${tw.formInput} w-full font-mono text-xs`}
              rows={3}
              placeholder='{"namespace": "ai-pipeline"}'
              value={formData.config}
              onChange={(e) => {
                updateField("config", e.target.value);
                setConfigError(null);
              }}
            />
            {configError && (
              <p className="text-xs text-red-500 mt-1">{configError}</p>
            )}
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2 pt-1">
            <button
              type="submit"
              className={`${tw.btn} ${tw.btnPrimary} flex items-center gap-1.5`}
            >
              <Check className="w-4 h-4" />
              {editingId ? "Update" : "Create"}
            </button>
            <button
              type="button"
              className={tw.btn}
              onClick={() => {
                setShowForm(false);
                setEditingId(null);
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* Table */}
      {loading ? (
        <div className="text-center py-12 text-sm text-gray-400">
          Loading...
        </div>
      ) : sources.length === 0 ? (
        <div className="text-center py-12 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl">
          <Database className="w-10 h-10 mx-auto text-gray-300 dark:text-gray-600 mb-3" />
          <p className="text-sm text-gray-500 dark:text-gray-400">
            No data sources configured
          </p>
          <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
            Add external systems so the chat agent knows about them
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className={tw.table}>
            <thead>
              <tr>
                <th className={tw.th}>Name</th>
                <th className={tw.th}>Type</th>
                <th className={tw.th}>Endpoint</th>
                <th className={tw.th}>Description</th>
                <th className={tw.th}>Status</th>
                <th className={tw.th}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sources.map((src) => (
                <tr key={src.id}>
                  <td className={`${tw.td} font-medium`}>{src.name}</td>
                  <td className={tw.td}>
                    <span className={typeBadgeClasses(src.source_type)}>
                      {SOURCE_TYPES.find((t) => t.value === src.source_type)
                        ?.label ?? src.source_type}
                    </span>
                  </td>
                  <td className={tw.td}>
                    {src.endpoint ? (
                      <code className="text-xs bg-gray-100 dark:bg-gray-900 px-1.5 py-0.5 rounded">
                        {src.endpoint}
                      </code>
                    ) : (
                      <span className="text-gray-400">—</span>
                    )}
                  </td>
                  <td className={`${tw.td} max-w-xs`}>
                    <span className="text-sm text-gray-600 dark:text-gray-400 line-clamp-2">
                      {src.description ?? "—"}
                    </span>
                  </td>
                  <td className={tw.td}>
                    <span className={statusBadgeClasses(src.status)}>
                      {src.status}
                    </span>
                  </td>
                  <td className={tw.td}>
                    <div className="flex items-center gap-1">
                      <button
                        className={tw.btnSmall}
                        title="Edit"
                        onClick={() => openEditForm(src)}
                      >
                        <Pencil className="w-3.5 h-3.5" />
                      </button>
                      <button
                        className={`${tw.btnSmall} hover:!bg-red-50 hover:!text-red-600 dark:hover:!bg-red-900/20 dark:hover:!text-red-400`}
                        title="Delete"
                        onClick={() => void handleDelete(src.id, src.name)}
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default IntelligenceSettings;
