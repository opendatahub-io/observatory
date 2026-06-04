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
import sqlite3
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
You are a factual claim verification system. Given a CLAIM extracted from an AI-generated document, and SOURCE MATERIAL that the AI was working from, determine whether the claim is supported by the evidence.

Evaluate ONLY whether the source material supports the claim. Do not use external knowledge.

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


def _run_arch_query(component: str) -> str | None:
    """Run arch-query for a component and return the output."""
    if not ARCH_QUERY.exists() or not ARCH_CONTEXT.exists():
        return None
    try:
        import subprocess
        result = subprocess.run(
            [str(ARCH_QUERY), "--base-dir", str(ARCH_CONTEXT), "component", component],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout[:15000]
    except Exception:
        pass
    return None


def _run_arch_grep(term: str) -> str | None:
    """Run arch-query grep to find components by any term (handles renames, aliases)."""
    if not ARCH_QUERY.exists() or not ARCH_CONTEXT.exists():
        return None
    try:
        import subprocess
        result = subprocess.run(
            [str(ARCH_QUERY), "--base-dir", str(ARCH_CONTEXT), "grep", term],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout[:15000]
    except Exception:
        pass
    return None


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
        components = _extract_component_names(claim_text)
        queried_components: set[str] = set()

        for comp in components[:3]:
            arch_data = _run_arch_query(comp)
            if arch_data:
                result.arch_queries.append(f"component {comp}")
                queried_components.add(comp)
                texts.append(f"--- Architecture Context: {comp} (via arch-query component) ---\n{arch_data}")

        # Grep for terms that didn't resolve as component names
        # Also grep for aliases/renames that arch-query handles via deep search
        grep_terms: set[str] = set()
        for alias in _component_aliases:
            if alias in claim_text.lower() and _component_aliases[alias] not in queried_components:
                grep_terms.add(alias)

        # Extract other key terms (port numbers, specific tech)
        import re
        for m in re.finditer(r'\b(OGX|port \d+|mTLS|FIPS|certifi|kube-rbac-proxy|NetworkPolicy)\b', claim_text, re.IGNORECASE):
            grep_terms.add(m.group(0))

        for term in list(grep_terms)[:3]:
            grep_data = _run_arch_grep(term)
            if grep_data:
                result.arch_queries.append(f"grep {term}")
                texts.append(f"--- Architecture Search: '{term}' (via arch-query grep) ---\n{grep_data}")

        # Include overlays for naming/renaming context and recent changes
        overlays = _get_arch_overlays()
        if overlays:
            result.arch_queries.append("overlays")
            texts.append(f"--- Architecture Overlays (active) ---\n{overlays}")

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
            import re
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
        for comp in evidence.arch_queries:
            lines.append(f"- `arch-query component {comp}`")
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
    client, claim_id, claim_text, claim_type, source_file = args_tuple
    global _verified, _failed

    evidence = find_source_material(source_file, claim_text, claim_type)
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


def main():
    parser = argparse.ArgumentParser(description="Verify claims against source material")
    parser.add_argument("--limit", type=int, default=0, help="Max claims to verify (0=all pending)")
    parser.add_argument("--type", type=str, action="append", help="Verify only claims of this type (repeatable, e.g. --type security --type architectural)")
    parser.add_argument("--jira", type=str, help="Verify claims for a specific Jira key")
    parser.add_argument("--workers", type=int, default=3, help="Concurrent workers (default: 3)")
    args = parser.parse_args()

    log.info("Using Vertex AI project=%s region=%s model=%s workers=%d", PROJECT_ID, REGION, MODEL, args.workers)

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    # Find unverified claims with source files
    where_extra = ""
    extra_params: list = []

    if args.type:
        placeholders = ",".join("?" for _ in args.type)
        where_extra += f" AND c.claim_type IN ({placeholders})"
        extra_params.extend(args.type)

    if args.jira:
        query = f"""
            SELECT DISTINCT c.id, c.claim_text, c.claim_type, cs.source_file
            FROM claims c
            JOIN claim_sources cs ON cs.claim_id = c.id
            JOIN claim_jira_keys jk ON jk.claim_id = c.id
            WHERE jk.jira_key = ? AND c.id NOT IN (SELECT claim_id FROM claim_verdicts)
            {where_extra}
            ORDER BY c.id DESC
        """
        rows = db.execute(query, (args.jira, *extra_params)).fetchall()
    else:
        query = f"""
            SELECT DISTINCT c.id, c.claim_text, c.claim_type, cs.source_file
            FROM claims c
            JOIN claim_sources cs ON cs.claim_id = c.id
            WHERE c.id NOT IN (SELECT claim_id FROM claim_verdicts)
            {where_extra}
            ORDER BY c.id DESC
        """
        rows = db.execute(query, extra_params).fetchall()

    db.close()

    if args.limit > 0:
        rows = rows[:args.limit]

    if not rows:
        log.info("No pending claims to verify")
        return

    arch_status = "available" if ARCH_QUERY.exists() and ARCH_CONTEXT.exists() else "not available"
    log.info("Verifying %d claims (arch-query: %s)", len(rows), arch_status)

    client = get_client()
    work_items = [(client, r["id"], r["claim_text"], r["claim_type"] or "", r["source_file"]) for r in rows]

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        pool.map(process_claim, work_items)

    log.info("Done. Verified %d claims, %d failed.", _verified, _failed)


if __name__ == "__main__":
    main()
