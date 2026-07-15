import { useEffect, useState, useCallback } from "react";
import Markdown from "../components/Markdown";
import {
  BookOpen,
  Plus,
  Search,
  Edit,
  Trash2,
  Tag,
  FolderOpen,
  X,
  Check,
  ChevronLeft,
  ChevronRight,
  Sparkles,
} from "lucide-react";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface Category {
  id: string;
  name: string;
  description: string;
  sort_order: number;
}

interface Article {
  id: string;
  category_id: string | null;
  category_name: string | null;
  title: string;
  slug: string;
  body: string;
  tags: string[];
  status: string;
  source: string;
  created_at: string;
  updated_at: string;
}

interface ArticlesResponse {
  articles: Article[];
  total: number;
}

interface SearchResult {
  id: string;
  title: string;
  slug: string;
  body: string;
  category_name: string | null;
  status: string;
  tags: string[];
  source: string;
  updated_at: string;
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const PAGE_SIZE = 50;

const STATUS_CLASSES: Record<string, string> = {
  draft: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  published: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  archived: "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300",
};

const CATEGORY_COLORS = [
  "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300",
  "bg-violet-100 text-violet-700 dark:bg-violet-900 dark:text-violet-300",
  "bg-pink-100 text-pink-700 dark:bg-pink-900 dark:text-pink-300",
  "bg-teal-100 text-teal-700 dark:bg-teal-900 dark:text-teal-300",
  "bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300",
  "bg-cyan-100 text-cyan-700 dark:bg-cyan-900 dark:text-cyan-300",
  "bg-rose-100 text-rose-700 dark:bg-rose-900 dark:text-rose-300",
  "bg-lime-100 text-lime-700 dark:bg-lime-900 dark:text-lime-300",
];

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/* renderMarkdown removed — using shared <Markdown> component */

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

function categoryColor(categoryId: string | null | undefined): string {
  if (!categoryId) return "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300";
  let hash = 0;
  for (let i = 0; i < categoryId.length; i++) hash = (hash * 31 + categoryId.charCodeAt(i)) | 0;
  return CATEGORY_COLORS[Math.abs(hash) % CATEGORY_COLORS.length] ?? "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300";
}

function excerpt(body: string, len = 150): string {
  const plain = body.replace(/[#*`\[\]()-]/g, "").replace(/\n/g, " ");
  return plain.length > len ? plain.slice(0, len) + "..." : plain;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

function KnowledgeBase() {
  // Categories
  const [categories, setCategories] = useState<Category[]>([]);
  const [showCategoryManager, setShowCategoryManager] = useState(false);
  const [categoryForm, setCategoryForm] = useState<{
    id?: string;
    name: string;
    description: string;
    sort_order: number;
  } | null>(null);

  // Articles
  const [articles, setArticles] = useState<Article[]>([]);
  const [articlesTotal, setArticlesTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);

  // Filters
  const [categoryFilter, setCategoryFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [tagFilter, setTagFilter] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null);
  const [searching, setSearching] = useState(false);

  // Detail / Form modals
  const [selectedArticle, setSelectedArticle] = useState<Article | null>(null);
  const [formModal, setFormModal] = useState<{
    mode: "create" | "edit";
    id?: string;
    title: string;
    body: string;
    category_id: string;
    tags: string;
    status: string;
    slug: string;
  } | null>(null);
  const [formSaving, setFormSaving] = useState(false);

  // Agent suggested count
  const [agentSuggestedCount, setAgentSuggestedCount] = useState(0);

  /* ---------------------------------------------------------------- */
  /*  Fetch helpers                                                    */
  /* ---------------------------------------------------------------- */

  const fetchCategories = useCallback(async () => {
    try {
      const res = await fetch("/api/v1/kb/categories");
      if (res.ok) setCategories(await res.json());
    } catch {
      /* ignore */
    }
  }, []);

  const fetchArticles = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (categoryFilter) params.set("category", categoryFilter);
      if (statusFilter !== "all") params.set("status", statusFilter);
      if (tagFilter.trim()) params.set("tag", tagFilter.trim());
      params.set("limit", String(PAGE_SIZE));
      params.set("offset", String(page * PAGE_SIZE));

      const res = await fetch(`/api/v1/kb/articles?${params}`);
      if (res.ok) {
        const data: ArticlesResponse = await res.json();
        setArticles(data.articles);
        setArticlesTotal(data.total);
      }
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [categoryFilter, statusFilter, tagFilter, page]);

  const fetchAgentSuggestedCount = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      params.set("status", "draft");
      params.set("limit", "1");
      params.set("offset", "0");
      // We fetch with a minimal limit just to get the total count
      const res = await fetch(`/api/v1/kb/articles?${params}`);
      if (res.ok) {
        const data: ArticlesResponse = await res.json();
        // Count agent_suggested from all drafts - fetch them all
        const allParams = new URLSearchParams();
        allParams.set("status", "draft");
        allParams.set("limit", String(data.total));
        allParams.set("offset", "0");
        const allRes = await fetch(`/api/v1/kb/articles?${allParams}`);
        if (allRes.ok) {
          const allData: ArticlesResponse = await allRes.json();
          const count = allData.articles.filter((a) => a.source === "agent_suggested").length;
          setAgentSuggestedCount(count);
        }
      }
    } catch {
      /* ignore */
    }
  }, []);

  /* ---------------------------------------------------------------- */
  /*  Effects                                                          */
  /* ---------------------------------------------------------------- */

  useEffect(() => {
    void fetchCategories();
    void fetchAgentSuggestedCount();
  }, [fetchCategories, fetchAgentSuggestedCount]);

  useEffect(() => {
    if (searchQuery.trim()) return; // skip list fetch when searching
    void fetchArticles();
  }, [fetchArticles, searchQuery]);

  /* ---------------------------------------------------------------- */
  /*  Search                                                           */
  /* ---------------------------------------------------------------- */

  const doSearch = useCallback(async () => {
    if (!searchQuery.trim()) {
      setSearchResults(null);
      return;
    }
    setSearching(true);
    try {
      const params = new URLSearchParams();
      params.set("q", searchQuery.trim());
      params.set("limit", "50");
      const res = await fetch(`/api/v1/kb/search?${params}`);
      if (res.ok) {
        const data = await res.json();
        setSearchResults(data.results ?? []);
      }
    } catch {
      /* ignore */
    } finally {
      setSearching(false);
    }
  }, [searchQuery]);

  useEffect(() => {
    const timer = setTimeout(() => {
      void doSearch();
    }, 300);
    return () => clearTimeout(timer);
  }, [doSearch]);

  /* ---------------------------------------------------------------- */
  /*  Article CRUD                                                     */
  /* ---------------------------------------------------------------- */

  const openArticleDetail = async (id: string) => {
    try {
      const res = await fetch(`/api/v1/kb/articles/${id}`);
      if (res.ok) setSelectedArticle(await res.json());
    } catch {
      /* ignore */
    }
  };

  const deleteArticle = async (id: string) => {
    if (!confirm("Delete this article?")) return;
    try {
      const res = await fetch(`/api/v1/kb/articles/${id}`, { method: "DELETE" });
      if (res.ok) {
        setSelectedArticle(null);
        void fetchArticles();
        void fetchAgentSuggestedCount();
      }
    } catch {
      /* ignore */
    }
  };

  const openCreateForm = () => {
    setFormModal({
      mode: "create",
      title: "",
      body: "",
      category_id: "",
      tags: "",
      status: "draft",
      slug: "",
    });
  };

  const openEditForm = (article: Article) => {
    setFormModal({
      mode: "edit",
      id: article.id,
      title: article.title,
      body: article.body,
      category_id: article.category_id != null ? String(article.category_id) : "",
      tags: article.tags.join(", "),
      status: article.status,
      slug: article.slug,
    });
    setSelectedArticle(null);
  };

  const submitArticleForm = async () => {
    if (!formModal) return;
    setFormSaving(true);
    try {
      const payload: Record<string, unknown> = {
        title: formModal.title,
        body: formModal.body,
        status: formModal.status,
        slug: formModal.slug || slugify(formModal.title),
        tags: formModal.tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
      };
      if (formModal.category_id) {
        payload.category_id = Number(formModal.category_id);
      } else {
        payload.category_id = null;
      }

      const url =
        formModal.mode === "create"
          ? "/api/v1/kb/articles"
          : `/api/v1/kb/articles/${formModal.id}`;
      const method = formModal.mode === "create" ? "POST" : "PUT";

      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        setFormModal(null);
        void fetchArticles();
        void fetchAgentSuggestedCount();
      }
    } catch {
      /* ignore */
    } finally {
      setFormSaving(false);
    }
  };

  const approveArticle = async (id: string) => {
    try {
      const res = await fetch(`/api/v1/kb/articles/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "published" }),
      });
      if (res.ok) {
        void fetchArticles();
        void fetchAgentSuggestedCount();
      }
    } catch {
      /* ignore */
    }
  };

  const rejectArticle = async (id: string) => {
    try {
      const res = await fetch(`/api/v1/kb/articles/${id}`, { method: "DELETE" });
      if (res.ok) {
        void fetchArticles();
        void fetchAgentSuggestedCount();
      }
    } catch {
      /* ignore */
    }
  };

  /* ---------------------------------------------------------------- */
  /*  Category CRUD                                                    */
  /* ---------------------------------------------------------------- */

  const submitCategoryForm = async () => {
    if (!categoryForm) return;
    try {
      const payload: Record<string, unknown> = {
        name: categoryForm.name,
        description: categoryForm.description || undefined,
        sort_order: categoryForm.sort_order,
      };

      const url = categoryForm.id
        ? `/api/v1/kb/categories/${categoryForm.id}`
        : "/api/v1/kb/categories";
      const method = categoryForm.id ? "PUT" : "POST";

      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        setCategoryForm(null);
        void fetchCategories();
      }
    } catch {
      /* ignore */
    }
  };

  const deleteCategory = async (id: string) => {
    if (!confirm("Delete this category? Articles in this category will become uncategorized."))
      return;
    try {
      const res = await fetch(`/api/v1/kb/categories/${id}`, { method: "DELETE" });
      if (res.ok) {
        void fetchCategories();
        void fetchArticles();
      }
    } catch {
      /* ignore */
    }
  };

  /* ---------------------------------------------------------------- */
  /*  Derived                                                          */
  /* ---------------------------------------------------------------- */

  const totalPages = Math.ceil(articlesTotal / PAGE_SIZE);
  const displayArticles = searchResults !== null ? [] : articles;
  const isSearching = searchQuery.trim().length > 0;

  /* ---------------------------------------------------------------- */
  /*  Render                                                           */
  /* ---------------------------------------------------------------- */

  return (
    <div
      className="-mx-6 lg:-mx-8 -my-6 flex flex-col"
      style={{ height: "calc(100vh - 64px)" }}
    >
      {/* Header */}
      <div className="px-6 lg:px-8 py-4 border-b border-gray-200 dark:border-gray-700 flex-shrink-0">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <BookOpen size={24} className="text-primary-600 dark:text-primary-400" />
            <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">
              Knowledge Base
            </h1>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowCategoryManager(!showCategoryManager)}
              className="px-3 py-2 text-sm font-medium text-gray-600 dark:text-gray-300 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors flex items-center gap-1.5"
            >
              <FolderOpen size={16} />
              Categories
            </button>
            <button
              onClick={openCreateForm}
              className="px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg text-sm font-medium transition-colors flex items-center gap-1.5"
            >
              <Plus size={16} />
              New Article
            </button>
          </div>
        </div>

        {/* Search and filters */}
        <div className="flex gap-3 flex-wrap items-center">
          <div className="relative flex-1 min-w-[200px]">
            <Search
              size={16}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
            />
            <input
              type="text"
              placeholder="Search articles..."
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setPage(0);
              }}
              className="w-full pl-9 pr-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
            />
          </div>

          <select
            value={categoryFilter}
            onChange={(e) => {
              setCategoryFilter(e.target.value);
              setPage(0);
            }}
            className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
          >
            <option value="">All categories</option>
            {categories.map((cat) => (
              <option key={cat.id} value={cat.name}>
                {cat.name}
              </option>
            ))}
          </select>

          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPage(0);
            }}
            className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
          >
            <option value="all">All statuses</option>
            <option value="draft">Draft</option>
            <option value="published">Published</option>
            <option value="archived">Archived</option>
          </select>

          <input
            type="text"
            placeholder="Filter by tag..."
            value={tagFilter}
            onChange={(e) => {
              setTagFilter(e.target.value);
              setPage(0);
            }}
            className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none w-[160px]"
          />
        </div>
      </div>

      {/* Main content area */}
      <div className="flex-1 overflow-y-auto px-6 lg:px-8 py-4">
        {/* Agent suggested banner */}
        {agentSuggestedCount > 0 && (
          <div className="mb-4 bg-purple-50 dark:bg-purple-900/20 border border-purple-200 dark:border-purple-800 rounded-xl p-4 flex items-center gap-3">
            <Sparkles size={20} className="text-purple-600 dark:text-purple-400 flex-shrink-0" />
            <div className="flex-1">
              <span className="text-sm font-medium text-purple-800 dark:text-purple-200">
                {agentSuggestedCount} agent-suggested article{agentSuggestedCount !== 1 ? "s" : ""}{" "}
                awaiting review
              </span>
              <span className="text-xs text-purple-600 dark:text-purple-400 ml-2">
                Draft articles suggested by AI agents that need approval or rejection.
              </span>
            </div>
          </div>
        )}

        {/* Category manager (collapsible) */}
        {showCategoryManager && (
          <div className="mb-4 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                Manage Categories
              </h3>
              <div className="flex items-center gap-2">
                <button
                  onClick={() =>
                    setCategoryForm({ name: "", description: "", sort_order: categories.length })
                  }
                  className="text-xs px-2.5 py-1 bg-primary-600 hover:bg-primary-700 text-white rounded-lg font-medium transition-colors flex items-center gap-1"
                >
                  <Plus size={12} />
                  Add
                </button>
                <button
                  onClick={() => setShowCategoryManager(false)}
                  className="p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
                >
                  <X size={16} />
                </button>
              </div>
            </div>

            {categories.length === 0 && (
              <div className="text-sm text-gray-500 dark:text-gray-400">
                No categories yet. Create one to organize articles.
              </div>
            )}

            {categories.length > 0 && (
              <div className="space-y-2">
                {categories.map((cat) => (
                  <div
                    key={cat.id}
                    className="flex items-center justify-between py-2 px-3 bg-gray-50 dark:bg-gray-700/30 rounded-lg"
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={`inline-block text-xs font-semibold px-2 py-0.5 rounded-full ${categoryColor(cat.id)}`}
                      >
                        {cat.name}
                      </span>
                      {cat.description && (
                        <span className="text-xs text-gray-500 dark:text-gray-400">
                          {cat.description}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() =>
                          setCategoryForm({
                            id: cat.id,
                            name: cat.name,
                            description: cat.description,
                            sort_order: cat.sort_order,
                          })
                        }
                        className="p-1 text-gray-400 hover:text-primary-600 dark:hover:text-primary-400"
                      >
                        <Edit size={14} />
                      </button>
                      <button
                        onClick={() => void deleteCategory(cat.id)}
                        className="p-1 text-gray-400 hover:text-red-600 dark:hover:text-red-400"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Loading state */}
        {loading && !isSearching && articles.length === 0 && (
          <div className="text-center py-12 text-gray-500 dark:text-gray-400">
            Loading articles...
          </div>
        )}

        {/* Search results */}
        {isSearching && (
          <>
            {searching && (
              <div className="text-center py-12 text-gray-500 dark:text-gray-400">
                Searching...
              </div>
            )}
            {!searching && searchResults !== null && searchResults.length === 0 && (
              <div className="text-center py-12 text-gray-500 dark:text-gray-400">
                No articles match your search.
              </div>
            )}
            {!searching && searchResults !== null && searchResults.length > 0 && (
              <div className="grid gap-3">
                {searchResults.map((r) => (
                  <div
                    key={r.id}
                    onClick={() => void openArticleDetail(r.id)}
                    className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 cursor-pointer hover:border-primary-300 dark:hover:border-primary-600 transition-colors"
                  >
                    <div className="flex items-start justify-between gap-3 mb-2">
                      <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                        {r.title}
                      </h3>
                      <div className="flex items-center gap-2 flex-shrink-0">
                        {r.source === "agent_suggested" && (
                          <span className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300">
                            <Sparkles size={10} />
                            Agent
                          </span>
                        )}
                        <span
                          className={`inline-block text-xs font-semibold px-2 py-0.5 rounded-full ${STATUS_CLASSES[r.status] ?? STATUS_CLASSES.draft}`}
                        >
                          {r.status}
                        </span>
                      </div>
                    </div>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
                      {excerpt(r.body)}
                    </p>
                    <div className="flex items-center gap-2 flex-wrap">
                      {r.category_name && (
                        <span className="inline-block text-xs font-semibold px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300">
                          {r.category_name}
                        </span>
                      )}
                      {r.tags.map((tag) => (
                        <span
                          key={tag}
                          className="inline-flex items-center gap-0.5 text-xs px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400"
                        >
                          <Tag size={10} />
                          {tag}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {/* Article cards */}
        {!isSearching && !loading && displayArticles.length === 0 && (
          <div className="text-center py-12 text-gray-500 dark:text-gray-400">
            No articles found. Create one to get started.
          </div>
        )}

        {!isSearching && displayArticles.length > 0 && (
          <div className="grid gap-3">
            {displayArticles.map((article) => (
              <div
                key={article.id}
                onClick={() => void openArticleDetail(article.id)}
                className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 cursor-pointer hover:border-primary-300 dark:hover:border-primary-600 transition-colors"
              >
                <div className="flex items-start justify-between gap-3 mb-2">
                  <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                    {article.title}
                  </h3>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    {article.source === "agent_suggested" && (
                      <span className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300">
                        <Sparkles size={10} />
                        Agent Suggested
                      </span>
                    )}
                    <span
                      className={`inline-block text-xs font-semibold px-2 py-0.5 rounded-full ${STATUS_CLASSES[article.status] ?? STATUS_CLASSES.draft}`}
                    >
                      {article.status}
                    </span>
                  </div>
                </div>

                <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
                  {excerpt(article.body)}
                </p>

                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 flex-wrap">
                    {article.category_name && (
                      <span
                        className={`inline-block text-xs font-semibold px-2 py-0.5 rounded-full ${categoryColor(article.category_id)}`}
                      >
                        {article.category_name}
                      </span>
                    )}
                    {article.tags.map((tag) => (
                      <span
                        key={tag}
                        className="inline-flex items-center gap-0.5 text-xs px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400"
                      >
                        <Tag size={10} />
                        {tag}
                      </span>
                    ))}
                  </div>
                  <div className="flex items-center gap-2">
                    {article.source === "agent_suggested" && article.status === "draft" && (
                      <>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            void approveArticle(article.id);
                          }}
                          className="p-1.5 text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-900/30 rounded-lg transition-colors"
                          title="Approve (publish)"
                        >
                          <Check size={16} />
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            void rejectArticle(article.id);
                          }}
                          className="p-1.5 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/30 rounded-lg transition-colors"
                          title="Reject (delete)"
                        >
                          <Trash2 size={16} />
                        </button>
                      </>
                    )}
                    <span className="text-xs text-gray-400 dark:text-gray-500">
                      {new Date(article.updated_at).toLocaleDateString()}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Pagination */}
        {!isSearching && totalPages > 1 && (
          <div className="flex items-center justify-center gap-4 mt-4 pb-2">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="text-sm font-medium px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center gap-1"
            >
              <ChevronLeft size={14} />
              Previous
            </button>
            <span className="text-sm text-gray-500 dark:text-gray-400">
              Page {page + 1} of {totalPages} ({articlesTotal} articles)
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="text-sm font-medium px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center gap-1"
            >
              Next
              <ChevronRight size={14} />
            </button>
          </div>
        )}
      </div>

      {/* ============================================================ */}
      {/*  Article detail modal                                         */}
      {/* ============================================================ */}
      {selectedArticle && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
          onClick={() => setSelectedArticle(null)}
        >
          <div
            className="bg-white dark:bg-gray-800 rounded-2xl shadow-xl max-w-3xl w-full max-h-[90vh] flex flex-col overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal header */}
            <div className="flex items-center justify-between px-6 py-4 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700 flex-shrink-0">
              <div className="flex items-center gap-2 flex-wrap flex-1 mr-3">
                <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
                  {selectedArticle.title}
                </h2>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <button
                  onClick={() => openEditForm(selectedArticle)}
                  className="p-1.5 text-gray-400 hover:text-primary-600 dark:hover:text-primary-400 rounded-lg"
                  title="Edit"
                >
                  <Edit size={18} />
                </button>
                <button
                  onClick={() => void deleteArticle(selectedArticle.id)}
                  className="p-1.5 text-gray-400 hover:text-red-600 dark:hover:text-red-400 rounded-lg"
                  title="Delete"
                >
                  <Trash2 size={18} />
                </button>
                <button
                  onClick={() => setSelectedArticle(null)}
                  className="p-1.5 text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 rounded-lg"
                >
                  <X size={18} />
                </button>
              </div>
            </div>

            {/* Modal body */}
            <div className="flex-1 overflow-y-auto p-6">
              {/* Meta info */}
              <div className="flex items-center gap-2 flex-wrap mb-4">
                {selectedArticle.category_name && (
                  <span
                    className={`inline-block text-xs font-semibold px-2 py-0.5 rounded-full ${categoryColor(selectedArticle.category_id)}`}
                  >
                    {selectedArticle.category_name}
                  </span>
                )}
                <span
                  className={`inline-block text-xs font-semibold px-2 py-0.5 rounded-full ${STATUS_CLASSES[selectedArticle.status] ?? STATUS_CLASSES.draft}`}
                >
                  {selectedArticle.status}
                </span>
                {selectedArticle.source === "agent_suggested" && (
                  <span className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300">
                    <Sparkles size={10} />
                    Agent Suggested
                  </span>
                )}
                {selectedArticle.tags.map((tag) => (
                  <span
                    key={tag}
                    className="inline-flex items-center gap-0.5 text-xs px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400"
                  >
                    <Tag size={10} />
                    {tag}
                  </span>
                ))}
              </div>

              {/* Timestamps */}
              <div className="flex gap-4 text-xs text-gray-500 dark:text-gray-400 mb-5">
                <span>Created: {new Date(selectedArticle.created_at).toLocaleString()}</span>
                <span>Updated: {new Date(selectedArticle.updated_at).toLocaleString()}</span>
                {selectedArticle.source && (
                  <span>Source: {selectedArticle.source}</span>
                )}
              </div>

              {/* Rendered body */}
              <div className="prose prose-sm dark:prose-invert max-w-none text-sm text-gray-700 dark:text-gray-300 leading-relaxed">
                <Markdown content={selectedArticle.body} />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ============================================================ */}
      {/*  Create / Edit form modal                                     */}
      {/* ============================================================ */}
      {formModal && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
          onClick={() => setFormModal(null)}
        >
          <div
            className="bg-white dark:bg-gray-800 rounded-2xl shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Form header */}
            <div className="flex items-center justify-between px-6 py-4 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700">
              <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
                {formModal.mode === "create" ? "New Article" : "Edit Article"}
              </h2>
              <button
                onClick={() => setFormModal(null)}
                className="p-1.5 text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 rounded-lg"
              >
                <X size={18} />
              </button>
            </div>

            {/* Form body */}
            <div className="p-6 space-y-4">
              {/* Title */}
              <div>
                <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
                  Title
                </label>
                <input
                  type="text"
                  value={formModal.title}
                  onChange={(e) => {
                    const title = e.target.value;
                    setFormModal((f) =>
                      f
                        ? {
                            ...f,
                            title,
                            slug:
                              f.mode === "create" || f.slug === slugify(f.title)
                                ? slugify(title)
                                : f.slug,
                          }
                        : f,
                    );
                  }}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
                  placeholder="Article title"
                />
              </div>

              {/* Slug */}
              <div>
                <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
                  Slug
                </label>
                <input
                  type="text"
                  value={formModal.slug}
                  onChange={(e) =>
                    setFormModal((f) => (f ? { ...f, slug: e.target.value } : f))
                  }
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none font-mono"
                  placeholder="auto-generated-from-title"
                />
              </div>

              {/* Category + Status row */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
                    Category
                  </label>
                  <select
                    value={formModal.category_id}
                    onChange={(e) =>
                      setFormModal((f) => (f ? { ...f, category_id: e.target.value } : f))
                    }
                    className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
                  >
                    <option value="">No category</option>
                    {categories.map((cat) => (
                      <option key={cat.id} value={cat.id}>
                        {cat.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
                    Status
                  </label>
                  <select
                    value={formModal.status}
                    onChange={(e) =>
                      setFormModal((f) => (f ? { ...f, status: e.target.value } : f))
                    }
                    className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
                  >
                    <option value="draft">Draft</option>
                    <option value="published">Published</option>
                    <option value="archived">Archived</option>
                  </select>
                </div>
              </div>

              {/* Tags */}
              <div>
                <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
                  Tags (comma-separated)
                </label>
                <input
                  type="text"
                  value={formModal.tags}
                  onChange={(e) =>
                    setFormModal((f) => (f ? { ...f, tags: e.target.value } : f))
                  }
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
                  placeholder="e.g. rhoai, operator, troubleshooting"
                />
              </div>

              {/* Body */}
              <div>
                <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
                  Body (Markdown)
                </label>
                <textarea
                  value={formModal.body}
                  onChange={(e) =>
                    setFormModal((f) => (f ? { ...f, body: e.target.value } : f))
                  }
                  rows={16}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none font-mono resize-y"
                  placeholder="Write article content in Markdown..."
                />
              </div>

              {/* Actions */}
              <div className="flex items-center justify-end gap-3 pt-2">
                <button
                  onClick={() => setFormModal(null)}
                  className="px-4 py-2 text-sm font-medium text-gray-600 dark:text-gray-300 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={() => void submitArticleForm()}
                  disabled={formSaving || !formModal.title.trim()}
                  className="px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5"
                >
                  {formSaving ? (
                    "Saving..."
                  ) : formModal.mode === "create" ? (
                    <>
                      <Plus size={14} />
                      Create Article
                    </>
                  ) : (
                    <>
                      <Check size={14} />
                      Save Changes
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ============================================================ */}
      {/*  Category form modal                                          */}
      {/* ============================================================ */}
      {categoryForm && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
          onClick={() => setCategoryForm(null)}
        >
          <div
            className="bg-white dark:bg-gray-800 rounded-2xl shadow-xl max-w-md w-full"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Category form header */}
            <div className="flex items-center justify-between px-6 py-4 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700 rounded-t-2xl">
              <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
                {categoryForm.id ? "Edit Category" : "New Category"}
              </h2>
              <button
                onClick={() => setCategoryForm(null)}
                className="p-1.5 text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 rounded-lg"
              >
                <X size={18} />
              </button>
            </div>

            {/* Category form body */}
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
                  Name
                </label>
                <input
                  type="text"
                  value={categoryForm.name}
                  onChange={(e) =>
                    setCategoryForm((f) => (f ? { ...f, name: e.target.value } : f))
                  }
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
                  placeholder="Category name"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
                  Description
                </label>
                <input
                  type="text"
                  value={categoryForm.description}
                  onChange={(e) =>
                    setCategoryForm((f) => (f ? { ...f, description: e.target.value } : f))
                  }
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
                  placeholder="Optional description"
                />
              </div>

              <div className="flex items-center justify-end gap-3 pt-2">
                <button
                  onClick={() => setCategoryForm(null)}
                  className="px-4 py-2 text-sm font-medium text-gray-600 dark:text-gray-300 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={() => void submitCategoryForm()}
                  disabled={!categoryForm.name.trim()}
                  className="px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {categoryForm.id ? "Save" : "Create"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default KnowledgeBase;
