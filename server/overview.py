"""Structural overview of a project, computed without an LLM.

Everything here is derived from the files themselves, so it is instant, free,
and works before an API key is configured. It answers the questions someone
opening an unfamiliar repository asks first:

  - what is this written in
  - where does execution start
  - which modules is everything else built on
  - in what order should I read it

The load-bearing part is the import graph. A module's in-degree - how many
other modules import it - is a far better guide to what matters than file size
or commit counts: the thing everything depends on is the thing you have to
understand first.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .projects import SKIP_DIRS

# files that mark a starting point, most specific first
ENTRY_NAMES = (
    "__main__.py", "main.py", "app.py", "cli.py", "manage.py", "wsgi.py", "asgi.py",
    "index.js", "index.ts", "main.js", "main.jsx", "main.ts", "main.tsx",
    "Application.java", "server.js",
)

CONFIG_NAMES = (
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "package.json",
    "pom.xml", "build.gradle", "Cargo.toml", "go.mod", "composer.json", "Gemfile",
    "Dockerfile", "docker-compose.yml", "Makefile",
)

DOC_NAMES = ("README.md", "README.rst", "README.txt", "README_CN.md", "CONTRIBUTING.md", "ARCHITECTURE.md")

PY = ".py"
JS_EXTS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".vue")

_JS_IMPORT = re.compile(
    r"""(?:^|\s)(?:import\s[^'"]*?from\s*|import\s*|require\s*\(\s*|export\s[^'"]*?from\s*)['"]([^'"]+)['"]""",
    re.MULTILINE,
)

LANGUAGE_BY_EXT = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".vue": "Vue", ".java": "Java",
    ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP", ".cs": "C#",
    ".c": "C", ".h": "C", ".cpp": "C++", ".hpp": "C++", ".kt": "Kotlin",
    ".css": "CSS", ".html": "HTML", ".sql": "SQL", ".sh": "Shell",
    ".md": "Markdown", ".json": "JSON", ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML",
}

MAX_SOURCE_BYTES = 512_000


@dataclass
class ModuleInfo:
    path: str
    language: str
    lines: int = 0
    defs: int = 0
    imported_by: set[str] = field(default_factory=set)
    imports: set[str] = field(default_factory=set)
    summary: str = ""


def build_overview(root: Path) -> dict:
    """Everything the overview panel needs, in one pass over the project."""
    modules = _scan(root)
    _link_imports(modules)

    ranked = sorted(
        modules.values(),
        key=lambda m: (-len(m.imported_by), -m.defs, m.path),
    )
    core = [m for m in ranked if m.imported_by][:8]
    entries = _entry_points(root, modules)

    return {
        "languages": _languages(modules),
        "totals": {
            "files": len(modules),
            "lines": sum(m.lines for m in modules.values()),
            "definitions": sum(m.defs for m in modules.values()),
        },
        "entry_points": [_module_row(modules[p]) for p in entries if p in modules],
        "core_modules": [_module_row(m) for m in core],
        "largest": [
            _module_row(m)
            for m in sorted(modules.values(), key=lambda m: -m.lines)[:6]
        ],
        "reading_route": _reading_route(root, modules, entries, core),
        "orphans": [
            m.path for m in ranked
            if not m.imported_by and not m.imports and m.language in ("Python", "JavaScript", "TypeScript")
        ][:6],
    }


# ---- scanning -----------------------------------------------------------

def _scan(root: Path) -> dict[str, ModuleInfo]:
    modules: dict[str, ModuleInfo] = {}

    for path in sorted(root.rglob("*")):
        rel_parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if not path.is_file():
            continue

        ext = path.suffix.lower()
        language = LANGUAGE_BY_EXT.get(ext)
        if not language:
            continue
        try:
            if path.stat().st_size > MAX_SOURCE_BYTES:
                continue
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        rel = "/".join(rel_parts)
        info = ModuleInfo(path=rel, language=language, lines=source.count("\n") + 1)

        if ext == PY:
            _read_python(source, info)
        elif ext in JS_EXTS:
            _read_js(source, info)

        modules[rel] = info

    return modules


def _read_python(source: str, info: ModuleInfo) -> None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return

    info.summary = (ast.get_docstring(tree) or "").strip().split("\n")[0]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            info.defs += 1

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                info.imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            # level>0 is a relative import; record it with dots so the resolver
            # can walk up from this module's own package
            prefix = "." * node.level
            info.imports.add(prefix + (node.module or ""))


def _read_js(source: str, info: ModuleInfo) -> None:
    info.defs = len(re.findall(r"\b(?:function|class|const\s+\w+\s*=\s*\(|=>)", source))
    for match in _JS_IMPORT.finditer(source):
        info.imports.add(match.group(1))


# ---- import graph -------------------------------------------------------

def _link_imports(modules: dict[str, ModuleInfo]) -> None:
    """Resolve each import to another file in the project, ignoring third parties."""
    by_module_path = {_as_module(p): p for p in modules}

    for path, info in modules.items():
        for raw in info.imports:
            target = (
                _resolve_relative(path, raw, modules)
                if raw.startswith(".")
                else _resolve_absolute(raw, by_module_path, modules)
            )
            if target and target != path:
                modules[target].imported_by.add(path)


def _as_module(path: str) -> str:
    stem = path[:-3] if path.endswith(PY) else path
    if stem.endswith("/__init__"):
        stem = stem[: -len("/__init__")]
    return stem.replace("/", ".")


def _resolve_absolute(name: str, by_module_path: dict[str, str], modules: dict[str, ModuleInfo]) -> str | None:
    # walk from the most specific prefix down, so a.b.c matches a/b/c.py before a/b.py
    parts = name.split(".")
    for cut in range(len(parts), 0, -1):
        candidate = ".".join(parts[:cut])
        if candidate in by_module_path:
            return by_module_path[candidate]
    return None


def _resolve_relative(source_path: str, raw: str, modules: dict[str, ModuleInfo]) -> str | None:
    level = len(raw) - len(raw.lstrip("."))
    tail = raw.lstrip(".")

    base = source_path.rsplit("/", 1)[0] if "/" in source_path else ""
    for _ in range(level - 1):
        base = base.rsplit("/", 1)[0] if "/" in base else ""

    stem = f"{base}/{tail.replace('.', '/')}" if tail else base
    stem = stem.lstrip("/")

    for candidate in (f"{stem}.py", f"{stem}/__init__.py"):
        if candidate in modules:
            return candidate
    return None


# ---- derived views ------------------------------------------------------

def _languages(modules: dict[str, ModuleInfo]) -> list[dict]:
    lines: dict[str, int] = defaultdict(int)
    files: dict[str, int] = defaultdict(int)
    for m in modules.values():
        lines[m.language] += m.lines
        files[m.language] += 1

    total = sum(lines.values()) or 1
    rows = [
        {"language": lang, "lines": n, "files": files[lang], "percent": round(n * 100 / total, 1)}
        for lang, n in lines.items()
    ]
    return sorted(rows, key=lambda r: -r["lines"])[:8]


def _entry_points(root: Path, modules: dict[str, ModuleInfo]) -> list[str]:
    found = [p for name in ENTRY_NAMES for p in modules if p.rsplit("/", 1)[-1] == name]

    # console_scripts in pyproject name the real entry points directly
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            text = pyproject.read_text(encoding="utf-8", errors="replace")
            block = re.search(r"\[project\.scripts\](.*?)(?:\n\[|\Z)", text, re.S)
            if block:
                for module in re.findall(r'=\s*"([\w.]+):', block.group(1)):
                    candidate = module.replace(".", "/") + ".py"
                    if candidate in modules and candidate not in found:
                        found.append(candidate)
        except OSError:
            pass

    seen: list[str] = []
    for p in found:
        if p not in seen:
            seen.append(p)
    return seen[:8]


def _reading_route(root: Path, modules: dict[str, ModuleInfo], entries: list[str],
                   core: list[ModuleInfo]) -> list[dict]:
    """An ordered path through the project: context, then entry, then core.

    Deliberately not the LLM's opinion - it is derived from what is on disk, so
    it costs nothing and cannot invent a file that does not exist.
    """
    route: list[dict] = []
    seen: set[str] = set()

    def add(path: str, why: str):
        if path in seen or path not in modules:
            return
        seen.add(path)
        route.append({
            "path": path,
            "why": why,
            "lines": modules[path].lines,
            "summary": modules[path].summary,
        })

    for name in DOC_NAMES:
        for path in modules:
            if path.rsplit("/", 1)[-1] == name:
                add(path, "先看项目自己的说明")

    for name in CONFIG_NAMES:
        for path in modules:
            if path.rsplit("/", 1)[-1] == name and path.count("/") == 0:
                add(path, "依赖和入口都写在这里")

    for path in entries:
        add(path, "程序从这里开始执行")

    for m in core:
        add(m.path, f"被 {len(m.imported_by)} 个模块依赖，是承重结构")

    return route[:12]


def _module_row(m: ModuleInfo) -> dict:
    return {
        "path": m.path,
        "language": m.language,
        "lines": m.lines,
        "definitions": m.defs,
        "imported_by": len(m.imported_by),
        "summary": m.summary,
    }
