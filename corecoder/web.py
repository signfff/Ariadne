"""Full-stack web workspace for reading and reviewing codebases.

This deliberately uses only Python's standard library for the server so the
prototype can run anywhere CoreCoder already runs.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .agent import Agent
from .config import Config
from .llm import LLM, LiteLLM
from .profiles import get_profile, tools_for_profile


STATIC_DIR = Path(__file__).with_name("web_static")
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox", "dist", "build"}
TEXT_EXTS = {
    ".bat",
    ".cfg",
    ".css",
    ".csv",
    ".env",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".lock",
    ".md",
    ".py",
    ".rs",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


def main():
    parser = argparse.ArgumentParser(
        prog="corecoder-web",
        description="Launch the CoreCoder code-reading web UI.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind (default: 8765)")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), _Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"CoreCoder web UI running at {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        server.server_close()


class _Handler(BaseHTTPRequestHandler):
    server_version = "CoreCoderFullStack/0.2"

    def do_GET(self):  # noqa: N802 - stdlib handler API
        parsed = urlparse(self.path)
        if parsed.path in {"/api/config", "/api/health"}:
            config = Config.from_env()
            self._json({
                "app": "CoreCoder Full-Stack Workspace",
                "kind": "full-stack",
                "frontend": "corecoder/web_static/index.html",
                "backend": "corecoder.web",
                "cwd": os.getcwd(),
                "profiles": ["learn", "ask", "review"],
                "runtime": {
                    "api_key_present": bool(config.api_key),
                    "model": config.model,
                    "base_url": config.base_url,
                    "provider": config.provider,
                },
            })
            return

        rel = "index.html" if parsed.path in ("", "/") else unquote(parsed.path.lstrip("/"))
        target = (STATIC_DIR / rel).resolve()
        if not _is_within(target, STATIC_DIR) or not target.is_file():
            self.send_error(404)
            return

        data = target.read_bytes()
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):  # noqa: N802 - stdlib handler API
        routes = {
            "/api/pick-folder": self._pick_folder,
            "/api/open": self._open_project,
            "/api/file": self._read_file,
            "/api/analyze": self._analyze_project,
            "/api/teach": self._teach_project,
        }
        parsed = urlparse(self.path)
        handler = routes.get(parsed.path)
        if handler is None:
            self.send_error(404)
            return
        try:
            handler(self._body_json())
        except ValueError as e:
            self._json({"error": str(e)}, status=400)
        except Exception as e:  # keep UI failures readable during prototyping
            self._json({"error": f"{type(e).__name__}: {e}"}, status=500)

    def log_message(self, fmt, *args):
        return

    def _body_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("request body must be a JSON object")
        return data

    def _json(self, data: dict, status: int = 200):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _open_project(self, data: dict):
        root = _project_root(data)
        files = _collect_files(root)
        self._json(
            {
                "root": str(root),
                "name": root.name,
                "files": files,
                "stats": _stats(files),
            }
        )

    def _pick_folder(self, data: dict):
        start = data.get("path") if isinstance(data.get("path"), str) else os.getcwd()
        try:
            import tkinter as tk
            from tkinter import filedialog
        except Exception as e:
            raise ValueError(f"folder picker is unavailable: {e}") from e

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            selected = filedialog.askdirectory(initialdir=start, title="Open project folder")
        finally:
            root.destroy()
        if not selected:
            self._json({"path": ""})
            return
        self._json({"path": str(Path(selected).resolve())})

    def _read_file(self, data: dict):
        root = _project_root(data)
        rel = data.get("file")
        if not isinstance(rel, str) or not rel:
            raise ValueError("file is required")
        target = (root / rel).resolve()
        if not _is_within(target, root) or not target.is_file():
            raise ValueError("file is outside the project or does not exist")
        if target.stat().st_size > 512_000:
            raise ValueError("file is too large to preview")
        text = target.read_text(encoding="utf-8", errors="replace")
        self._json({"file": rel, "content": text})

    def _analyze_project(self, data: dict):
        root = _project_root(data)
        profile_name = _normalize_profile(data.get("profile", "learn"))

        report, tool_events, llm = _run_readonly_agent(root, profile_name, _analysis_prompt(root, profile_name))
        self._json(_agent_payload(report, tool_events, llm))

    def _teach_project(self, data: dict):
        root = _project_root(data)
        action = data.get("action", "guide")
        if action not in {"guide", "route", "file", "glossary", "quiz"}:
            raise ValueError("action must be 'guide', 'route', 'file', 'glossary', or 'quiz'")

        selected_file = data.get("file")
        if action == "file":
            if not isinstance(selected_file, str) or not selected_file:
                raise ValueError("file is required for file explanation")
            target = (root / selected_file).resolve()
            if not _is_within(target, root) or not target.is_file():
                raise ValueError("file is outside the project or does not exist")

        prompt = _teaching_prompt(root, action, selected_file if isinstance(selected_file, str) else None)
        try:
            report, tool_events, llm = _run_readonly_agent(root, "learn", prompt)
            payload = _agent_payload(report, tool_events, llm)
        except Exception as e:
            payload = _offline_teaching_payload(root, action, selected_file if isinstance(selected_file, str) else None, str(e))
        payload["action"] = action
        self._json(payload)


def _normalize_profile(profile_name) -> str:
    if not isinstance(profile_name, str) or not profile_name:
        return "learn"
    if profile_name == "review":
        # Keep old clients from failing, but route the web product toward teaching.
        return "learn"
    if profile_name not in {"learn", "ask"}:
        raise ValueError("profile must be 'learn' or 'ask'")
    return profile_name


def _run_readonly_agent(root: Path, profile_name: str, prompt: str):
    old_cwd = os.getcwd()
    os.chdir(root)
    try:
        config = Config.from_env()
        if not config.api_key:
            raise ValueError("No API key found. Set OPENAI_API_KEY, DEEPSEEK_API_KEY, or CORECODER_API_KEY.")

        llm_cls = LiteLLM if config.provider == "litellm" else LLM
        llm = llm_cls(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )
        profile = get_profile(profile_name)
        agent = Agent(
            llm=llm,
            tools=tools_for_profile(profile_name),
            max_context_tokens=config.max_context_tokens,
            profile_instructions=profile.instructions,
        )
        tool_events: list[dict] = []

        report = agent.chat(
            prompt,
            on_tool=lambda name, args: tool_events.append({"name": name, "arguments": args}),
        )
        return report, tool_events, llm
    finally:
        os.chdir(old_cwd)


def _agent_payload(report: str, tool_events: list[dict], llm) -> dict:
    return {
        "report": report,
        "tools": tool_events,
        "tokens": {
            "prompt": llm.total_prompt_tokens,
            "completion": llm.total_completion_tokens,
            "total": llm.total_prompt_tokens + llm.total_completion_tokens,
            "cost": llm.estimated_cost,
        },
    }


def _offline_teaching_payload(root: Path, action: str, selected_file: str | None, error: str) -> dict:
    files = _collect_files(root, limit=120)
    report = _offline_teaching_report(root, files, action, selected_file, error)
    return {
        "report": report,
        "tools": [],
        "offline": True,
        "error": error,
        "tokens": {"prompt": 0, "completion": 0, "total": 0, "cost": None},
    }


def _offline_teaching_report(root: Path, files: list[dict], action: str, selected_file: str | None, error: str) -> str:
    py_files = [f["path"] for f in files if f["path"].endswith(".py")]
    md_files = [f["path"] for f in files if f["path"].lower().endswith((".md", ".txt"))]
    config_files = [
        f["path"]
        for f in files
        if f["name"].lower() in {"pyproject.toml", "package.json", "requirements.txt", "dockerfile"}
        or f["path"].lower().endswith((".toml", ".yaml", ".yml", ".json"))
    ]
    test_files = [f["path"] for f in files if "test" in f["path"].lower()]
    entry_files = [
        f
        for f in py_files
        if f.endswith(("cli.py", "web.py", "__main__.py", "main.py", "app.py", "server.py"))
    ]

    if action == "route":
        return _zh(
            f"## 离线阅读路线\n\n"
            f"> 模型调用失败，已根据文件树生成基础路线。错误：`{error}`\n\n"
            f"### 5 分钟速览\n"
            f"- 先看说明文档：{_join_some(md_files)}\n"
            f"- 再看配置文件：{_join_some(config_files)}\n\n"
            f"### 30 分钟路线\n"
            f"- 入口文件：{_join_some(entry_files)}\n"
            f"- 核心 Python 文件：{_join_some(py_files)}\n"
            f"- 测试文件：{_join_some(test_files)}\n\n"
            f"### 2 小时深入\n"
            f"- 按入口到核心模块的顺序读：入口 -> 配置 -> 核心流程 -> 工具/服务 -> 测试。\n"
            f"- 每读一个模块，记录它负责什么、依赖谁、对外暴露什么。"
        )
    if action == "file" and selected_file:
        text = _read_preview(root / selected_file)
        return _zh(
            f"## 离线文件讲解：{selected_file}\n\n"
            f"> 模型调用失败，已生成基础讲解。错误：`{error}`\n\n"
            f"### 它在项目里的位置\n"
            f"- 路径：`{selected_file}`\n"
            f"- 类型：`{Path(selected_file).suffix or '(none)'}`\n\n"
            f"### 建议读法\n"
            f"- 先看文件顶部 import，判断它依赖哪些模块。\n"
            f"- 再找类、函数和入口分支，理解它对外提供什么能力。\n"
            f"- 最后回到测试文件里找它如何被验证。\n\n"
            f"### 文件开头预览\n"
            f"```text\n{text}\n```"
        )
    if action == "glossary":
        return _zh(
            f"## 离线概念词典\n\n"
            f"> 模型调用失败，已根据文件名生成基础词典。错误：`{error}`\n\n"
            f"- 入口：通常从 {_join_some(entry_files)} 开始，负责启动 CLI 或 Web 服务。\n"
            f"- 配置：通常在 {_join_some(config_files)}，负责依赖、脚本、环境变量或构建设置。\n"
            f"- 核心模块：通常在 {_join_some(py_files)}，负责主要业务逻辑。\n"
            f"- 测试：通常在 {_join_some(test_files)}，说明项目希望保证哪些行为。"
        )
    if action == "quiz":
        return _zh(
            f"## 离线练习题\n\n"
            f"> 模型调用失败，已根据文件树生成基础练习。错误：`{error}`\n\n"
            f"1. 找到项目入口文件，并说明它启动了哪些模块。\n"
            f"2. 找到配置文件，列出项目依赖和命令入口。\n"
            f"3. 选择一个核心文件，画出它调用了哪些本地模块。\n"
            f"4. 选择一个测试文件，说明它验证了哪个行为。\n"
            f"5. 小实践：写一段 5 行总结，解释这个项目的主流程。"
        )
    return _zh(
        f"## 离线项目总览\n\n"
        f"> 模型调用失败，已根据文件树生成基础导读。错误：`{error}`\n\n"
        f"### 项目位置\n"
        f"`{root}`\n\n"
        f"### 先读这些文件\n"
        f"- 说明文档：{_join_some(md_files)}\n"
        f"- 配置文件：{_join_some(config_files)}\n"
        f"- 入口文件：{_join_some(entry_files)}\n"
        f"- 测试文件：{_join_some(test_files)}\n\n"
        f"### 阅读建议\n"
        f"先从 README/配置建立项目边界，再从入口文件跟到核心模块，最后用测试文件校验自己的理解。"
    )


def _join_some(items: list[str], limit: int = 6) -> str:
    if not items:
        return "暂未识别"
    shown = [f"`{item}`" for item in items[:limit]]
    suffix = f" 等 {len(items)} 个" if len(items) > limit else ""
    return "、".join(shown) + suffix


def _read_preview(path: Path, limit: int = 1200) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError as e:
        return f"无法读取文件：{e}"


def _project_root(data: dict) -> Path:
    raw = data.get("path")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("path is required")
    root = Path(raw).expanduser().resolve()
    if not root.exists():
        raise ValueError(f"path does not exist: {raw}")
    if not root.is_dir():
        raise ValueError(f"path is not a directory: {raw}")
    return root


def _collect_files(root: Path, limit: int = 800) -> list[dict]:
    files = []
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
            continue
        rel = "/".join(rel_parts)
        files.append(
            {
                "path": rel,
                "name": path.name,
                "ext": path.suffix.lower() or "(none)",
                "size": size,
                "previewable": path.suffix.lower() in TEXT_EXTS and size <= 512_000,
            }
        )
        if len(files) >= limit:
            break
    files.sort(key=lambda f: f["path"].lower())
    return files


def _stats(files: list[dict]) -> dict:
    by_ext: dict[str, int] = {}
    total_size = 0
    for item in files:
        by_ext[item["ext"]] = by_ext.get(item["ext"], 0) + 1
        total_size += int(item["size"])
    top_exts = sorted(by_ext.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
    return {"file_count": len(files), "total_size": total_size, "top_exts": top_exts}


def _analysis_prompt(root: Path, profile: str) -> str:
    if profile == "learn":
        return _teaching_prompt(root, "guide", None)
    if profile == "review":
        return _zh(
            f"请审查这个项目，绝对路径是：{root}\n\n"
            "请先查看项目结构、README、配置文件、测试和主要入口文件，然后重点检查核心业务代码。"
            "这不是普通项目分析，请按代码审查方式输出，默认中文，不要使用英文小节标题。"
            "报告必须优先给出可执行的问题清单；每条问题包含：严重级别、位置、问题、影响、建议修复。"
            "位置要尽量具体到文件路径和行号；如果没有行号，请给出函数名、类名或唯一代码片段。"
            "保持只读，不要修改文件，不要运行写入性命令。"
        )
    return (
        _zh(f"请分析这个项目，绝对路径是：{root}\n\n")
        + _zh("请使用只读工具查看文件树、README、配置文件、测试和主要入口文件。")
        + _zh("然后用中文输出一份简洁的项目导读，包含：项目是什么、整体结构、主执行流程、重要文件、如何运行、建议阅读顺序。")
        + _zh("不要使用英文小节标题。")
    )


def _teaching_prompt(root: Path, action: str, selected_file: str | None) -> str:
    common = (
        _zh(f"项目绝对路径：{root}\n\n")
        + _zh("你是源码阅读老师，不是代码审查员。目标是帮助第一次接触项目的人读懂它。")
        + _zh("请默认使用中文，不要查 bug，不要输出审查报告，不要修改文件，不要运行命令。")
        + _zh("请使用只读工具查看必要文件，并引用具体文件路径作为依据。")
    )
    if action == "route":
        return (
            common
            + _zh("请生成一份分阶段阅读路线：先给 5 分钟速览，再给 30 分钟路线，再给 2 小时深入路线。")
            + _zh("每一步都说明要读哪个文件、为什么读、读完应该理解什么。")
        )
    if action == "file":
        return (
            common
            + _zh(f"请专门讲解这个文件：{selected_file}\n")
            + _zh("请说明它在项目里的位置、它依赖谁、谁会调用它、主要类/函数做什么、阅读时应该抓住哪几条线。")
            + _zh("不要逐行翻译，要像老师带读源码一样解释。")
        )
    if action == "glossary":
        return (
            common
            + _zh("请提炼这个项目的核心概念词典。")
            + _zh("每个概念包含：概念名、通俗解释、相关文件、为什么重要、读源码时如何识别它。")
        )
    if action == "quiz":
        return (
            common
            + _zh("请生成一组边读边练的学习题。")
            + _zh("题目要覆盖项目入口、核心流程、工具/模块职责、配置和测试。")
            + _zh("每题都给提示，但不要直接给完整答案；最后给一个小型实践任务。")
        )
    return (
        common
        + _zh("请输出一份适合学习的项目导读，包含：")
        + _zh("项目是做什么的、先读哪些文件以及为什么、目录结构怎么理解、主执行流程、核心概念词典、")
        + _zh("容易卡住的地方、30 分钟阅读路线、边读边思考的练习题。")
    )


def _zh(text: str) -> str:
    """Keep Chinese prompts visibly as UTF-8 in source."""
    return text


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    main()
