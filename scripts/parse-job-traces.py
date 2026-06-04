#!/usr/bin/env python3
"""Parse job trace logs into structured JSON events.

Reads job-trace.log files from ./var/artifacts/ and writes structured
event JSON to ./var/traces/.

Usage:
    python scripts/parse-job-traces.py                    # all traces
    python scripts/parse-job-traces.py rfe-assessor       # single pipeline
    python scripts/parse-job-traces.py --limit 5          # first N per pipeline
"""

import argparse
import json
import logging
import re
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("parse-traces")

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "var" / "artifacts"
TRACES = ROOT / "var" / "traces"

LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T[\d:.]+Z)\s+\d{2}[OE]\+?\s?(.*)")

# Package patterns
RPM_INSTALL_RE = re.compile(r"^Installing:\s+([^;]+);([^;]+);([^;]+);(.+)")
PIP_COLLECTING_RE = re.compile(r"^Collecting\s+(\S+?)(?:[=><!]+(.+?))?(?:\s|$)")
PIP_DOWNLOADING_RE = re.compile(r"^Downloading\s+(\S+?)-(\S+?)[-.](?:py|cp|tar|whl)")

# Runner/infra patterns
DOCKER_IMAGE_RE = re.compile(r"Using docker image (sha256:\w+) for (\S+)")
RUNNER_RE = re.compile(r"Running on (runner-\S+)")
CHECKOUT_RE = re.compile(r"Checking out (\w+) as")
CLAUDE_VERSION_RE = re.compile(r"^(\d+\.\d+\.\d+) \(Claude Code\)")

# Agent output patterns
TOOL_CALL_RE = re.compile(r"🔧\s+(\w+)\s+\$\s+(.*)")
SUBAGENT_RE = re.compile(r"🤖\s+Agent\s+\[([^\]]+)\]\s+(.*)")


def classify_line(content: str, state: dict) -> dict | None:
    """Classify a single line and return a structured event, or None to skip."""
    if not content:
        return None

    # Section markers
    if "section_start:" in content or "section_end:" in content:
        return None

    # Thinking
    if "🧠" in content:
        text = content.split("🧠", 1)[1].strip()
        if text.startswith("Thinking "):
            text = text[9:]
        state["in_block"] = "thinking"
        state["block_content"] = [text]
        return None  # will emit on block end

    # Response
    if "💬" in content:
        text = content.split("💬", 1)[1].strip()
        if text.startswith("Claude "):
            text = text[7:]
        # Flush any pending thinking block
        event = _flush_block(state)
        state["in_block"] = "response"
        state["block_content"] = [text]
        return event  # return flushed thinking, response will flush later

    # Tool call
    m = TOOL_CALL_RE.search(content)
    if m:
        event = _flush_block(state)
        tool_event = {"type": "tool_call", "tool": m.group(1), "command": m.group(2)}
        if event:
            state["_pending"] = tool_event
            return event
        return tool_event

    # Subagent spawn
    m = SUBAGENT_RE.search(content)
    if m:
        event = _flush_block(state)
        sub_event = {"type": "subagent_spawn", "agent_id": m.group(1), "prompt": m.group(2)}
        if event:
            state["_pending"] = sub_event
            return event
        return sub_event

    # RPM package install
    m = RPM_INSTALL_RE.match(content)
    if m:
        return {"type": "package_install", "manager": "rpm", "name": m.group(1), "version": m.group(2), "arch": m.group(3), "repo": m.group(4)}

    # Pip collecting
    m = PIP_COLLECTING_RE.match(content)
    if m and not content.startswith("  "):
        return {"type": "package_install", "manager": "pip", "name": m.group(1), "version": m.group(2) or ""}

    # Docker image
    m = DOCKER_IMAGE_RE.search(content)
    if m:
        return {"type": "metadata", "key": "container_image", "value": m.group(2), "digest": m.group(1)}

    # Runner
    m = RUNNER_RE.search(content)
    if m:
        return {"type": "metadata", "key": "runner_id", "value": m.group(1)}

    # Git checkout
    m = CHECKOUT_RE.search(content)
    if m:
        return {"type": "metadata", "key": "git_sha", "value": m.group(1)}

    # Claude version
    m = CLAUDE_VERSION_RE.match(content)
    if m:
        return {"type": "metadata", "key": "claude_version", "value": m.group(1)}

    # Exit code
    if "Claude exit code:" in content:
        code = re.search(r"exit code:\s*(\d+)", content)
        return {"type": "metadata", "key": "exit_code", "value": code.group(1) if code else "unknown"}

    # Cost summary lines
    if any(x in content for x in ["CLAUDE TOKEN", "Token Type", "cacheRead", "cacheCreation"]):
        return {"type": "cost_summary", "text": content.strip()}

    if content.strip().startswith("Model:"):
        return {"type": "metadata", "key": "model", "value": content.split(":", 1)[1].strip()}

    # Shell command
    if content.startswith("$ "):
        event = _flush_block(state)
        cmd_event = {"type": "shell_command", "command": content[2:]}
        if event:
            state["_pending"] = cmd_event
            return event
        return cmd_event

    # Continuation of multi-line block
    if state.get("in_block"):
        state["block_content"].append(content)
        return None

    # Job status
    if content.strip() == "Job succeeded":
        return {"type": "metadata", "key": "job_status", "value": "succeeded"}
    if content.strip() == "Job failed":
        return {"type": "metadata", "key": "job_status", "value": "failed"}

    return None


def _flush_block(state: dict) -> dict | None:
    """Flush a pending multi-line block (thinking/response)."""
    if not state.get("in_block"):
        return None
    block_type = state["in_block"]
    content = "\n".join(state["block_content"]).strip()
    state["in_block"] = None
    state["block_content"] = []
    if not content:
        return None
    return {"type": block_type, "text": content}


def parse_trace(trace_path: Path) -> dict:
    """Parse a single job trace file into structured events."""
    events: list[dict] = []
    packages: list[dict] = []
    metadata: dict[str, str] = {}
    state: dict = {"in_block": None, "block_content": [], "_pending": None}

    with open(trace_path, errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            m = LINE_RE.match(line)
            if m:
                ts, content = m.group(1), m.group(2)
            else:
                ts = None
                content = line.strip()

            event = classify_line(content, state)

            # Check for pending event from previous classification
            if state.get("_pending"):
                pending = state.pop("_pending")
                if ts:
                    pending["timestamp"] = ts
                pending["line"] = line_num
                if pending["type"] == "package_install":
                    packages.append(pending)
                elif pending["type"] == "metadata":
                    metadata[pending["key"]] = pending.get("value", "")
                else:
                    events.append(pending)

            if not event:
                continue

            if ts:
                event["timestamp"] = ts
            event["line"] = line_num

            if event["type"] == "package_install":
                packages.append(event)
            elif event["type"] == "metadata":
                metadata[event["key"]] = event.get("value", "")
            elif event["type"] == "cost_summary":
                pass  # skip — already captured via OTEL
            else:
                events.append(event)

    # Flush any remaining block
    final = _flush_block(state)
    if final:
        events.append(final)

    return {
        "events": events,
        "packages": packages,
        "metadata": metadata,
        "event_counts": _count_types(events),
        "package_count": len(packages),
    }


def _count_types(events: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in events:
        t = e["type"]
        counts[t] = counts.get(t, 0) + 1
    return counts


def find_traces(slug: str | None = None) -> list[tuple[str, str, str, Path]]:
    """Find job-trace.log files. Returns (slug, pipeline_id, job_dir_name, path)."""
    results = []
    search = ARTIFACTS / slug if slug else ARTIFACTS

    for trace_path in search.rglob("job-trace.log"):
        parts = trace_path.relative_to(ARTIFACTS).parts
        if len(parts) < 4 or parts[1] != "ci-jobs":
            continue
        pipeline_slug = parts[0]
        pipeline_id = parts[2]
        job_dir = parts[3]
        results.append((pipeline_slug, pipeline_id, job_dir, trace_path))

    return results


def main():
    parser = argparse.ArgumentParser(description="Parse job traces into structured JSON")
    parser.add_argument("slugs", nargs="*", help="Pipeline slug(s) (default: all)")
    parser.add_argument("--limit", type=int, default=0, help="Max traces per pipeline")
    args = parser.parse_args()

    if args.slugs:
        traces = []
        for s in args.slugs:
            traces.extend(find_traces(s))
    else:
        traces = find_traces()

    if args.limit > 0:
        by_slug: dict[str, list] = {}
        for t in traces:
            by_slug.setdefault(t[0], []).append(t)
        traces = []
        for slug_traces in by_slug.values():
            traces.extend(slug_traces[:args.limit])

    if not traces:
        log.error("No job-trace.log files found")
        sys.exit(1)

    log.info("Parsing %d trace files", len(traces))

    total_events = 0
    total_packages = 0

    for pipeline_slug, pipeline_id, job_dir, trace_path in traces:
        out_dir = TRACES / pipeline_slug / pipeline_id
        out_file = out_dir / f"{job_dir}.events.json"

        if out_file.exists():
            continue

        result = parse_trace(trace_path)

        out_dir.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(result, indent=2))

        total_events += len(result["events"])
        total_packages += result["package_count"]

        log.info(
            "[%s/%s] %d events, %d packages → %s",
            pipeline_slug, job_dir,
            len(result["events"]),
            result["package_count"],
            out_file.relative_to(ROOT),
        )

    log.info("Done. %d events, %d packages extracted.", total_events, total_packages)


if __name__ == "__main__":
    main()
