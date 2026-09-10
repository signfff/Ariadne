"""FastAPI application.

Replaces the old stdlib `corecoder.web` server.  Two things it does that the
old one could not: stream the agent token by token over SSE, and report the
real error when a model call fails instead of hiding it behind a fallback.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from corecoder import __version__
from corecoder.config import Config

from . import overview as overview_mod
from . import projects
from .agent_stream import build_agent, stream_agent
from .schemas import (
    ChatRequest,
    FileRequest,
    HealthResponse,
    IndexRequest,
    ProjectRequest,
    SearchRequest,
)

app = FastAPI(
    title="CoreCoder API",
    description="Read-only code-reading agent over a project folder.",
    version=__version__,
)

# the React dev server runs on another origin during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# in-memory sessions: session_id -> Agent (conversation history lives on the agent)
_SESSIONS: dict[str, object] = {}


@app.get("/api/health", response_model=HealthResponse)
def health():
    """Config the server actually resolved - the first place to look when a run fails."""
    import os

    config = Config.from_env()
    return HealthResponse(
        app="CoreCoder",
        version=__version__,
        cwd=os.getcwd(),
        profiles=["learn", "ask", "review"],
        runtime={
            "api_key_present": bool(config.api_key),
            "model": config.model,
            "base_url": config.base_url,
            "provider": config.provider,
        },
    )


@app.post("/api/project")
def open_project(req: ProjectRequest):
    """Scan a project folder and return its file listing plus stats."""
    try:
        root = projects.resolve_root(req.path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    files = projects.collect_files(root)
    return {
        "root": str(root),
        "files": files,
        "stats": projects.stats(files),
    }


@app.post("/api/file")
def read_file(req: FileRequest):
    """Read one project-relative text file."""
    try:
        root = projects.resolve_root(req.path)
        return projects.read_file(root, req.file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/overview")
def project_overview(req: ProjectRequest):
    """Structural read of the project: languages, entry points, what depends on what.

    Pure static analysis - no model call, so this works before a key is set.
    """
    try:
        root = projects.resolve_root(req.path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return overview_mod.build_overview(root)


@app.post("/api/index")
def build_project_index(req: IndexRequest):
    """Build or refresh the semantic index. Runs locally - no API key, no cost."""
    from corecoder.rag import Embedder, EmbedderUnavailable, build_index, index_path, open_store

    try:
        root = projects.resolve_root(req.path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if req.rebuild and index_path(root).exists():
        index_path(root).unlink()

    try:
        embedder = Embedder()
        store = open_store(root, embedder)
    except EmbedderUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    try:
        stats = build_index(root, embedder, store)
    finally:
        store.close()

    return {
        "summary": stats.summary(),
        "files_scanned": stats.files_scanned,
        "files_indexed": stats.files_indexed,
        "total_chunks": stats.total_chunks,
        "model": embedder.model_name,
    }


@app.post("/api/search")
def search_project(req: SearchRequest):
    """Hybrid semantic + keyword search over the index."""
    from corecoder.rag import Embedder, EmbedderUnavailable, hybrid_search, index_path, open_store

    try:
        root = projects.resolve_root(req.path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not index_path(root).exists():
        raise HTTPException(status_code=409, detail="No index for this project yet. Build one first.")

    try:
        embedder = Embedder()
        store = open_store(root, embedder)
    except EmbedderUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    try:
        results = hybrid_search(store, embedder, req.query, top_k=req.top_k)
    finally:
        store.close()

    return {
        "query": req.query,
        "hits": [
            {
                "path": hit.path,
                "start_line": hit.start_line,
                "end_line": hit.end_line,
                "kind": hit.kind,
                "name": hit.name,
                "text": hit.text,
                "score": score,
                "arms": sorted(set(arms)),
            }
            for hit, score, arms in results
        ],
    }


@app.post("/api/chat")
def chat(req: ChatRequest):
    """Run the agent and stream the whole run back as server-sent events.

    Event types: token, tool_start, tool_result, done, error.
    """
    try:
        root = projects.resolve_root(req.path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    agent = _SESSIONS.get(req.session_id) if req.session_id else None
    if req.session_id and agent is None:
        try:
            agent, _ = build_agent(req.profile)
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        _SESSIONS[req.session_id] = agent

    def event_source():
        for event in stream_agent(root, req.profile, req.message, agent=agent):
            yield f"event: {event.type}\ndata: {json.dumps(event.data, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # stop nginx buffering the stream
        },
    )


# Serving the built client from the API process gives one command and one
# origin - the shape you would actually deploy, and the one to demo from.
# In development Vite serves the client instead, with hot reload, and proxies
# /api back here. Mounted last so it never shadows an API route.
WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"

if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="ui")
else:

    @app.get("/")
    def missing_ui():
        return {
            "message": "API is running, but the client has not been built.",
            "build": "cd web && npm install && npm run build",
            "dev": "cd web && npm run dev  (then open http://127.0.0.1:5173)",
            "docs": "/docs",
        }


def main():
    """Entry point for `corecoder-server`."""
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(prog="corecoder-server", description="Run the CoreCoder API server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes")
    args = parser.parse_args()

    uvicorn.run("server.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
