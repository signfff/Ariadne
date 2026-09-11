"""Tests for core modules: config, context, session, imports."""

from ariadne_code import ALL_TOOLS, LLM, PROFILES, Agent, Config, __version__, tools_for_profile
from ariadne_code import session as session_module
from ariadne_code.context import ContextManager, estimate_tokens
from ariadne_code.session import list_sessions, load_session, save_session
from ariadne_code.tools import get_tool


def test_version():
    assert __version__ == "0.4.0"


def test_public_api_exports():
    """Users should be able to import key classes from the top-level package."""
    assert Agent is not None
    assert LLM is not None
    assert Config is not None
    assert len(ALL_TOOLS) == 8
    assert "review" in PROFILES


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("ARIADNE_MODEL", "test-model")
    c = Config.from_env()
    assert c.model == "test-model"


def test_config_defaults(monkeypatch):
    # clear relevant env vars without leaking the change into other tests
    monkeypatch.delenv("ARIADNE_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("ARIADNE_MAX_TOKENS", raising=False)

    c = Config.from_env()
    assert c.model == "gpt-5.5"
    assert c.max_tokens == 4096
    assert c.temperature == 0.0


def test_config_accepts_anthropic_style_env(monkeypatch):
    monkeypatch.delenv("ARIADNE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ARIADNE_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("ARIADNE_BASE_URL", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-test")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic")
    monkeypatch.setenv("ANTHROPIC_MODEL", "deepseek-v4-pro[1m]")

    c = Config.from_env()

    assert c.api_key == "sk-test"
    assert c.base_url == "https://api.deepseek.com"
    assert c.model == "deepseek-v4-pro[1m]"


def test_ariadne_env_takes_priority_over_anthropic_env(monkeypatch):
    monkeypatch.setenv("ARIADNE_API_KEY", "core-key")
    monkeypatch.setenv("ARIADNE_BASE_URL", "https://core.example/v1")
    monkeypatch.setenv("ARIADNE_MODEL", "core-model")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "anthropic-key")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic")
    monkeypatch.setenv("ANTHROPIC_MODEL", "anthropic-model")

    c = Config.from_env()

    assert c.api_key == "core-key"
    assert c.base_url == "https://core.example/v1"
    assert c.model == "core-model"


# --- Context ---

def test_estimate_tokens():
    msgs = [{"role": "user", "content": "hello world"}]
    t = estimate_tokens(msgs)
    assert t > 0
    assert t < 100


def test_context_snip():
    ctx = ContextManager(max_tokens=3000)
    msgs = [
        {"role": "tool", "tool_call_id": "t1", "content": "x\n" * 1000},
    ]
    before = estimate_tokens(msgs)
    ctx._snip_tool_outputs(msgs)
    after = estimate_tokens(msgs)
    assert after < before


def test_context_compress():
    ctx = ContextManager(max_tokens=2000)
    msgs = []
    for i in range(20):
        msgs.append({"role": "user", "content": f"msg {i} " + "a" * 200})
        msgs.append({"role": "tool", "tool_call_id": f"t{i}", "content": "b" * 2000})
    before = estimate_tokens(msgs)
    ctx.maybe_compress(msgs, None)
    after = estimate_tokens(msgs)
    assert after < before
    assert len(msgs) < 40  # should be compressed


def test_safe_split_never_orphans_a_tool_message():
    """The kept tail must not begin with a 'tool' message - it would be severed
    from the assistant tool_calls that produced it, which the API rejects."""
    ctx = ContextManager(max_tokens=1000)
    messages = [
        {"role": "user", "content": "do it"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]},
        {"role": "tool", "tool_call_id": "c1", "content": "result"},
        {"role": "tool", "tool_call_id": "c2", "content": "result2"},
    ]
    split = ctx._safe_split(messages, keep_recent=1)
    assert messages[split].get("role") != "tool"


def test_compress_never_leaves_an_orphan_tool_reply():
    """After summarisation every tool reply must still follow its tool_calls."""
    ctx = ContextManager(max_tokens=2000)
    msgs = []
    for i in range(20):
        msgs.append({"role": "user", "content": f"msg {i} " + "a" * 200})
        msgs.append({"role": "assistant", "content": None, "tool_calls": [{"id": f"c{i}"}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": "b" * 800})
    ctx.maybe_compress(msgs, None)
    for i, m in enumerate(msgs):
        if m.get("role") == "tool":
            prev = msgs[i - 1]
            assert prev.get("role") == "tool" or prev.get("tool_calls"), f"orphan tool at {i}"


# --- Session ---

def test_session_save_load(tmp_path, monkeypatch):
    monkeypatch.setattr(session_module, "SESSIONS_DIR", tmp_path)
    msgs = [{"role": "user", "content": "test message"}]
    save_session(msgs, "test-model", "pytest_test_session")
    loaded = load_session("pytest_test_session")
    assert loaded is not None
    assert loaded[0] == msgs
    assert loaded[1] == "test-model"


def test_session_name_is_sanitized(tmp_path, monkeypatch):
    monkeypatch.setattr(session_module, "SESSIONS_DIR", tmp_path)
    msgs = [{"role": "user", "content": "test message"}]
    sid = save_session(msgs, "test-model", "../Research Notes!")

    assert sid == "Research-Notes"
    assert (tmp_path / "Research-Notes.json").exists()
    assert load_session("../Research Notes!") is not None


def test_session_not_found():
    assert load_session("nonexistent_session_id") is None


def test_list_sessions():
    sessions = list_sessions()
    assert isinstance(sessions, list)


# --- Cost estimation ---

def test_cost_estimation_known_model():
    from ariadne_code.llm import LLM
    llm = LLM.__new__(LLM)
    llm.model = "gpt-5.4"
    llm.total_prompt_tokens = 1_000_000
    llm.total_completion_tokens = 500_000
    cost = llm.estimated_cost
    assert cost is not None
    assert cost == 2.5 + 7.5  # $2.5/M in + $15/M out * 0.5M

def test_cost_estimation_unknown_model():
    from ariadne_code.llm import LLM
    llm = LLM.__new__(LLM)
    llm.model = "some-custom-model"
    llm.total_prompt_tokens = 1000
    llm.total_completion_tokens = 500
    assert llm.estimated_cost is None


# --- Changed files tracking ---

def test_edit_tracks_changed_files(tmp_path):
    from ariadne_code.tools.edit import _changed_files
    _changed_files.clear()
    edit = get_tool("edit_file")
    path = tmp_path / "sample.py"
    path.write_text("aaa\nbbb\n")
    edit.execute(file_path=str(path), old_string="aaa", new_string="zzz")
    assert any(str(path) in p for p in _changed_files)
    _changed_files.clear()


def test_write_tracks_changed_files(tmp_path):
    from ariadne_code.tools.edit import _changed_files
    _changed_files.clear()
    write = get_tool("write_file")
    path = tmp_path / "tracked.txt"
    write.execute(file_path=str(path), content="tracked\n")
    assert any(path.name in p for p in _changed_files)
    _changed_files.clear()


# --- Agent tool execution ---

def test_agent_tool_scope_is_per_instance():
    """An Agent restricted to a subset of tools must not resolve tools outside it."""
    only_read = [get_tool("read_file")]
    agent = Agent(llm=LLM.__new__(LLM), tools=only_read)
    assert set(agent._tool_by_name) == {"read_file"}

    class _TC:
        name = "bash"  # a real, registered tool - but not in this agent's set
        id = "x"
        arguments = {"command": "echo hi"}

    assert "unknown tool 'bash'" in agent._exec_tool(_TC())


def test_read_only_profiles_expose_only_search_and_read_tools():
    for profile in ("ask", "review"):
        tools = tools_for_profile(profile)
        assert [t.name for t in tools] == ["read_file", "glob", "grep", "search_code"]


def test_full_profile_exposes_all_tools():
    assert [t.name for t in tools_for_profile("full")] == [t.name for t in ALL_TOOLS]


def test_exec_tool_distinguishes_bad_args_from_internal_error():
    """A TypeError raised inside a tool must not be reported as bad arguments."""
    from ariadne_code.tools.base import Tool

    class _Boom(Tool):
        name = "boom"
        description = "raises TypeError internally"
        parameters = {"type": "object", "properties": {}, "required": []}

        def execute(self):
            raise TypeError("internal explosion")

    agent = Agent(llm=LLM.__new__(LLM), tools=[_Boom()])

    class _BadArgs:
        name, id, arguments = "boom", "1", {"unexpected": 1}

    class _Good:
        name, id, arguments = "boom", "2", {}

    assert "bad arguments" in agent._exec_tool(_BadArgs())
    assert "Error executing boom" in agent._exec_tool(_Good())
    assert "bad arguments" not in agent._exec_tool(_Good())


def test_interrupt_backfills_missing_tool_replies():
    """A half-finished tool round must be repaired so history stays valid."""
    agent = Agent(llm=LLM.__new__(LLM), tools=[])
    agent.messages = [
        {"role": "assistant", "content": None, "tool_calls": [{"id": "a"}, {"id": "b"}]},
        {"role": "tool", "tool_call_id": "a", "content": "done"},
    ]

    class _TC:
        def __init__(self, i):
            self.id = i

    agent._answer_pending_tool_calls([_TC("a"), _TC("b")])
    replies = [m for m in agent.messages if m.get("role") == "tool"]
    ids = [m["tool_call_id"] for m in replies]
    assert sorted(ids) == ["a", "b"]
    assert ids.count("a") == 1  # the already-answered call wasn't duplicated


def test_dev_extra_points_at_this_package():
    """The dev extra self-references by name; a rename must update it.

    When it drifts, pip happily installs whatever unrelated project owns that
    name on PyPI and the missing extras only surface as ImportErrors in CI.
    """
    from pathlib import Path

    import pytest

    # tomllib is stdlib only from 3.11, and this project supports 3.10. The
    # check does not depend on the interpreter, so skipping on 3.10 loses
    # nothing - the other four versions still guard it.
    tomllib = pytest.importorskip("tomllib", reason="stdlib tomllib needs Python 3.11+")

    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )
    name = pyproject["project"]["name"]
    extras = pyproject["project"]["optional-dependencies"]

    referenced = [d for d in extras["dev"] if d.startswith(f"{name}[")]
    assert referenced, f"dev extra must self-reference '{name}', got {extras['dev']}"

    # and every extra it pulls in must exist
    for extra in referenced[0].split("[", 1)[1].rstrip("]").split(","):
        assert extra.strip() in extras, f"dev references unknown extra '{extra}'"
