"""Parse Linux strace output files for common queries."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

_MAX_RESULTS = 500

_SYSCALL_RE = re.compile(
    r"^(?:\d+\s+)?"           # optional PID
    r"(?:[\d.]+\s+)?"         # optional timestamp
    r"(\w+)\("                # syscall name
    r"(.*)\)\s*=\s*(.+)$"     # args and return value
)

_OPENAT_PATH_RE = re.compile(r'"([^"]+)"')
_EXECVE_RE = re.compile(r'"([^"]+)",\s*\[([^\]]*)\]')
_CONNECT_ADDR_RE = re.compile(
    r"sin6?_port=htons\((\d+)\).*sin6?_addr=inet_(?:pton|addr)\([^\"]*\"([^\"]+)\""
    r"|sun_path=\"([^\"]+)\""
)


def parse_strace_path(
    path: Path, query: str, file_glob: str = "*"
) -> dict:
    if path.is_file():
        files = [path]
    elif path.is_dir():
        files = sorted(path.rglob(file_glob))
        if not files:
            files = sorted(path.rglob("*"))
            files = [f for f in files if f.is_file() and not f.name.startswith(".")]
    else:
        return {"error": f"Path not found: {path}"}

    results: dict = {"query": query, "source_files": len(files)}

    if query == "files_accessed":
        results.update(_collect_openat(files, read_only=True))
    elif query == "files_written":
        results.update(_collect_openat(files, read_only=False))
    elif query == "failed_opens":
        results.update(_collect_failed_opens(files))
    elif query == "execve":
        results.update(_collect_execve(files))
    elif query == "clone":
        results.update(_collect_clone(files))
    elif query == "network":
        results.update(_collect_network(files))
    elif query == "summary":
        results.update(_collect_summary(files))
    else:
        results["error"] = f"Unknown query type: {query}"

    return results


def _iter_syscalls(files: list[Path]):
    for f in files:
        try:
            with open(f, "r", errors="replace") as fh:
                for line in fh:
                    m = _SYSCALL_RE.match(line.strip())
                    if m:
                        yield m.group(1), m.group(2), m.group(3), line.strip()
        except Exception:
            continue


def _collect_openat(files: list[Path], read_only: bool) -> dict:
    seen: dict[str, str] = {}
    for syscall, args, ret, _raw in _iter_syscalls(files):
        if syscall != "openat":
            continue
        pm = _OPENAT_PATH_RE.search(args)
        if not pm:
            continue
        filepath = pm.group(1)
        if read_only:
            if "O_RDONLY" not in args:
                continue
        else:
            if not any(f in args for f in ("O_WRONLY", "O_RDWR", "O_CREAT")):
                continue
        if filepath in seen:
            continue
        status = "ok" if not ret.startswith("-1") else "failed"
        seen[filepath] = status
        if len(seen) >= _MAX_RESULTS:
            break

    entries = [{"path": p, "status": s} for p, s in sorted(seen.items())]
    return {"files": entries, "count": len(entries), "capped": len(seen) >= _MAX_RESULTS}


def _collect_failed_opens(files: list[Path]) -> dict:
    seen: dict[str, str] = {}
    for syscall, args, ret, _raw in _iter_syscalls(files):
        if syscall != "openat":
            continue
        if not ret.startswith("-1"):
            continue
        pm = _OPENAT_PATH_RE.search(args)
        if not pm:
            continue
        filepath = pm.group(1)
        if filepath in seen:
            continue
        err_match = re.search(r"(\w+)\s*\(", ret)
        err = err_match.group(1) if err_match else "unknown"
        seen[filepath] = err
        if len(seen) >= _MAX_RESULTS:
            break

    entries = [{"path": p, "error": e} for p, e in sorted(seen.items())]
    return {"files": entries, "count": len(entries), "capped": len(seen) >= _MAX_RESULTS}


def _collect_execve(files: list[Path]) -> dict:
    commands: list[dict] = []
    seen: set[str] = set()
    for syscall, args, ret, _raw in _iter_syscalls(files):
        if syscall != "execve":
            continue
        em = _EXECVE_RE.match(args)
        if not em:
            continue
        executable = em.group(1)
        argv_raw = em.group(2)
        argv = re.findall(r'"([^"]*)"', argv_raw)
        key = executable + " " + " ".join(argv[:3])
        if key in seen:
            continue
        seen.add(key)
        status = "ok" if ret.strip() == "0" else "failed"
        commands.append({
            "executable": executable,
            "argv": argv[:10],
            "status": status,
        })
        if len(commands) >= _MAX_RESULTS:
            break

    return {"commands": commands, "count": len(commands), "capped": len(commands) >= _MAX_RESULTS}


def _collect_clone(files: list[Path]) -> dict:
    clones: list[dict] = []
    for syscall, args, ret, _raw in _iter_syscalls(files):
        if syscall not in ("clone", "clone3"):
            continue
        child_pid = ret.strip().split()[0] if not ret.startswith("-1") else None
        flags = []
        for flag in re.findall(r"CLONE_\w+", args):
            flags.append(flag)
        entry = {"syscall": syscall, "flags": flags}
        if child_pid and child_pid.isdigit():
            entry["child_pid"] = int(child_pid)
        clones.append(entry)
        if len(clones) >= _MAX_RESULTS:
            break

    flag_counts = Counter()
    for c in clones:
        for f in c["flags"]:
            flag_counts[f] += 1

    return {
        "clones": clones[:100],
        "total": len(clones),
        "flag_summary": dict(flag_counts.most_common(20)),
        "capped": len(clones) >= _MAX_RESULTS,
    }


def _collect_network(files: list[Path]) -> dict:
    connections: list[dict] = []
    seen: set[str] = set()
    for syscall, args, ret, _raw in _iter_syscalls(files):
        if syscall != "connect":
            continue
        m = _CONNECT_ADDR_RE.search(args)
        if not m:
            continue
        if m.group(3):
            key = f"unix:{m.group(3)}"
            entry = {"type": "unix", "path": m.group(3)}
        else:
            port = m.group(1)
            addr = m.group(2)
            key = f"tcp:{addr}:{port}"
            entry = {"type": "tcp", "address": addr, "port": int(port)}
        if key in seen:
            continue
        seen.add(key)
        entry["status"] = "ok" if not ret.startswith("-1") else "failed"
        connections.append(entry)
        if len(connections) >= _MAX_RESULTS:
            break

    return {"connections": connections, "count": len(connections), "capped": len(connections) >= _MAX_RESULTS}


def _collect_summary(files: list[Path]) -> dict:
    counts: Counter = Counter()
    total_lines = 0
    for syscall, _args, _ret, _raw in _iter_syscalls(files):
        counts[syscall] += 1
        total_lines += 1

    return {
        "total_syscalls": total_lines,
        "syscall_counts": dict(counts.most_common(50)),
        "unique_syscalls": len(counts),
    }
