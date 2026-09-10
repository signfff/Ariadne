"""Split a project into retrievable chunks.

Fixed-size windows cut through the middle of functions, which produces hits
that start halfway into a body and read as noise.  Python files are therefore
split along their syntax tree - one chunk per function or class - so every hit
is a complete, quotable unit with a real name and line range.  Other languages
fall back to overlapping line windows until a parser exists for them.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

WINDOW_LINES = 60
WINDOW_OVERLAP = 15
MAX_CHUNK_LINES = 200
MAX_FILE_BYTES = 512_000

# generated files: thousands of lines that match every query and mean nothing
SKIP_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock"}
SKIP_SUFFIXES = (".min.js", ".min.css", ".bundle.js", ".map")

SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".tox",
    "dist", "build", ".pytest_cache", ".ruff_cache", ".mypy_cache",
    ".idea", ".next", "target", ".corecoder_index", ".claude", ".vscode",
}

INDEXABLE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".rb",
    ".php", ".kt", ".cs", ".c", ".h", ".cpp", ".hpp", ".sh", ".sql",
    ".md", ".rst", ".txt", ".toml", ".yaml", ".yml", ".json", ".css", ".vue",
}


@dataclass
class Chunk:
    """One retrievable unit of a project."""

    path: str            # project-relative, forward slashes
    start_line: int      # 1-based, inclusive
    end_line: int        # 1-based, inclusive
    kind: str            # "function" | "class" | "module" | "window"
    name: str            # symbol name, or the file name for windows
    text: str
    tokens: int = field(default=0)

    @property
    def location(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"

    def for_embedding(self) -> str:
        """Build the text the embedder actually sees.

        Embedding the raw body works badly, and measurably so: the model caps at
        512 tokens, so most of a long function is cut off anyway, and a Chinese
        sentence model cannot tell one block of code from another - every chunk
        in this repo scored within 0.19 of every other, which is noise.

        What the model can match is prose. The card therefore keeps the parts a
        human wrote - identifiers, docstring, comments, signatures - and drops
        the rest of the body, which stays in `text` for display.
        """
        parts = [
            f"{self.path} {self.kind} {self.name}",
            _humanise(self.name),
            _prose_lines(self.text),
            _signature_lines(self.text),
        ]
        return "\n".join(p for p in parts if p)[:2000]


_DOC_MARKS = ('"""', "'''")


def _humanise(name: str) -> str:
    """Split snake_case and CamelCase so identifiers read as words."""
    import re

    words = re.split(r"[._]|(?<=[a-z0-9])(?=[A-Z])", name)
    return " ".join(w.lower() for w in words if w)


def _prose_lines(text: str, limit: int = 14) -> str:
    """Pull out docstrings and comments - the human-written half of a chunk."""
    out: list[str] = []
    in_doc = False

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        if in_doc:
            out.append(line.strip('"\'' ))
            if line.endswith(_DOC_MARKS):
                in_doc = False
        elif line.startswith(_DOC_MARKS):
            body = line[3:]
            if body.endswith(_DOC_MARKS):
                out.append(body[:-3])
            else:
                out.append(body)
                in_doc = True
        elif line.startswith(("#", "//")):
            out.append(line.lstrip("#/ ").strip())

        if len(out) >= limit:
            break

    return " ".join(o for o in out if o)


def _signature_lines(text: str, limit: int = 6) -> str:
    """Keep def/class/export lines so the shape of the code stays searchable."""
    keys = ("def ", "class ", "async def ", "function ", "export ", "const ", "@app.")
    out = [ln.strip() for ln in text.splitlines() if ln.strip().startswith(keys)]
    return " ".join(out[:limit])


def chunk_project(root: Path, limit: int | None = None) -> list[Chunk]:
    """Walk a project and chunk every indexable file."""
    chunks: list[Chunk] = []
    for path in sorted(root.rglob("*")):
        rel_parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if not is_indexable(path):
            continue

        chunks.extend(chunk_file(path, "/".join(rel_parts)))
        if limit and len(chunks) >= limit:
            break
    return chunks


def is_indexable(path: Path) -> bool:
    """One filter shared by the chunker and the indexer, so they never disagree."""
    if not path.is_file() or path.suffix.lower() not in INDEXABLE_EXTS:
        return False
    if path.name in SKIP_NAMES or path.name.endswith(SKIP_SUFFIXES):
        return False
    try:
        return path.stat().st_size <= MAX_FILE_BYTES
    except OSError:
        return False


def chunk_file(path: Path, rel: str) -> list[Chunk]:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if not source.strip():
        return []

    if path.suffix.lower() == ".py":
        parsed = _chunk_python(source, rel)
        if parsed is not None:
            return parsed
    return _chunk_windows(source, rel, path.name)


def _chunk_python(source: str, rel: str) -> list[Chunk] | None:
    """Chunk by top-level def/class. Returns None if the file does not parse."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    lines = source.splitlines()
    chunks: list[Chunk] = []
    covered: set[int] = set()

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue

        start = min(node.lineno, *(d.lineno for d in node.decorator_list)) if node.decorator_list else node.lineno
        end = node.end_lineno or start

        if isinstance(node, ast.ClassDef) and end - start + 1 > MAX_CHUNK_LINES:
            # a large class becomes one chunk per method, so a hit points at the
            # method rather than a few hundred lines of unrelated siblings
            chunks.extend(_split_class(node, lines, rel))
            covered.update(range(start, end + 1))
            continue

        kind = "class" if isinstance(node, ast.ClassDef) else "function"
        chunks.append(_make(rel, start, end, kind, node.name, lines))
        covered.update(range(start, end + 1))

    # whatever sits outside any def/class - imports, constants, __main__ blocks.
    # These are emitted per contiguous run: taking first..last as one span would
    # swallow every function in between and re-index the whole file.
    chunks.extend(_uncovered_runs(lines, covered, rel))
    return chunks or None


def _uncovered_runs(lines: list[str], covered: set[int], rel: str) -> list[Chunk]:
    """Chunk each contiguous stretch of lines no def/class claimed."""
    out: list[Chunk] = []
    run: list[int] = []

    for i in range(1, len(lines) + 2):
        if i <= len(lines) and i not in covered:
            run.append(i)
            continue
        if run:
            out.extend(_emit_run(run, lines, rel))
            run = []
    return out


def _emit_run(run: list[int], lines: list[str], rel: str) -> list[Chunk]:
    while run and not lines[run[0] - 1].strip():
        run.pop(0)
    while run and not lines[run[-1] - 1].strip():
        run.pop()
    if not run:
        return []

    name = Path(rel).name
    start, end = run[0], run[-1]
    if end - start + 1 <= MAX_CHUNK_LINES:
        return [_make(rel, start, end, "module", name, lines)]

    # a long run (a big __main__ block, a wall of constants) becomes windows
    out = []
    step = max(1, WINDOW_LINES - WINDOW_OVERLAP)
    for begin in range(start, end + 1, step):
        stop = min(begin + WINDOW_LINES - 1, end)
        if any(lines[i - 1].strip() for i in range(begin, stop + 1)):
            out.append(_make(rel, begin, stop, "module", name, lines))
        if stop == end:
            break
    return out


def _split_class(node: ast.ClassDef, lines: list[str], rel: str) -> list[Chunk]:
    out: list[Chunk] = []
    methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

    header_end = methods[0].lineno - 1 if methods else (node.end_lineno or node.lineno)
    if header_end >= node.lineno:
        out.append(_make(rel, node.lineno, header_end, "class", node.name, lines))

    for m in methods:
        start = min(m.lineno, *(d.lineno for d in m.decorator_list)) if m.decorator_list else m.lineno
        out.append(_make(rel, start, m.end_lineno or start, "function", f"{node.name}.{m.name}", lines))
    return out


def _chunk_windows(source: str, rel: str, name: str) -> list[Chunk]:
    """Overlapping line windows, for files we cannot parse."""
    lines = source.splitlines()
    if not lines:
        return []

    chunks: list[Chunk] = []
    step = max(1, WINDOW_LINES - WINDOW_OVERLAP)
    for start in range(0, len(lines), step):
        end = min(start + WINDOW_LINES, len(lines))
        if not any(line.strip() for line in lines[start:end]):
            continue
        chunks.append(_make(rel, start + 1, end, "window", name, lines))
        if end == len(lines):
            break
    return chunks


def _make(rel: str, start: int, end: int, kind: str, name: str, lines: list[str]) -> Chunk:
    end = min(end, len(lines))
    body = "\n".join(lines[start - 1 : end])
    if end - start + 1 > MAX_CHUNK_LINES:
        body = "\n".join(lines[start - 1 : start - 1 + MAX_CHUNK_LINES]) + "\n... (truncated)"
    return Chunk(
        path=rel,
        start_line=start,
        end_line=end,
        kind=kind,
        name=name,
        text=body,
        tokens=len(body) // 3,
    )
