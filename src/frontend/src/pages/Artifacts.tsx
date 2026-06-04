import { useEffect, useState, useCallback } from "react";
import { FileText, FolderOpen, ChevronRight, ChevronDown, X } from "lucide-react";

interface Pipeline {
  id: number;
  slug: string;
  name: string;
  group: string | null;
}

interface ArtifactFile {
  id: number;
  source: string;
  source_ref: string | null;
  file_path: string;
  file_size: number | null;
  mime_type: string | null;
}

function Artifacts() {
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactFile[]>([]);
  const [artifactsLoading, setArtifactsLoading] = useState(false);
  const [modalArtifact, setModalArtifact] = useState<ArtifactFile | null>(null);
  const [modalContent, setModalContent] = useState<string | null>(null);
  const [contentLoading, setContentLoading] = useState(false);
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");

  const fetchPipelines = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/pipelines");
      if (res.ok) {
        const data = await res.json();
        setPipelines(data.pipelines ?? []);
      }
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchPipelines();
  }, [fetchPipelines]);

  const fetchArtifacts = useCallback(async (slug: string) => {
    setArtifactsLoading(true);
    setExpandedDirs(new Set());
    try {
      const res = await fetch(`/api/pipelines/${encodeURIComponent(slug)}/artifacts/latest`);
      if (res.ok) {
        const data = await res.json();
        setArtifacts(data.artifacts ?? []);
      } else {
        setArtifacts([]);
      }
    } catch {
      setArtifacts([]);
    } finally {
      setArtifactsLoading(false);
    }
  }, []);

  const selectPipeline = (slug: string) => {
    setSelectedSlug(slug);
    void fetchArtifacts(slug);
  };

  const openFile = async (artifact: ArtifactFile) => {
    setModalArtifact(artifact);
    setModalContent(null);

    const mime = artifact.mime_type ?? "";
    if (mime.startsWith("text/") || mime === "application/json" || mime === "application/xml") {
      setContentLoading(true);
      try {
        const res = await fetch(`/api/artifacts/${artifact.id}/content`);
        if (res.ok) {
          setModalContent(await res.text());
        }
      } catch {
        /* ignore */
      } finally {
        setContentLoading(false);
      }
    }
  };

  const closeModal = () => {
    setModalArtifact(null);
    setModalContent(null);
  };

  const toggleDir = (dir: string) => {
    setExpandedDirs((prev) => {
      const next = new Set(prev);
      if (next.has(dir)) next.delete(dir);
      else next.add(dir);
      return next;
    });
  };

  const filteredArtifacts = search
    ? artifacts.filter((a) => a.file_path.toLowerCase().includes(search.toLowerCase()))
    : artifacts;

  const buildTree = (files: ArtifactFile[]) => {
    const bySource: Record<string, ArtifactFile[]> = {};
    for (const a of files) {
      const key = a.source === "data_repo" ? "Data Repository" : "CI Job Artifacts";
      if (!bySource[key]) bySource[key] = [];
      bySource[key].push(a);
    }

    const result: Record<string, { dirs: Map<string, ArtifactFile[]>; rootFiles: ArtifactFile[] }> = {};
    for (const [source, srcFiles] of Object.entries(bySource)) {
      const dirs = new Map<string, ArtifactFile[]>();
      const rootFiles: ArtifactFile[] = [];
      for (const f of srcFiles) {
        const slashIdx = f.file_path.indexOf("/");
        if (slashIdx === -1) {
          rootFiles.push(f);
        } else {
          const dir = f.file_path.substring(0, slashIdx);
          if (!dirs.has(dir)) dirs.set(dir, []);
          dirs.get(dir)!.push(f);
        }
      }
      result[source] = { dirs, rootFiles };
    }
    return result;
  };

  return (
    <div className="-mx-6 lg:-mx-8 -my-6 flex flex-col" style={{ height: "calc(100vh - 64px)" }}>
      {/* Header */}
      <div className="px-6 lg:px-8 py-4 border-b border-gray-200 dark:border-gray-700 flex-shrink-0">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100 mb-1">Artifacts</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Browse CI job artifacts and data repository files across all pipelines.
        </p>
      </div>

      {loading && (
        <div className="text-center py-12 text-gray-500 dark:text-gray-400 flex-1">Loading pipelines...</div>
      )}

      {!loading && (
        <div className="flex flex-1 min-h-0">
          {/* Pipeline list */}
          <div className="w-56 flex-shrink-0 border-r border-gray-200 dark:border-gray-700 overflow-y-auto bg-white dark:bg-gray-800">
            <div className="px-4 py-3 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700 sticky top-0">
              <span className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">Pipelines</span>
            </div>
            {pipelines.map((p) => (
              <button
                key={p.slug}
                onClick={() => selectPipeline(p.slug)}
                className={`w-full text-left px-4 py-2.5 text-sm border-b border-gray-100 dark:border-gray-800 transition-colors ${
                  selectedSlug === p.slug
                    ? "bg-primary-50 dark:bg-primary-900/20 text-primary-700 dark:text-primary-300 font-medium"
                    : "text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700/30"
                }`}
              >
                <div className="truncate">{p.name}</div>
                {p.group && <div className="text-xs text-gray-400 dark:text-gray-500">{p.group}</div>}
              </button>
            ))}
          </div>

          {/* File tree */}
          <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
            {!selectedSlug && (
              <div className="flex items-center justify-center flex-1 text-sm text-gray-400 dark:text-gray-500">
                Select a pipeline to browse its artifacts
              </div>
            )}

            {selectedSlug && artifactsLoading && (
              <div className="flex items-center justify-center flex-1 text-sm text-gray-500 dark:text-gray-400">Loading artifacts...</div>
            )}

            {selectedSlug && !artifactsLoading && artifacts.length === 0 && (
              <div className="flex items-center justify-center flex-1 text-sm text-gray-500 dark:text-gray-400">
                No artifacts collected for this pipeline yet.
              </div>
            )}

            {selectedSlug && !artifactsLoading && artifacts.length > 0 && (() => {
              const tree = buildTree(filteredArtifacts);

              return (
                <>
                  {/* Search bar */}
                  <div className="px-4 py-2 border-b border-gray-200 dark:border-gray-700 flex-shrink-0">
                    <input
                      type="text"
                      placeholder="Search files..."
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                      className="text-sm px-3 py-1.5 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 outline-none focus:border-primary-400 w-full"
                    />
                  </div>

                  {/* Scrollable file list */}
                  <div className="flex-1 overflow-y-auto">
                    {Object.entries(tree).map(([source, { dirs, rootFiles }]) => (
                      <div key={source}>
                        <div className="px-4 py-2 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700 sticky top-0 z-10">
                          <span className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">{source}</span>
                          <span className="ml-2 text-xs text-gray-400 dark:text-gray-500">
                            {(dirs.size > 0 ? [...dirs.values()].reduce((s, f) => s + f.length, 0) : 0) + rootFiles.length} files
                          </span>
                        </div>
                        {[...dirs.entries()].map(([dir, dirFiles]) => (
                          <div key={dir}>
                            <button
                              onClick={() => toggleDir(`${source}/${dir}`)}
                              className="w-full flex items-center gap-2 px-4 py-1.5 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700/30 border-b border-gray-100 dark:border-gray-800"
                            >
                              {expandedDirs.has(`${source}/${dir}`) ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                              <FolderOpen size={14} className="text-amber-500" />
                              <span className="truncate">{dir}/</span>
                              <span className="text-xs text-gray-400 ml-auto flex-shrink-0">{dirFiles.length}</span>
                            </button>
                            {expandedDirs.has(`${source}/${dir}`) && dirFiles.map((f) => (
                              <button
                                key={f.id}
                                onClick={() => void openFile(f)}
                                className="w-full flex items-center gap-2 pl-10 pr-4 py-1.5 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700/30 border-b border-gray-100 dark:border-gray-800"
                              >
                                <FileText size={14} className="flex-shrink-0" />
                                <span className="truncate">{f.file_path.substring(f.file_path.indexOf("/") + 1)}</span>
                                {f.file_size != null && <span className="text-xs text-gray-400 ml-auto flex-shrink-0">{(f.file_size / 1024).toFixed(1)}k</span>}
                              </button>
                            ))}
                          </div>
                        ))}
                        {rootFiles.map((f) => (
                          <button
                            key={f.id}
                            onClick={() => void openFile(f)}
                            className="w-full flex items-center gap-2 px-4 py-1.5 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700/30 border-b border-gray-100 dark:border-gray-800"
                          >
                            <FileText size={14} className="flex-shrink-0" />
                            <span className="truncate">{f.file_path}</span>
                            {f.file_size != null && <span className="text-xs text-gray-400 ml-auto flex-shrink-0">{(f.file_size / 1024).toFixed(1)}k</span>}
                          </button>
                        ))}
                      </div>
                    ))}
                  </div>
                </>
              );
            })()}
          </div>
        </div>
      )}

      {/* Content viewer modal */}
      {modalArtifact && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-6"
          onClick={closeModal}
        >
          <div
            className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-full max-w-4xl max-h-[85vh] flex flex-col overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal header */}
            <div className="flex items-center justify-between px-5 py-3 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700 flex-shrink-0">
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold text-gray-900 dark:text-gray-100 truncate">{modalArtifact.file_path}</div>
                <div className="flex gap-3 text-xs text-gray-400 dark:text-gray-500 mt-0.5">
                  {modalArtifact.mime_type && <span>{modalArtifact.mime_type}</span>}
                  {modalArtifact.file_size != null && <span>{(modalArtifact.file_size / 1024).toFixed(1)} KB</span>}
                  <span className="inline-block px-1.5 py-0 rounded bg-gray-200 dark:bg-gray-600 text-gray-600 dark:text-gray-300">
                    {modalArtifact.source === "data_repo" ? "data repo" : "ci job"}
                  </span>
                </div>
              </div>
              <button
                onClick={closeModal}
                className="p-1.5 text-gray-400 dark:text-gray-500 hover:text-gray-900 dark:hover:text-gray-100 hover:bg-gray-200 dark:hover:bg-gray-600 rounded-lg transition-colors flex-shrink-0 ml-3"
              >
                <X size={18} />
              </button>
            </div>

            {/* Modal body */}
            <div className="flex-1 overflow-auto p-5">
              {contentLoading && <div className="text-sm text-gray-400">Loading...</div>}
              {!contentLoading && modalContent === null && (
                <div className="text-sm text-gray-400">Binary file — content preview not available</div>
              )}
              {!contentLoading && modalContent !== null && (
                <pre className="text-xs text-gray-800 dark:text-gray-200 font-mono whitespace-pre-wrap break-all leading-relaxed">{modalContent}</pre>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default Artifacts;
