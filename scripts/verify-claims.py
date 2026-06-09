#!/usr/bin/env python3
"""Verify extracted claims against source material in artifact directories.

Reads unverified claims from the database, finds co-located source material
in ./var/artifacts/, and uses Claude via Vertex AI as a judge to evaluate
each claim against the evidence.

Usage:
    python scripts/verify-claims.py                    # verify all pending
    python scripts/verify-claims.py --limit 50         # verify N claims
    python scripts/verify-claims.py --jira RHAISTRAT-1676  # verify claims for a Jira key
    python scripts/verify-claims.py --workers 3        # concurrent workers

Requires:
    - anthropic[vertex] pip package
    - GCP credentials
"""

import argparse
import concurrent.futures
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

try:
    from anthropic import AnthropicVertex
except ImportError:
    sys.exit("anthropic[vertex] is required: pip install 'anthropic[vertex]'")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("verify-claims")

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "var" / "artifacts"
DB_PATH = ROOT / "data" / "observatory.db"

# Load .env
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

PROJECT_ID = os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID", "itpc-gcp-ai-eng-claude")
REGION = os.environ.get("CLOUD_ML_REGION", "global")
MODEL = os.environ.get("CLAIM_VERIFICATION_MODEL", "claude-sonnet-4-6")
FALLBACK_MODEL = os.environ.get("CLAIM_VERIFICATION_FALLBACK_MODEL", "claude-opus-4-6")
FALLBACK_THRESHOLD = 50  # re-verify with Opus if Sonnet confidence <= this

VERIFICATION_PROMPT = """\
You are a factual claim verification system. Given a CLAIM extracted from an AI-generated document, and SOURCE MATERIAL, determine whether the claim is supported by the evidence.

The source material is organized into labeled sections. Pay close attention to the section headers to understand what each piece of evidence represents:

1. **"Source:" sections** — the original text the AI agent was working from. These describe what is being PROPOSED or REVIEWED, not necessarily what currently exists in the platform.

2. **"Architecture Context:" and "Architecture Search:" sections** — authoritative RHOAI component documentation from the architecture-context repository (via arch-query). This represents what CURRENTLY EXISTS in the platform. If arch-query returns no results for a term, that term does not exist in the current platform architecture.

3. **"Raw Architecture Doc:" sections** — full component markdown files from the architecture-context repository. Same authority as arch-query — represents current platform state.

4. **"Platform Summary:" sections** — authoritative platform-level facts (image counts, component counts). These are ground truth for the current platform.

5. **"NFR checklist" sections** — security non-functional requirements checklist. A generated requirement that maps to a checklist item is valid (not hallucinated).

6. **"Architecture Overlays" sections** — recent architecture updates including component renames (e.g., Llama Stack → OGX).

CRITICAL DISTINCTION: When a claim says something "does not exist" or "has no reference" in the platform architecture, verify against the arch-query/architecture-doc sections ONLY, not the source document sections. The source documents describe proposals — they may mention a technology that is being newly introduced, which does NOT mean it already exists in the platform.

When verifying architectural claims, connect related facts from the same source. For example, if the source says component X has a kube-rbac-proxy sidecar AND lists port 8443 as HTTPS, then "X uses kube-rbac-proxy on port 8443" is supported.

Evaluate based on the provided source material. Do not use external knowledge.

Return a JSON object with these fields:
- "verdict": one of "supported", "refuted", "insufficient", "inconclusive"
  - "supported": the source material clearly supports this claim
  - "refuted": the source material contradicts this claim
  - "insufficient": no relevant evidence found in the source material
  - "inconclusive": the source material is ambiguous about this claim
- "confidence": 0-100 integer
- "evidence_summary": one sentence explaining the verdict
- "evidence_quote": the most relevant quote from the source material (or null if insufficient)

Return ONLY the JSON object, no markdown fences.

CLAIM:
{claim}

SOURCE MATERIAL:
{source}
"""


def get_client() -> AnthropicVertex:
    return AnthropicVertex(project_id=PROJECT_ID, region=REGION)


ARCH_QUERY = ROOT / "var" / "bin" / "arch-query"
ARCH_CONTEXT = ROOT / "var" / "checkouts" / "architecture-context" / "architecture"

# Versions the agents are most likely referencing
ARCH_VERSIONS = ["rhoai-3.4", "rhoai-3.3", "rhoai-3.5-ea.1", "rhoai.next"]
VERSION_RE = re.compile(r"(?:rhoai|RHOAI)[\s-]*([\d.]+(?:-ea\.?\d*)?)", re.IGNORECASE)


def _detect_version(text: str) -> str | None:
    """Detect RHOAI version from text. Returns arch-query version string or None."""
    m = VERSION_RE.search(text)
    if not m:
        return None
    ver = m.group(1)
    # Map to arch-query version format
    candidates = [f"rhoai-{ver}", f"rhoai-{ver.replace('.', '-')}"]
    for c in candidates:
        if (ARCH_CONTEXT / c).is_dir():
            return c
    return None


def _arch_query_cmd(args: list[str], version: str | None = None) -> str | None:
    """Run an arch-query command and return stdout."""
    if not ARCH_QUERY.exists() or not ARCH_CONTEXT.exists():
        return None
    cmd = [str(ARCH_QUERY), "--base-dir", str(ARCH_CONTEXT)] + args
    if version:
        cmd.extend(["--version", version])
    try:
        import subprocess
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout[:20000]
    except Exception:
        pass
    return None


def _run_arch_query(component: str, version: str | None = None) -> str | None:
    return _arch_query_cmd(["component", component], version)


def _run_arch_query_raw(command: str, version: str | None = None) -> str | None:
    return _arch_query_cmd([command, "-o", "raw"], version)


def _run_arch_grep(term: str, version: str | None = None) -> str | None:
    return _arch_query_cmd(["grep", term], version)


RAW_ARCH_DIR = ROOT / "var" / "checkouts" / "architecture-context" / "architecture" / "rhoai-3.5-ea.1"


def _get_raw_arch_docs(claim_text: str, evidence: "EvidenceResult") -> str | None:
    """Read raw architecture markdown files for components mentioned in the claim.

    Reads the full .md files from the architecture-context checkout.
    Updates evidence.file_sources and evidence.arch_queries with specific files used.
    """
    if not RAW_ARCH_DIR.exists():
        return None

    components = _extract_component_names(claim_text)
    if not components:
        return None

    texts = []
    for comp in components[:3]:
        md_path = RAW_ARCH_DIR / f"{comp}.md"
        if not md_path.exists():
            continue
        content = md_path.read_text(errors="replace")
        if len(content) > 15000:
            content = content[:15000] + "\n[truncated]"
        rel_path = f"var/checkouts/architecture-context/architecture/rhoai-3.5-ea.1/{comp}.md"
        evidence.file_sources.append(rel_path)
        evidence.arch_queries.append(f"raw-doc:{comp}.md")
        texts.append(f"--- Raw Architecture Doc: {comp}.md (rhoai-3.5-ea.1) ---\n{content}")

    # Also check PLATFORM.md for platform-level claims
    platform_keywords = ["platform", "ships", "container image", "PLATFORM.md"]
    if any(kw.lower() in claim_text.lower() for kw in platform_keywords):
        platform_path = RAW_ARCH_DIR / "PLATFORM.md"
        if platform_path.exists():
            content = platform_path.read_text(errors="replace")
            if len(content) > 15000:
                content = content[:15000] + "\n[truncated]"
            evidence.file_sources.append("var/checkouts/architecture-context/architecture/rhoai-3.5-ea.1/PLATFORM.md")
            evidence.arch_queries.append("raw-doc:PLATFORM.md")
            texts.append(f"--- Raw Architecture Doc: PLATFORM.md (rhoai-3.5-ea.1) ---\n{content}")

    if not texts:
        return None

    return "\n\n".join(texts)


_overlays_cache: str | None = None


def _get_arch_overlays() -> str | None:
    """Get active overlays from arch-query (cached)."""
    global _overlays_cache
    if _overlays_cache is not None:
        return _overlays_cache if _overlays_cache else None

    if not ARCH_QUERY.exists() or not ARCH_CONTEXT.exists():
        _overlays_cache = ""
        return None
    try:
        import subprocess
        result = subprocess.run(
            [str(ARCH_QUERY), "--base-dir", str(ARCH_CONTEXT), "overlays"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            _overlays_cache = result.stdout[:20000]
            return _overlays_cache
    except Exception:
        pass
    _overlays_cache = ""
    return None


_component_list: list[str] | None = None
_component_aliases: dict[str, str] = {
    "ogx": "llama-stack",
    "ogx distribution": "llama-stack",
    "llama stack": "llama-stack",
    "llamastack": "llama-stack",
    "llama stack distribution": "llama-stack",
    "llama-stack-distribution": "llama-stack",
    "ogx k8s operator": "llama-stack-k8s-operator",
    "ogx operator": "llama-stack-k8s-operator",
}


def _get_component_list() -> list[str]:
    """Get the full component list from arch-query (cached)."""
    global _component_list
    if _component_list is not None:
        return _component_list

    if not ARCH_QUERY.exists() or not ARCH_CONTEXT.exists():
        _component_list = []
        return _component_list

    try:
        import subprocess
        result = subprocess.run(
            [str(ARCH_QUERY), "--base-dir", str(ARCH_CONTEXT), "list", "--names-only"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            _component_list = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        else:
            _component_list = []
    except Exception:
        _component_list = []

    return _component_list


def _extract_component_names(claim_text: str) -> list[str]:
    """Extract component names from a claim for arch-query lookup."""
    text_lower = claim_text.lower()
    found = []

    # Check aliases first
    for alias, canonical in _component_aliases.items():
        if alias in text_lower:
            found.append(canonical)

    # Check actual component names from arch-query
    for comp in _get_component_list():
        if comp.lower() in text_lower:
            found.append(comp)

    return list(set(found))


VERIFICATION_DIR = ROOT / "var" / "verification"


class EvidenceResult:
    def __init__(self):
        self.file_sources: list[str] = []
        self.arch_queries: list[str] = []
        self.combined_text: str = ""

    @property
    def has_evidence(self) -> bool:
        return bool(self.combined_text)


def find_source_material(source_file: str, claim_text: str = "", claim_type: str = "") -> EvidenceResult:
    """Find source/ground-truth material for verifying a claim."""
    result = EvidenceResult()
    source_path = ARTIFACTS / source_file
    if not source_path.exists():
        return result

    parent = source_path.parent
    sources = []

    # Security reviews: look for *-strat-text.md and *-threat-surface.md
    for pattern in ["*-strat-text.md", "*-threat-surface.md"]:
        for p in parent.glob(pattern):
            if p != source_path:
                sources.append(p)
        for p in parent.parent.rglob(pattern):
            if p != source_path:
                sources.append(p)

    # Strat pipeline: look for strat-originals/ sibling
    originals_dir = parent.parent / "strat-originals"
    if originals_dir.exists():
        for p in originals_dir.glob("*.md"):
            sources.append(p)

    # NFR checklist — ground truth for generated security requirements
    nfr_checklist = ROOT / "var" / "definitions" / "strat-security-reviews" / "source-repo" / ".claude" / "skills" / "strat-security-review" / "references" / "nfr-checklist.md"
    if nfr_checklist.exists() and claim_type in ("security", ""):
        sources.append(nfr_checklist)

    # Concatenate file-based sources
    texts = []
    seen_paths: set[str] = set()
    for p in sources[:5]:
        if str(p) in seen_paths:
            continue
        seen_paths.add(str(p))
        result.file_sources.append(str(p.relative_to(ROOT)))
        text = p.read_text(errors="replace")
        if len(text) > 20000:
            text = text[:20000] + "\n[truncated]"
        texts.append(f"--- Source: {p.name} ---\n{text}")

    # Architecture context for architectural/security claims
    if claim_type in ("architectural", "security"):
        # Detect RHOAI version from claim text and source file path
        version = _detect_version(claim_text)
        if not version:
            # Try to detect from source file content (first few source files)
            for p in sources[:2]:
                try:
                    sample = p.read_text(errors="replace")[:2000]
                    version = _detect_version(sample)
                    if version:
                        break
                except Exception:
                    pass
        # Default to current GA if no version detected
        if not version:
            version = "rhoai-3.4"

        version_label = f" (version={version})"

        components = _extract_component_names(claim_text)
        queried_components: set[str] = set()

        for comp in components[:3]:
            arch_data = _run_arch_query(comp, version)
            if arch_data:
                result.arch_queries.append(f"component {comp}{version_label}")
                queried_components.add(comp)
                texts.append(f"--- Architecture Context: {comp}{version_label} (via arch-query) ---\n{arch_data}")

        # Grep for terms that didn't resolve as component names
        grep_terms: set[str] = set()
        for alias in _component_aliases:
            if alias in claim_text.lower() and _component_aliases[alias] not in queried_components:
                grep_terms.add(alias)

        for m in re.finditer(r'\b(OGX|port \d+|mTLS|FIPS|certifi|kube-rbac-proxy|NetworkPolicy)\b', claim_text, re.IGNORECASE):
            grep_terms.add(m.group(0))

        for term in list(grep_terms)[:3]:
            grep_data = _run_arch_grep(term, version)
            if grep_data:
                result.arch_queries.append(f"grep {term}{version_label}")
                texts.append(f"--- Architecture Search: '{term}'{version_label} (via arch-query grep) ---\n{grep_data}")

        # Platform summary for platform-level claims
        platform_keywords = ["platform", "ships", "container image", "component", "PLATFORM.md"]
        if any(kw.lower() in claim_text.lower() for kw in platform_keywords):
            platform_data = _run_arch_query_raw("platform", version)
            if platform_data:
                result.arch_queries.append(f"platform -o raw{version_label}")
                texts.append(f"--- Platform Summary{version_label} (via arch-query platform) ---\n{platform_data}")

        # Include overlays for naming/renaming context and recent changes
        overlays = _get_arch_overlays()
        if overlays:
            result.arch_queries.append("overlays")
            texts.append(f"--- Architecture Overlays (active) ---\n{overlays}")

        # Raw architecture docs — full component markdown from checkout
        raw_docs = _get_raw_arch_docs(claim_text, result)
        if raw_docs:
            texts.append(raw_docs)

    if texts:
        combined = "\n\n".join(texts)
        if len(combined) > 50000:
            combined = combined[:50000] + "\n[truncated]"
        result.combined_text = combined

    return result


def verify_claim(client: AnthropicVertex, claim_text: str, source_material: str, model: str | None = None) -> dict | None:
    """Call Claude to verify a claim against source material."""
    use_model = model or MODEL
    prompt = VERIFICATION_PROMPT.format(claim=claim_text, source=source_material)

    try:
        response = client.messages.create(
            model=use_model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        content = response.content[0].text.strip()
        if not content:
            log.warning("Empty response from %s", use_model)
            return None

        # Strip markdown fences
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

        # Try direct parse first
        try:
            result = json.loads(content)
            result["_model_used"] = use_model
            return result
        except json.JSONDecodeError:
            pass

        # Try to extract JSON object from the response
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                result = json.loads(content[start:end])
                result["_model_used"] = use_model
                return result
            except json.JSONDecodeError:
                pass

        # Last resort: try fixing common issues (unescaped newlines in strings)
        try:
            fixed = re.sub(r'(?<!\\)\n', '\\n', content[start:end] if start >= 0 else content)
            result = json.loads(fixed)
            result["_model_used"] = use_model
            return result
        except (json.JSONDecodeError, Exception) as exc:
            log.warning("Failed to parse verdict JSON: %s — response: %s", exc, content[:200])
            return None
    except Exception as exc:
        log.error("API call failed (%s): %s", use_model, exc)
        return None


_db_lock = threading.Lock()
_verified = 0
_failed = 0


def _write_verification_log(
    claim_id: int,
    claim_text: str,
    claim_type: str,
    source_file: str,
    evidence: "EvidenceResult",
    verdict_result: dict | None,
) -> None:
    """Write a detailed markdown log for one claim verification."""
    VERIFICATION_DIR.mkdir(parents=True, exist_ok=True)
    log_path = VERIFICATION_DIR / f"{claim_id}.md"

    verdict = verdict_result.get("verdict", "error") if verdict_result else "error"
    confidence = verdict_result.get("confidence", 0) if verdict_result else 0
    summary = verdict_result.get("evidence_summary", "") if verdict_result else "Verification failed"
    quote = verdict_result.get("evidence_quote") if verdict_result else None
    model_used = verdict_result.get("_model_used", MODEL) if verdict_result else "none"
    lines = [
        f"# Claim {claim_id}",
        "",
        f"**Verdict:** {verdict}  ",
        f"**Confidence:** {confidence}%  ",
        f"**Model:** {model_used}  ",
        f"**Type:** {claim_type}  ",
        f"**Source file:** `{source_file}`",
        "",
        "## Claim",
        "",
        f"> {claim_text}",
        "",
        "## Evidence Sources",
        "",
    ]

    if evidence.file_sources:
        lines.append("### Files")
        for f in evidence.file_sources:
            lines.append(f"- `{f}`")
        lines.append("")

    if evidence.arch_queries:
        lines.append("### Architecture Queries")
        for q in evidence.arch_queries:
            if q.startswith("arch-query") or q.startswith("raw-doc:"):
                lines.append(f"- `{q}`")
            else:
                lines.append(f"- `arch-query {q}`")
        lines.append("")

    if not evidence.file_sources and not evidence.arch_queries:
        lines.append("_No evidence sources found_")
        lines.append("")

    lines.append("## Verdict")
    lines.append("")
    lines.append(f"**{verdict}** (confidence: {confidence}%)")
    lines.append("")
    if summary:
        lines.append(summary)
        lines.append("")
    if quote:
        lines.append("### Evidence Quote")
        lines.append("")
        lines.append(f"> {quote}")
        lines.append("")

    log_path.write_text("\n".join(lines))


def process_claim(args_tuple: tuple) -> None:
    """Worker function for thread pool."""
    client, claim_id, claim_text, claim_type, source_files_str = args_tuple
    global _verified, _failed

    # Gather evidence from all source files for this claim
    source_files = source_files_str.split(",") if source_files_str else []
    evidence = EvidenceResult()
    for sf in source_files:
        sf = sf.strip()
        if not sf:
            continue
        partial = find_source_material(sf, claim_text, claim_type)
        # Merge evidence
        evidence.file_sources.extend(partial.file_sources)
        evidence.arch_queries.extend(partial.arch_queries)
        if partial.combined_text:
            if evidence.combined_text:
                evidence.combined_text += "\n\n" + partial.combined_text
            else:
                evidence.combined_text = partial.combined_text

    # Deduplicate
    evidence.file_sources = list(dict.fromkeys(evidence.file_sources))
    evidence.arch_queries = list(dict.fromkeys(evidence.arch_queries))
    if len(evidence.combined_text) > 50000:
        evidence.combined_text = evidence.combined_text[:50000] + "\n[truncated]"

    source_file = source_files[0] if source_files else "unknown"
    if not evidence.has_evidence:
        _write_verification_log(claim_id, claim_text, claim_type, source_file, evidence, None)
        return

    result = verify_claim(client, claim_text, evidence.combined_text)

    # Fallback to Opus if Sonnet is inconclusive or low confidence
    if result and FALLBACK_MODEL != MODEL:
        verdict_val = result.get("verdict", "")
        conf_val = result.get("confidence", 0)
        if verdict_val == "inconclusive" or (verdict_val == "insufficient" and conf_val <= FALLBACK_THRESHOLD):
            log.info("Claim %d: Sonnet returned %s (%d%%) — escalating to %s", claim_id, verdict_val, conf_val, FALLBACK_MODEL)
            opus_result = verify_claim(client, claim_text, evidence.combined_text, model=FALLBACK_MODEL)
            if opus_result:
                result = opus_result

    # Always write the log file
    _write_verification_log(claim_id, claim_text, claim_type, source_file, evidence, result)

    if not result:
        with _db_lock:
            _failed += 1
        return

    verdict = result.get("verdict", "inconclusive")
    confidence = result.get("confidence", 0)
    evidence_summary = result.get("evidence_summary", "")
    evidence_quote = result.get("evidence_quote")
    model_used = result.get("_model_used", MODEL)

    evidence_source_str = f"llm-judge({model_used})"
    if evidence.arch_queries:
        evidence_source_str = f"llm-judge({model_used})+arch-query"
    if any(q.startswith("raw-doc:") for q in evidence.arch_queries):
        evidence_source_str += "+raw-arch-docs"

    with _db_lock:
        db = sqlite3.connect(DB_PATH)
        db.execute(
            """INSERT INTO claim_verdicts
                (claim_id, verdict, confidence, evidence_summary, evidence_source, evidence_detail)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (claim_id, verdict, confidence, evidence_summary, evidence_source_str, evidence_quote),
        )
        db.commit()
        db.close()
        _verified += 1

    log.info("Claim %d: %s (confidence=%d) — %s", claim_id, verdict, confidence, claim_text[:80])


CLAUDE_BIN = os.environ.get("CLAUDE_BIN", os.path.expanduser("~/.local/bin/claude"))
SKILL_FILE = ROOT / ".claude" / "skills" / "verify-claim" / "SKILL.md"

CLAUDE_ENV = {
    "CLAUDE_CODE_USE_VERTEX": "1",
    "CLOUD_ML_REGION": os.environ.get("CLOUD_ML_REGION", "global"),
    "ANTHROPIC_VERTEX_PROJECT_ID": os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID", PROJECT_ID),
}


def find_warmup_evidence(source_file: str, claim_text: str = "", claim_type: str = "") -> EvidenceResult:
    """Gather file-based evidence only (no arch-query). Used in agentic mode."""
    result = EvidenceResult()
    source_path = ARTIFACTS / source_file
    if not source_path.exists():
        return result

    parent = source_path.parent
    sources = []

    for pattern in ["*-strat-text.md", "*-threat-surface.md"]:
        for p in parent.glob(pattern):
            if p != source_path:
                sources.append(p)
        for p in parent.parent.rglob(pattern):
            if p != source_path:
                sources.append(p)

    originals_dir = parent.parent / "strat-originals"
    if originals_dir.exists():
        for p in originals_dir.glob("*.md"):
            sources.append(p)

    nfr_checklist = ROOT / "var" / "definitions" / "strat-security-reviews" / "source-repo" / ".claude" / "skills" / "strat-security-review" / "references" / "nfr-checklist.md"
    if nfr_checklist.exists():
        sources.append(nfr_checklist)

    texts = []
    seen_paths: set[str] = set()
    for p in sources[:5]:
        if str(p) in seen_paths:
            continue
        seen_paths.add(str(p))
        result.file_sources.append(str(p.relative_to(ROOT)))
        text = p.read_text(errors="replace")
        if len(text) > 20000:
            text = text[:20000] + "\n[truncated]"
        texts.append(f"--- Source: {p.name} ---\n{text}")

    if texts:
        combined = "\n\n".join(texts)
        if len(combined) > 50000:
            combined = combined[:50000] + "\n[truncated]"
        result.combined_text = combined

    return result


CODEX_BIN = os.environ.get("CODEX_BIN", "codex")
VERDICT_SCHEMA = ROOT / "var" / "verification" / "verdict-schema.json"


def process_claim_agentic(args_tuple: tuple) -> None:
    """Worker function for agentic verification via Claude Code or Codex."""
    claim_id, claim_text, claim_type, source_files_str, agentic_model, engine = args_tuple
    global _verified, _failed

    source_files = source_files_str.split(",") if source_files_str else []
    evidence = EvidenceResult()
    for sf in source_files:
        sf = sf.strip()
        if not sf:
            continue
        partial = find_warmup_evidence(sf, claim_text, claim_type)
        evidence.file_sources.extend(partial.file_sources)
        if partial.combined_text:
            if evidence.combined_text:
                evidence.combined_text += "\n\n" + partial.combined_text
            else:
                evidence.combined_text = partial.combined_text

    evidence.file_sources = list(dict.fromkeys(evidence.file_sources))
    if len(evidence.combined_text) > 50000:
        evidence.combined_text = evidence.combined_text[:50000] + "\n[truncated]"

    source_file = source_files[0] if source_files else "unknown"

    # Write claim input to an isolated directory so concurrent workers don't interfere
    input_dir = ROOT / "var" / "verification" / "pending" / str(claim_id)
    input_dir.mkdir(parents=True, exist_ok=True)
    input_path = input_dir / f"{claim_id}.json"

    claim_input = {
        "claim_id": claim_id,
        "claim_text": claim_text,
        "claim_type": claim_type or "",
        "warmup_evidence": evidence.combined_text or "",
        "source_files": source_files,
    }
    input_path.write_text(json.dumps(claim_input, indent=2))

    try:
        if engine == "codex":
            prompt = f"$verify-claim {claim_id}"
            output_path = input_dir / "codex-output.json"
            cmd = [
                CODEX_BIN, "exec",
                prompt,
                "--sandbox", "read-only",
                "--output-schema", str(VERDICT_SCHEMA),
                "--output-last-message", str(output_path),
            ]
            if agentic_model not in ("sonnet", "opus"):
                cmd.extend(["-m", agentic_model])
            else:
                agentic_model = "gpt-5.5"
            proc_env = dict(os.environ)
        else:
            prompt = f"/verify-claim {claim_id}"
            cmd = [
                CLAUDE_BIN,
                "-p", prompt,
                "--model", agentic_model,
                "--effort", "medium",
                "--output-format", "json",
                "--no-session-persistence",
                "--allowedTools", "Bash,Read,Grep,Skill",
                "--dangerously-skip-permissions",
            ]
            proc_env = {**os.environ, **CLAUDE_ENV}
            skill_content = None

        log.info("Claim %d: starting agentic verification (%s)", claim_id, engine)
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=180, cwd=str(ROOT),
            env=proc_env, input="",
        )

        if proc.returncode != 0:
            log.warning("Claim %d: %s exited %d — stderr: %s", claim_id, engine, proc.returncode, proc.stderr[:500])
            with _db_lock:
                _failed += 1
            _write_verification_log(claim_id, claim_text, claim_type, source_file, evidence, None)
            return

        # Parse the JSON output from the agent. Codex stdout includes run logs, so prefer
        # the final-message file when available.
        if engine == "codex" and output_path.exists():
            output = output_path.read_text().strip()
        else:
            output = proc.stdout.strip()
        result = None
        try:
            parsed = json.loads(output)
            # --output-format json wraps in {"type":"result","result":...}
            if isinstance(parsed, dict) and "result" in parsed:
                result_text = parsed["result"]
            else:
                result_text = output
        except json.JSONDecodeError:
            result_text = output

        # Extract the verdict JSON from the result text
        if isinstance(result_text, str):
            # Try to find JSON in the result
            try:
                result = json.loads(result_text)
            except json.JSONDecodeError:
                start = result_text.find("{")
                end = result_text.rfind("}") + 1
                if start >= 0 and end > start:
                    try:
                        result = json.loads(result_text[start:end])
                    except json.JSONDecodeError:
                        pass
        elif isinstance(result_text, dict):
            result = result_text

        if not result or "verdict" not in result:
            log.warning("Claim %d: could not parse verdict from output: %s", claim_id, (result_text or "")[:200])
            with _db_lock:
                _failed += 1
            _write_verification_log(claim_id, claim_text, claim_type, source_file, evidence, None)
            return

        # Record tools used in the evidence result
        tools_used = result.get("tools_used", [])
        evidence.arch_queries.extend(tools_used)

        verdict = result.get("verdict", "inconclusive")
        confidence = result.get("confidence", 0)
        evidence_summary = result.get("evidence_summary", "")
        evidence_quote = result.get("evidence_quote")
        root_cause = result.get("root_cause")

        tool_count = len(tools_used)
        evidence_source_str = f"agentic({engine}:{agentic_model},{tool_count} tool calls)"

        # Include root cause in evidence detail
        detail_parts = []
        if evidence_quote:
            detail_parts.append(evidence_quote)
        if root_cause:
            detail_parts.append(f"root_cause: {root_cause}")
        evidence_detail = " | ".join(detail_parts) if detail_parts else evidence_quote

        with _db_lock:
            db = sqlite3.connect(DB_PATH)
            db.execute(
                """INSERT INTO claim_verdicts
                    (claim_id, verdict, confidence, evidence_summary, evidence_source, evidence_detail)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (claim_id, verdict, confidence, evidence_summary, evidence_source_str, evidence_detail),
            )
            db.commit()
            db.close()
            _verified += 1

        result["_model_used"] = f"agentic({engine}:{agentic_model})"
        _write_verification_log(claim_id, claim_text, claim_type, source_file, evidence, result)
        log.info("Claim %d: %s (confidence=%d, %d tools) — %s", claim_id, verdict, confidence, tool_count, claim_text[:80])

    except subprocess.TimeoutExpired:
        log.warning("Claim %d: agentic verification timed out after 120s", claim_id)
        with _db_lock:
            _failed += 1
    except Exception as exc:
        log.error("Claim %d: agentic error: %s", claim_id, exc)
        with _db_lock:
            _failed += 1
    finally:
        try:
            shutil.rmtree(input_dir, ignore_errors=True)
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser(description="Verify claims against source material")
    parser.add_argument("--limit", type=int, default=0, help="Max claims to verify (0=all pending)")
    parser.add_argument("--claim", type=int, help="Verify a single claim by ID (re-verifies even if already done)")
    parser.add_argument("--type", type=str, action="append", help="Verify only claims of this type (repeatable, e.g. --type security --type architectural)")
    parser.add_argument("--jira", type=str, help="Verify claims for a specific Jira key")
    parser.add_argument("--workers", type=int, default=None, help="Concurrent workers (default: 5 deterministic, 3 agentic)")
    parser.add_argument("--mode", choices=["deterministic", "agentic", "agentic-retry"],
                        default="deterministic", help="Evidence gathering mode (default: deterministic)")
    parser.add_argument("--agentic-model", default="sonnet", help="Model for agentic mode (default: sonnet)")
    parser.add_argument("--engine", choices=["claude", "codex"], default="claude",
                        help="Agent engine for agentic mode (default: claude)")
    args = parser.parse_args()

    if args.workers is None:
        args.workers = 3 if args.mode.startswith("agentic") else 5

    log.info("Using Vertex AI project=%s region=%s model=%s workers=%d", PROJECT_ID, REGION, MODEL, args.workers)

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    # Find claims to verify
    where_extra = ""
    extra_params: list = []

    if args.type:
        placeholders = ",".join("?" for _ in args.type)
        where_extra += f" AND c.claim_type IN ({placeholders})"
        extra_params.extend(args.type)

    if args.claim:
        # Single claim — always re-verify (delete existing verdict first)
        db.execute("DELETE FROM claim_verdicts WHERE claim_id = ?", (args.claim,))
        db.commit()
        query = f"""
            SELECT c.id, c.claim_text, c.claim_type,
                GROUP_CONCAT(DISTINCT cs.source_file) as source_files
            FROM claims c
            JOIN claim_sources cs ON cs.claim_id = c.id
            WHERE c.id = ?
            GROUP BY c.id
        """
        rows = db.execute(query, (args.claim,)).fetchall()
        db.close()
        if not rows:
            log.error("Claim %d not found", args.claim)
            return
        log.info("Re-verifying claim %d (mode=%s)", args.claim, args.mode)
        row = rows[0]
        if args.mode.startswith("agentic"):
            process_claim_agentic((row["id"], row["claim_text"], row["claim_type"] or "", row["source_files"], args.agentic_model, args.engine))
        else:
            client = get_client()
            process_claim((client, row["id"], row["claim_text"], row["claim_type"] or "", row["source_files"]))
        log.info("Done.")
        return

    if args.mode == "agentic-retry":
        # Re-verify claims that got insufficient or inconclusive verdicts
        # Delete existing verdicts so they can be re-verified
        query = f"""
            SELECT c.id, c.claim_text, c.claim_type,
                GROUP_CONCAT(DISTINCT cs.source_file) as source_files
            FROM claims c
            JOIN claim_sources cs ON cs.claim_id = c.id
            JOIN claim_verdicts cv ON cv.claim_id = c.id
            WHERE cv.verdict IN ('insufficient', 'inconclusive')
            AND c.claim_type IN ('architectural', 'security')
            {where_extra}
            GROUP BY c.id
            ORDER BY c.id DESC
        """
        rows = db.execute(query, extra_params).fetchall()
        # Delete existing verdicts for these claims so we can re-verify
        for r in rows:
            db.execute("DELETE FROM claim_verdicts WHERE claim_id = ?", (r["id"],))
        db.commit()
    elif args.jira:
        query = f"""
            SELECT c.id, c.claim_text, c.claim_type,
                GROUP_CONCAT(DISTINCT cs.source_file) as source_files
            FROM claims c
            JOIN claim_sources cs ON cs.claim_id = c.id
            JOIN claim_jira_keys jk ON jk.claim_id = c.id
            WHERE jk.jira_key = ? AND c.id NOT IN (SELECT claim_id FROM claim_verdicts)
            {where_extra}
            GROUP BY c.id
            ORDER BY c.id DESC
        """
        rows = db.execute(query, (args.jira, *extra_params)).fetchall()
    else:
        query = f"""
            SELECT c.id, c.claim_text, c.claim_type,
                GROUP_CONCAT(DISTINCT cs.source_file) as source_files
            FROM claims c
            JOIN claim_sources cs ON cs.claim_id = c.id
            WHERE c.id NOT IN (SELECT claim_id FROM claim_verdicts)
            {where_extra}
            GROUP BY c.id
            ORDER BY c.id DESC
        """
        rows = db.execute(query, extra_params).fetchall()

    db.close()

    if args.limit > 0:
        rows = rows[:args.limit]

    if not rows:
        log.info("No pending claims to verify")
        return

    use_agentic = args.mode.startswith("agentic")
    arch_status = "available" if ARCH_QUERY.exists() and ARCH_CONTEXT.exists() else "not available"
    log.info("Verifying %d claims (mode=%s, arch-query: %s, workers: %d)",
             len(rows), args.mode, arch_status, args.workers)

    if use_agentic:
        work_items = [(r["id"], r["claim_text"], r["claim_type"] or "", r["source_files"], args.agentic_model, args.engine) for r in rows]
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            pool.map(process_claim_agentic, work_items)
    else:
        client = get_client()
        work_items = [(client, r["id"], r["claim_text"], r["claim_type"] or "", r["source_files"]) for r in rows]
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            pool.map(process_claim, work_items)

    log.info("Done. Verified %d claims, %d failed.", _verified, _failed)


if __name__ == "__main__":
    main()
