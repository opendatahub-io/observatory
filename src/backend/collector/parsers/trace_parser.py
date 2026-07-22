"""Parse GitLab job traces into structured trace_events / trace_packages / trace_metadata."""

import re

import aiosqlite

_SECTION_START_RE = re.compile(r"section_start:\d+:(\S+)")
_SECTION_END_RE = re.compile(r"section_end:\d+:(\S+)")

_COMMAND_RE = re.compile(r"(?:^|\s)\$\s+(.+)$", re.MULTILINE)

_TOOL_CALL_RE = re.compile(
    r"\U0001f527\s+(\w+)\s+\$\s+(.+)$", re.MULTILINE
)

_PIP_INSTALL_RE = re.compile(
    r"Successfully installed\s+(.+)$", re.MULTILINE
)
_PIP_PKG_RE = re.compile(r"(\S+)-(\d[\w.]*)")

_DNF_PKG_RE = re.compile(
    r"^\s+(\S+)-(\d\S*)\s+(ubi-\S+|baseos|appstream|epel)\s+",
    re.MULTILINE,
)

_MICRODNF_PKG_RE = re.compile(
    r"Installing:\s+([^;\s]+);([^;]+);([^;]+);(\S+)"
)

_ERROR_RE = re.compile(
    r"\b(ERROR|FATAL|Traceback|Exception|panic:|FAILED)\b",
    re.IGNORECASE,
)

_EXIT_CODE_RE = re.compile(r"exit code (\d+)", re.IGNORECASE)

_IMAGE_RE = re.compile(
    r"Using docker image sha256:\w+ for (\S+) with digest (\S+)"
)

_RUNNER_RE = re.compile(r"Running with gitlab-runner ([\d.]+)")

_TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z)\s")

_LINE_PREFIX_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z\s+\S+\s+"
)


def _first_match(pattern: re.Pattern, text: str) -> str | None:
    m = pattern.search(text)
    return m.group(1) if m else None


def _strip_prefix(line: str) -> str:
    """Remove GitLab timestamp+stream prefix (e.g. '2026-06-24T03:08:34.383212Z 01O ')."""
    return _LINE_PREFIX_RE.sub("", line)


async def parse_job_trace(db: aiosqlite.Connection, run_id: int, log_text: str) -> None:
    events: list[tuple] = []
    packages: list[tuple] = []
    metadata: dict[str, str] = {}

    lines = log_text.split("\n")

    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()
        content = _strip_prefix(stripped)

        # GitLab section markers
        m = _SECTION_START_RE.search(stripped)
        if m:
            section = m.group(1)
            ts = _first_match(_TIMESTAMP_RE, stripped)
            events.append((run_id, "job_trace", "section_start", ts, section, line_num))
            continue

        m = _SECTION_END_RE.search(stripped)
        if m:
            section = m.group(1)
            ts = _first_match(_TIMESTAMP_RE, stripped)
            events.append((run_id, "job_trace", "section_end", ts, section, line_num))
            continue

        # Claude Code tool calls (🔧 Bash $ ...)
        m = _TOOL_CALL_RE.search(content)
        if m:
            tool_name = m.group(1)
            tool_cmd = m.group(2).strip()
            ts = _first_match(_TIMESTAMP_RE, stripped)
            events.append((run_id, "job_trace", "tool_call", ts,
                           f"{tool_name}: {tool_cmd}", line_num))
            continue

        # Shell commands ($ ... after prefix stripping)
        m = _COMMAND_RE.search(content)
        if m:
            cmd = m.group(1).strip()
            ts = _first_match(_TIMESTAMP_RE, stripped)
            events.append((run_id, "job_trace", "command", ts, cmd, line_num))
            continue

        # Error lines
        if _ERROR_RE.search(content):
            ts = _first_match(_TIMESTAMP_RE, stripped)
            events.append((run_id, "job_trace", "error", ts, content[:2000], line_num))

    # pip packages from "Successfully installed ..." lines
    for m in _PIP_INSTALL_RE.finditer(log_text):
        for pkg_match in _PIP_PKG_RE.finditer(m.group(1)):
            packages.append((run_id, "pip", pkg_match.group(1), pkg_match.group(2), None, None))

    # dnf/microdnf packages (table format)
    for m in _DNF_PKG_RE.finditer(log_text):
        name_ver = m.group(1)
        name = re.sub(r"\.\w+$", "", name_ver) if "." in name_ver else name_ver
        packages.append((run_id, "dnf", name, m.group(2), None, m.group(3)))

    # microdnf packages (Installing: name;version;arch;repo)
    for m in _MICRODNF_PKG_RE.finditer(log_text):
        packages.append((run_id, "dnf", m.group(1), m.group(2), m.group(3), m.group(4)))

    # Metadata
    runner_ver = _first_match(_RUNNER_RE, log_text)
    if runner_ver:
        metadata["gitlab_runner_version"] = runner_ver

    img_match = _IMAGE_RE.search(log_text)
    if img_match:
        metadata["container_image"] = img_match.group(1)
        metadata["container_digest"] = img_match.group(2)

    exit_match = _EXIT_CODE_RE.search(log_text)
    if exit_match:
        metadata["exit_code"] = exit_match.group(1)

    # Write to database
    if events:
        await db.executemany(
            """INSERT INTO trace_events (pipeline_run_id, source, event_type, timestamp, content, line_number)
               VALUES (?, ?, ?, ?, ?, ?)""",
            events,
        )

    if packages:
        await db.executemany(
            """INSERT INTO trace_packages (pipeline_run_id, manager, name, version, arch, repo)
               VALUES (?, ?, ?, ?, ?, ?)""",
            packages,
        )

    if metadata:
        await db.executemany(
            """INSERT OR REPLACE INTO trace_metadata (pipeline_run_id, key, value)
               VALUES (?, ?, ?)""",
            [(run_id, k, v) for k, v in metadata.items()],
        )

    if events or packages or metadata:
        await db.commit()
