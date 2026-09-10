"""Tests for the SSE bridge: blocking Agent callbacks -> ordered event stream."""

from pathlib import Path

from ariadne_code.agent import Agent
from ariadne_code.llm import LLMResponse, ToolCall
from ariadne_code.tools.base import Tool
from server.agent_stream import stream_agent


class EchoTool(Tool):
    name = "echo"
    description = "Echo the text back."
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def execute(self, text: str) -> str:
        return f"echoed: {text}"


class ScriptedLLM:
    """Replays a fixed list of responses, streaming text through on_token."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.total_prompt_tokens = 11
        self.total_completion_tokens = 22
        self.estimated_cost = 0.5

    def chat(self, messages, tools=None, on_token=None):
        resp = self._responses.pop(0)
        if on_token and resp.content:
            for ch in resp.content:
                on_token(ch)
        return resp


def _agent(responses):
    llm = ScriptedLLM(responses)
    agent = Agent.__new__(Agent)  # skip __init__ so no real system prompt/LLM is built
    agent.llm = llm
    agent.tools = [EchoTool()]
    agent._tool_by_name = {"echo": agent.tools[0]}
    agent.messages = []
    agent.max_rounds = 5
    agent._system = "test"

    class NoCompress:
        max_tokens = 1000

        def maybe_compress(self, messages, llm=None):
            return False

    agent.context = NoCompress()
    return agent


def test_stream_emits_tool_and_token_events(tmp_path):
    agent = _agent([
        LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="echo", arguments={"text": "hi"})]),
        LLMResponse(content="done"),
    ])

    events = list(stream_agent(tmp_path, "learn", "run it", agent=agent))
    kinds = [e.type for e in events]

    assert kinds[0] == "tool_start"
    assert kinds[1] == "tool_result"
    assert "token" in kinds
    assert kinds[-1] == "done"

    assert events[0].data == {"name": "echo", "arguments": {"text": "hi"}}
    assert events[1].data["preview"] == "echoed: hi"

    text = "".join(e.data["text"] for e in events if e.type == "token")
    assert text == "done"


def test_stream_reports_usage_on_done(tmp_path):
    agent = _agent([LLMResponse(content="ok")])
    done = [e for e in stream_agent(tmp_path, "learn", "hi", agent=agent) if e.type == "done"]

    assert len(done) == 1
    assert done[0].data["report"] == "ok"
    assert done[0].data["usage"]["total_tokens"] == 33
    assert done[0].data["usage"]["cost_usd"] == 0.5


def test_stream_surfaces_errors_instead_of_hiding_them(tmp_path):
    class Boom:
        total_prompt_tokens = total_completion_tokens = 0
        estimated_cost = None

        def chat(self, *a, **kw):
            raise RuntimeError("provider said no")

    agent = _agent([])
    agent.llm = Boom()

    events = list(stream_agent(tmp_path, "learn", "hi", agent=agent))
    assert events[-1].type == "error"
    assert events[-1].data["message"] == "provider said no"
    assert events[-1].data["kind"] == "RuntimeError"


def test_stream_restores_cwd_after_run(tmp_path):
    import os

    before = os.getcwd()
    agent = _agent([LLMResponse(content="ok")])
    list(stream_agent(tmp_path, "learn", "hi", agent=agent))
    assert os.getcwd() == before


def test_stream_runs_agent_inside_project_root(tmp_path):
    """The agent must see the chosen project as its working directory."""
    seen = {}

    class CwdProbe(Tool):
        name = "echo"
        description = "Report cwd."
        parameters = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}

        def execute(self, text: str) -> str:
            import os

            seen["cwd"] = os.getcwd()
            return "ok"

    agent = _agent([
        LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="echo", arguments={"text": "x"})]),
        LLMResponse(content="fin"),
    ])
    agent.tools = [CwdProbe()]
    agent._tool_by_name = {"echo": agent.tools[0]}

    list(stream_agent(tmp_path, "learn", "hi", agent=agent))
    assert Path(seen["cwd"]).resolve() == tmp_path.resolve()
