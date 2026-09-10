"""Bridge the blocking Agent loop onto a stream of SSE events.

`Agent.chat()` is synchronous and reports progress through callbacks, so it
cannot be awaited or iterated directly.  We run it on a worker thread and let
the callbacks push onto a queue that the request handler drains:

    Agent.chat()  --on_token/on_tool/on_tool_result-->  Queue  -->  SSE

The queue is bounded so a fast model cannot outrun a slow client without
applying backpressure to the worker.

Concurrency note: the file tools resolve relative paths against the process
working directory, so scoping the agent to a project means `os.chdir`, which
is process-global.  Runs are therefore serialised by `_RUN_LOCK`.  Removing
that limit means teaching the tools to take an explicit workspace root.
"""

from __future__ import annotations

import os
import queue
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from corecoder.agent import Agent
from corecoder.config import Config
from corecoder.llm import LLM, LiteLLM
from corecoder.profiles import get_profile, tools_for_profile

_RUN_LOCK = threading.Lock()
_QUEUE_MAXSIZE = 512
_DONE = object()


@dataclass
class Event:
    """One server-sent event."""

    type: str
    data: dict


def build_agent(profile_name: str) -> tuple[Agent, LLM]:
    """Construct an agent for a profile, or raise with a readable reason."""
    config = Config.from_env()
    if not config.api_key:
        raise RuntimeError(
            "No API key found. Set CORECODER_API_KEY, OPENAI_API_KEY, or DEEPSEEK_API_KEY."
        )

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
    return agent, llm


def stream_agent(root: Path, profile_name: str, prompt: str, agent: Agent | None = None) -> Iterator[Event]:
    """Run the agent inside `root` and yield events as they happen.

    Passing an existing `agent` continues that conversation; otherwise a fresh
    one is built for this run.
    """
    q: queue.Queue = queue.Queue(maxsize=_QUEUE_MAXSIZE)

    try:
        if agent is None:
            agent, llm = build_agent(profile_name)
        else:
            llm = agent.llm
    except Exception as e:
        yield Event("error", {"message": str(e), "kind": type(e).__name__})
        return

    def worker():
        old_cwd = os.getcwd()
        try:
            with _RUN_LOCK:
                os.chdir(root)
                try:
                    report = agent.chat(
                        prompt,
                        on_token=lambda t: q.put(Event("token", {"text": t})),
                        on_tool=lambda name, args: q.put(
                            Event("tool_start", {"name": name, "arguments": args})
                        ),
                        on_tool_result=lambda name, out: q.put(
                            Event("tool_result", {"name": name, "preview": _preview(out), "size": len(out)})
                        ),
                    )
                finally:
                    os.chdir(old_cwd)
            q.put(Event("done", {
                "report": report,
                "usage": {
                    "prompt_tokens": llm.total_prompt_tokens,
                    "completion_tokens": llm.total_completion_tokens,
                    "total_tokens": llm.total_prompt_tokens + llm.total_completion_tokens,
                    "cost_usd": llm.estimated_cost,
                },
            }))
        except Exception as e:
            # surface the real reason instead of a generic failure - a 400 from
            # the provider usually says exactly what is wrong
            q.put(Event("error", {"message": str(e), "kind": type(e).__name__}))
        finally:
            q.put(_DONE)

    thread = threading.Thread(target=worker, name="agent-run", daemon=True)
    thread.start()

    while True:
        item = q.get()
        if item is _DONE:
            break
        yield item


def _preview(text: str, limit: int = 600) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... (共 {len(text)} 字符)"
