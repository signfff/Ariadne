"""Tests for the FastAPI layer: routing, validation, and SSE wire format."""

import pytest
from fastapi.testclient import TestClient

from server import main as server_main
from server.agent_stream import Event


@pytest.fixture
def client():
    return TestClient(server_main.app)


def test_health_reports_resolved_config(client):
    body = client.get("/api/health").json()
    assert body["app"] == "CoreCoder"
    assert body["profiles"] == ["learn", "ask", "review"]
    assert set(body["runtime"]) == {"api_key_present", "model", "base_url", "provider"}


def test_project_rejects_missing_path(client):
    assert client.post("/api/project", json={"path": "D:/definitely/not/here"}).status_code == 400


def test_project_lists_files(client, tmp_path):
    (tmp_path / "a.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.js").write_text("x", encoding="utf-8")

    body = client.post("/api/project", json={"path": str(tmp_path)}).json()
    paths = [f["path"] for f in body["files"]]
    assert paths == ["a.py"]  # vendor dirs are skipped


def test_file_refuses_path_traversal(client, tmp_path):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    res = client.post("/api/file", json={"path": str(tmp_path), "file": "../../etc/passwd"})
    assert res.status_code == 400
    assert "outside the project" in res.json()["detail"]


def test_chat_validates_profile(client, tmp_path):
    res = client.post("/api/chat", json={"path": str(tmp_path), "message": "hi", "profile": "root"})
    assert res.status_code == 422


def test_chat_emits_sse_frames(client, tmp_path, monkeypatch):
    """Events must reach the wire as well-formed SSE, UTF-8 intact."""
    monkeypatch.setattr(
        server_main,
        "stream_agent",
        lambda *a, **kw: iter([
            Event("tool_start", {"name": "grep", "arguments": {"pattern": "def"}}),
            Event("tool_result", {"name": "grep", "preview": "命中 3 处", "size": 9}),
            Event("token", {"text": "入口在"}),
            Event("done", {"report": "入口在 cli.py", "usage": {"total_tokens": 5}}),
        ]),
    )

    res = client.post("/api/chat", json={"path": str(tmp_path), "message": "入口在哪"})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")

    frames = [f for f in res.text.split("\n\n") if f.strip()]
    assert len(frames) == 4
    assert frames[0].startswith("event: tool_start\ndata: ")
    assert frames[2] == 'event: token\ndata: {"text": "入口在"}'
    assert "入口在 cli.py" in frames[3]


def test_unknown_api_route_is_not_swallowed_by_the_ui_mount(client):
    """The SPA mount sits at '/', so it must not answer for missing API paths."""
    assert client.get("/api/nope").status_code == 404


def test_unknown_api_route_reports_404_for_every_verb(client):
    """The UI mount serves GET only, so a POST to a missing route used to 405."""
    for call in (client.get, client.post, client.put, client.delete):
        res = call("/api/definitely-not-a-route")
        assert res.status_code == 404, f"{call.__name__} returned {res.status_code}"
        assert "restart the server" in res.json()["detail"]


def test_real_api_routes_still_win_over_the_catch_all(client, tmp_path):
    assert client.post("/api/project", json={"path": str(tmp_path)}).status_code == 200
    assert client.post("/api/overview", json={"path": str(tmp_path)}).status_code == 200
