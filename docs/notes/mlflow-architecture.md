# MLflow Architectural Analysis

**Version**: 3.13.1.dev0 | **License**: Apache 2.0 | **Python**: 3.10+ | **Downloads**: 60M+/month

MLflow is the largest open-source AI engineering platform, covering the full lifecycle from experiment tracking through model deployment, with deep recent investment in LLM/agent observability.

---

## 1. High-Level Architecture

The codebase is organized into **10 major subsystems**, distributed as **3 separate packages** (core, skinny, tracing), with a **TypeScript SDK** for JS/TS integrations.

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLI (mlflow cli)                        │
├─────────┬──────────┬──────────┬──────────┬──────────┬──────────┤
│Tracking │  Models  │ Registry │ Tracing  │  GenAI   │ Gateway  │
│         │          │          │(OTel)    │(Prompts, │(AI Proxy)│
│         │          │          │          │ Eval)    │          │
├─────────┴──────────┴──────────┴──────────┴──────────┴──────────┤
│                    Store Abstraction Layer                      │
│         (File, SQLAlchemy, REST, Databricks, Cloud)            │
├─────────────────────────────────────────────────────────────────┤
│              Server (Flask + FastAPI + React UI)                │
├─────────────────────────────────────────────────────────────────┤
│   Artifact Stores: Local | S3 | Azure Blob | GCS | SFTP | DBFS│
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Core Subsystems

### A. Tracking (`mlflow/tracking/`)

The foundational subsystem for experiment management.

- **Fluent API** (`fluent.py`) -- high-level `mlflow.start_run()`, `log_param()`, `log_metric()`
- **MlflowClient** (`client.py`) -- lower-level CRUD for experiments, runs, metrics, params, tags
- **Workspace support** -- multi-tenant isolation (Databricks)
- **Async logging** (`utils/async_logging/`) -- batched, non-blocking metric/artifact writes

### B. Models (`mlflow/models/`)

Model packaging, versioning, and signature inference.

- **Model class** (`model.py`) -- metadata, info, MLmodel YAML
- **Signature inference** (`signature.py`) -- automatic input/output schema detection
- **Flavor backend** (`flavor_backend.py`) -- abstract base for all ML framework integrations
- **Each flavor provides**: `save_model()`, `log_model()`, `load_model()`, `_load_pyfunc()`, `autolog()`

### C. Model Registry (`store/model_registry/`)

Collaborative model lifecycle management with versioning and stage transitions (Staging, Production, Archived).

### D. Store Abstraction (`mlflow/store/`)

Pluggable backends for every data type:

| Store Type | Backends |
|---|---|
| **Tracking** | FileStore (local), SQLAlchemy (SQLite/Postgres/MySQL), REST (remote server), Databricks |
| **Model Registry** | FileStore, SQLAlchemy, REST, Databricks Unity Catalog |
| **Artifacts** | Local FS, S3, Azure Blob, GCS, SFTP, HTTP, Databricks DBFS |
| **Workspace** | SQLAlchemy, REST |

### E. Tracing (`mlflow/tracing/`)

Production-grade LLM observability, OpenTelemetry-native.

- Span creation with parent/child relationships
- W3C Trace Context distributed propagation
- Request/response payload capture
- Trace assessment and feedback APIs
- Sampling strategies
- Archival and retention policies
- Databricks SQL warehouse monitoring integration

### F. GenAI (`mlflow/genai/`)

High-level APIs for LLM/agent workflows:

- **Prompt management** -- versioning, testing, deployment, optimization
- **Evaluation** -- 50+ built-in metrics, LLM judges, RAG evaluation
- **Scorers** -- custom and scheduled scoring
- **Labeling** -- data labeling and review apps
- **Agent testing** -- automated agent testing utilities
- **Simulators** -- conversation simulation

### G. AI Gateway (`mlflow/gateway/`)

Unified API proxy for LLM providers:

- OpenAI-compatible interface across all providers
- Rate limiting, fallback, cost control
- Credential management
- Traffic splitting / A/B testing
- Provider implementations: OpenAI, Azure OpenAI, Anthropic, Bedrock, Gemini, Mistral, Groq, LiteLLM, Ollama

### H. Projects (`mlflow/projects/`)

Reproducible ML project execution:

- MLproject YAML spec parsing
- Multi-backend: local process, Docker, Kubernetes, Databricks
- Parameter substitution, environment management

### I. Deployments (`mlflow/deployments/`)

Extensible model deployment via entry-point plugins:

- Built-in: Databricks, MLflow server, OpenAI
- Plugin interface for custom deployment targets (SageMaker, Azure ML, etc.)

### J. Server (`mlflow/server/`)

Full HTTP server with dual framework support:

- **Flask** -- legacy REST API
- **FastAPI** -- newer ASGI-based API with security middleware
- **React UI** (`server/js/`) -- experiment browser, model registry, trace viewer
- **GraphQL API** (`server/graphql/`)
- **Auth** (`server/auth/`) -- OIDC, basic auth
- **Prometheus metrics** -- `prometheus_exporter.py`

---

## 3. Model Flavors (40+ Integrations)

### Classical ML

`sklearn`, `xgboost`, `lightgbm`, `catboost`, `h2o`, `statsmodels`, `spacy`, `prophet`, `pmdarima`

### Deep Learning

`pytorch` (+ Lightning), `tensorflow`, `keras`, `onnx`, `paddle`, `diffusers`

### LLM Providers

`openai`, `anthropic`, `bedrock`, `gemini`, `mistral`, `groq`, `litellm`

### Agent Frameworks

`langchain`, `llama_index`, `autogen`, `crewai`, `ag2`, `pydantic_ai`, `smolagents`, `strands`, `dspy`, `agno`, `haystack`, `semantic_kernel`

### Other

`transformers`, `sentence_transformers`, `shap`, `pyspark`, `johnsnowlabs`, `rfunc` (R)

---

## 4. Distribution Packages

| Package | Purpose | Install |
|---|---|---|
| **mlflow** | Full platform (server, UI, all features) | `pip install mlflow` |
| **mlflow-skinny** | Minimal client (tracking, logging only, no server/UI) | `pip install mlflow-skinny` |
| **mlflow-tracing** | Standalone LLM tracing SDK | `pip install mlflow-tracing` |
| **TypeScript SDK** | JS/TS tracing with 10 provider integrations | `libs/typescript/` monorepo |

### Optional Extras

| Extra | Purpose | Key Dependencies |
|---|---|---|
| `extras` | Cloud storage and monitoring | pyarrow, boto3, azure-storage-blob, google-cloud-storage, kubernetes, prometheus |
| `db` | Database backends | PyMySQL, psycopg2-binary, pymssql |
| `databricks` | Databricks integration | databricks-agents, azure-storage-file-datalake, boto3, google-cloud-storage |
| `gateway` / `genai` | AI Gateway | fastapi, uvicorn, slowapi, tiktoken, boto3, watchfiles |
| `mcp` | Model Context Protocol | fastmcp, click |
| `azure` | Azure storage | azure-storage-blob, azure-identity |
| `kubernetes` | Kubernetes support | kubernetes |
| `langchain` | LangChain integration | langchain (v0.3.26-1.3.0) |
| `auth` | Authentication | Flask-WTF |
| `sqlserver` | SQL Server support | mlflow-dbstore |
| `aliyun-oss` | Alibaba OSS | aliyunstoreplugin |
| `jfrog` | JFrog Artifactory | mlflow-jfrog-plugin |

---

## 5. Deployment Modes

### Local Development

`mlflow server` with SQLite + local filesystem artifacts.

### Docker

Three image variants:

- `mlflow:VERSION` -- lightweight core only (no extras)
- `mlflow:VERSION-full` -- all extras bundled (v3.9.0+)
- `mlflow:VERSION-full.dev` -- development version with editable install

### Docker Compose

Production-ready stack: MLflow + PostgreSQL + RustFS (S3-compatible artifact store). Provided in `docker-compose/` with environment file configuration.

### Kubernetes (Helm)

Production chart (`charts/`) with:

- TLS via Kubernetes Secrets
- Ingress with hostname validation
- PersistentVolumeClaim for storage
- Prometheus ServiceMonitor
- NetworkPolicy for traffic control
- RBAC (namespace and cluster-scoped)
- Garbage collection CronJob
- Secret-based database credentials
- Helm 3.8+, Kubernetes 1.23+

### Cloud Managed

Databricks (native), AWS SageMaker, Azure ML, Nebius.

---

## 6. Key Use Cases

| Use Case | MLflow Feature |
|---|---|
| Track ML experiments | Tracking API + UI |
| Compare model runs | Experiment search, metric comparison |
| Package models for deployment | Model flavors + `log_model()` |
| Version and promote models | Model Registry (stages) |
| Reproduce training runs | Projects (MLproject spec) |
| Monitor LLM applications | Tracing (OTel-native) |
| Evaluate LLM/RAG quality | GenAI evaluation, judges, scorers |
| Manage prompts | Prompt registry with versioning |
| Unify LLM provider APIs | AI Gateway |
| Deploy models to production | Deployments plugin system |
| Auto-log training metrics | `autolog()` for 30+ frameworks |
| Serve models via REST | `mlflow models serve` |
| Migrate file-based storage to DB | `fs2db` migration tool |

---

## 7. Server & API Layer

### Core Dependencies

- **Web**: Flask < 4, FastAPI < 1, Starlette < 2, Uvicorn < 1, Gunicorn < 27 (Linux), Waitress < 4 (Windows)
- **Database/ORM**: SQLAlchemy 1.4-2.x, Alembic < 2
- **Tracing**: OpenTelemetry API/SDK/Proto 1.9.0+
- **Data**: NumPy < 3, Pandas < 3, SciPy < 2, PyArrow 4.0-24.x, Scikit-learn < 2
- **Serialization**: Protobuf 3.12-7.x, Pydantic 2.x, PyYAML 5.1-6.x

### Protocol Buffers (`mlflow/protos/`)

REST API contracts defined in `.proto` files covering:

- Tracking service, model registry, assessments
- Databricks artifacts and tracing
- Jobs, issues, datasets, label schemas
- Prompt optimization

### CLI Entry Points

- `mlflow server` -- start tracking server
- `mlflow run` -- execute MLflow projects
- `mlflow models serve` -- model serving
- `mlflow models build-docker` -- Docker containerization
- `mlflow deployments` -- model deployment
- `mlflow experiments` -- experiment management
- `mlflow gateway` -- gateway server
- `mlflow gc` -- garbage collection
- `mlflow doctor` -- system diagnostics

---

## 8. CI/CD & Testing

### GitHub Actions (54 workflows)

- **Core testing**: Python tests split into 4 parallel groups (`master.yml`)
- **Cross-version**: Multi-version compatibility testing for ML frameworks
- **Examples**: Validation in 2 parallel groups, scheduled daily
- **Benchmarks**: Gateway and tracing performance benchmarks
- **Quality**: Ruff linting, PR title/size validation, protobuf generation
- **Docs**: Documentation building and preview generation
- **Helm**: Chart validation
- **JS/TS**: JavaScript/TypeScript test suite
- **Release**: Automated release notes, wheel building, Docker image publishing
- **PR automation**: Auto-assign, stale detection, duplicate PR detection, triage

### Test Structure (73 directories)

- Per-flavor integration tests for every model flavor
- Store backend tests (file, SQL, REST)
- Server endpoint tests
- Tracing and OTel integration tests
- End-to-end integration tests
- Claude Code and MCP protocol tests

### Examples (76 directories)

Covering: agent frameworks (13), ML frameworks (21), time series (6), cloud/infra (8), model management (7), and specialized use cases (9+).

---

## 9. Architectural Patterns

### Lazy Loading

Model flavors are loaded on-demand via `LazyLoader` in `__init__.py` to minimize import time and avoid pulling in heavy optional dependencies.

### Store Abstraction

Abstract base class per store type with multiple backend implementations (file, SQL, REST). Workspace-aware mixins add multi-tenancy support.

### Fluent + Client API

High-level convenience functions (e.g., `mlflow.start_run()`) delegate to the lower-level `MlflowClient`. Thread-safe context management for nested runs.

### Plugin System

Entry-point based extensibility:

- `mlflow.deployment` -- custom deployment targets
- `mlflow.app` -- custom Flask/FastAPI applications
- Model flavors can be registered as plugins
- Discovery via `importlib.metadata.entry_points()`

### Autologging Framework

Framework-specific monkey patching via `@autologging_integration` decorator. Queuing client for efficient batch logging. Post-training metrics capture.

### Protobuf-First API Design

REST API contracts defined in `.proto` files, generated to Python. Ensures schema consistency across server, client, and SDK.

### Multi-Workspace Support

Workspace-aware stores for Databricks multi-tenancy. Workspace context propagation through REST API headers.

---

## 10. Sub-Packages (`libs/`)

### mlflow-skinny (`libs/skinny/`)

Minimal-dependency client for production environments. Excludes server, UI, and heavy ML framework dependencies. Significantly smaller install footprint.

### mlflow-tracing (`libs/tracing/`)

Standalone tracing/observability SDK for GenAI applications. Supports automatic tracing for OpenAI, LangChain, DSPy, Anthropic, and others. Manual instrumentation via `@trace` decorator. No tracking server, UI, or model registry included.

### TypeScript SDK (`libs/typescript/`)

Monorepo with core library and 10 provider integrations:

- `anthropic`, `claude-code`, `codex`, `gemini`, `openai`, `opencode`, `openclaw`, `qwen-code`, `vercel`, `helpers`

---

## 11. Supplementary Tools

### fs2db (`fs2db/`)

FileStore-to-database migration tool. Converts `./mlruns` file-based storage to SQL backends:

```bash
mlflow migrate-filestore --source ./mlruns --target sqlite:///mlflow.db
```

### Development Tools (`dev/`)

26 Python scripts and 16+ shell scripts covering:

- `run_dev_server.py` -- local dev environment (backend + React frontend)
- `generate_protos.py` -- protocol buffer code generation
- `pyproject.py` -- autogenerates skinny/tracing package metadata
- `create_release_branch.py` / `create_release_tag.py` -- release automation
- `check_function_signatures.py` -- API signature validation
- Benchmarking, profiling, custom linter (`clint/`), proto-to-GraphQL converter

---

## 12. Hallucination Detection

MLflow provides comprehensive hallucination detection as a first-class capability, documented at [mlflow.org/ai-monitoring](https://mlflow.org/ai-monitoring). The codebase contains concrete implementations across multiple layers.

### Direct Hallucination Scorers

Three dedicated `Hallucination` scorer classes via third-party integrations:

| Scorer | Path | Version |
|---|---|---|
| DeepEval | `mlflow/genai/scorers/deepeval/scorers/__init__.py` | v3.8.0 |
| Phoenix/Arize | `mlflow/genai/scorers/phoenix/__init__.py` | v3.9.0 |
| Google ADK | `mlflow/genai/scorers/google_adk/__init__.py` (wraps `HallucinationsV1Evaluator`) | v3.11.0 |

### Groundedness Judges

Built-in judges that determine whether a response is supported by provided context:

- **`mlflow/genai/judges/builtin.py`** -- `is_grounded(request, response, context)` returns yes/no feedback
- **`mlflow/genai/judges/prompts/groundedness.py`** -- dedicated prompt template instructing the judge to evaluate claims against documents without external knowledge
- **`mlflow/genai/scorers/builtin_scorers.py`** -- `RetrievalGroundedness` scorer, described as assessing "whether the facts in the response are implied by the information in the last retrieval step, i.e., hallucinations do not occur"
- **`mlflow/genai/scorers/trulens/__init__.py`** -- `Groundedness` scorer using chain-of-thought reasoning (v3.10.0)

### Faithfulness Metrics

Evaluate factual consistency between generated output and source context:

- **`mlflow/metrics/genai/metric_definitions.py`** -- `faithfulness()` metric: "Evaluates the faithfulness of an LLM... based on how factually consistent the output is to the context"
- **`mlflow/genai/scorers/deepeval/scorers/rag_metrics.py`** -- `Faithfulness` scorer: "It helps detect hallucinations by checking if the generated content is grounded in the retrieval context"
- **`mlflow/genai/scorers/ragas/scorers/rag_metrics.py`** -- RAGAS `Faithfulness` scorer
- **`mlflow/genai/scorers/ragas/scorers/__init__.py`** -- RAGAS `ResponseGroundedness` scorer

### Issue Categorization

- **`mlflow/genai/discovery/entities.py`** -- hallucination is a recognized category tag in the discovery triage system, enabling automated issue routing

### How It Works in Practice

All scorers integrate with `mlflow.genai.evaluate()` and can run:

- **Offline**: during development/evaluation to benchmark model quality
- **Online**: asynchronously against production traces to detect quality drift
- **Scheduled**: via scheduled scorers for continuous monitoring

The system supports multiple LLM backends as judges (OpenAI, Anthropic, Databricks, Gemini) and both rule-based and LLM-based evaluation approaches.
