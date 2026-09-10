"""Project scanning and file reading.

Everything here is read-only and confined to the project root the caller
chose: `resolve_root` normalises the path, and `read_file` refuses anything
that escapes it.
"""

from __future__ import annotations

from pathlib import Path

SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".tox", "dist", "build", ".pytest_cache", ".ruff_cache",
    ".mypy_cache", ".idea", ".next", "target",
}

TEXT_EXTS = {
    ".bat", ".cfg", ".css", ".csv", ".env", ".go", ".gradle", ".html",
    ".ini", ".java", ".js", ".json", ".jsx", ".kt", ".lock", ".md",
    ".php", ".properties", ".py", ".rb", ".rs", ".sh", ".sql", ".toml",
    ".ts", ".tsx", ".txt", ".vue", ".xml", ".yaml", ".yml",
}

MAX_PREVIEW_BYTES = 512_000


def resolve_root(raw: str) -> Path:
    """Validate a user-supplied project path."""
    if not raw or not raw.strip():
        raise ValueError("path is required")
    root = Path(raw).expanduser().resolve()
    if not root.exists():
        raise ValueError(f"path does not exist: {raw}")
    if not root.is_dir():
        raise ValueError(f"path is not a directory: {raw}")
    return root


def is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def collect_files(root: Path, limit: int = 2000) -> list[dict]:
    """Walk the project, skipping build/vendor dirs. Sorted by path."""
    files: list[dict] = []
    truncated = False
    for path in root.rglob("*"):
        try:
            rel_parts = path.relative_to(root).parts
        except ValueError:
            continue
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if path.is_dir():
            continue
        try:
            size = path.stat().st_size
        except OSError:
            # unreadable entries (permissions, broken links) are skipped, not fatal
            continue
        ext = path.suffix.lower() or "(none)"
        files.append({
            "path": "/".join(rel_parts),
            "name": path.name,
            "ext": ext,
            "size": size,
            "previewable": ext in TEXT_EXTS and size <= MAX_PREVIEW_BYTES,
        })
        if len(files) >= limit:
            truncated = True
            break
    files.sort(key=lambda f: f["path"].lower())
    for f in files:
        f["truncated_listing"] = truncated
    return files


def stats(files: list[dict]) -> dict:
    by_ext: dict[str, int] = {}
    total_size = 0
    for item in files:
        by_ext[item["ext"]] = by_ext.get(item["ext"], 0) + 1
        total_size += int(item["size"])
    top_exts = sorted(by_ext.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
    return {
        "file_count": len(files),
        "total_size": total_size,
        "top_exts": [{"ext": e, "count": c} for e, c in top_exts],
    }


def read_file(root: Path, rel_path: str) -> dict:
    """Read one project-relative text file."""
    target = (root / rel_path).resolve()
    if not is_within(target, root):
        raise ValueError("file is outside the project")
    if not target.is_file():
        raise ValueError(f"not a file: {rel_path}")

    size = target.stat().st_size
    if size > MAX_PREVIEW_BYTES:
        raise ValueError(f"file too large to preview ({size} bytes)")

    text = target.read_text(encoding="utf-8", errors="replace")
    return {
        "path": rel_path,
        "size": size,
        "lines": text.count("\n") + 1,
        "content": text,
    }
