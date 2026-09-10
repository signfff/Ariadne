"""Agent profiles for different project-assistant workflows."""

from __future__ import annotations

from dataclasses import dataclass

from .tools import ALL_TOOLS, get_tool
from .tools.base import Tool


@dataclass(frozen=True)
class AgentProfile:
    """A named tool set plus behavior instructions."""

    name: str
    description: str
    tool_names: tuple[str, ...] | None
    instructions: str


PROFILES: dict[str, AgentProfile] = {
    "full": AgentProfile(
        name="full",
        description="Full coding agent with read, write, shell, search, and sub-agent tools.",
        tool_names=None,
        instructions="Use the full tool set to implement, verify, and explain software changes.",
    ),
    "learn": AgentProfile(
        name="learn",
        description="Read-only teaching mode for helping people understand a project.",
        tool_names=("read_file", "glob", "grep", "search_code"),
        instructions=(
            "你处在只读教学模式。目标是帮助用户更快读懂项目，而不是查 bug 或修改代码。"
            "默认使用中文，讲解要面向正在接手项目的人。"
            "优先解释项目目标、目录结构、入口流程、核心模块、关键概念、数据/控制流和推荐阅读顺序。"
            "回答要引用你查看过的文件，并把复杂代码拆成容易理解的步骤。"
            "不要修改文件，不要运行命令，不要把输出写成代码审查报告。"
        ),
    ),
    "ask": AgentProfile(
        name="ask",
        description="Read-only codebase Q&A mode for architecture and implementation questions.",
        tool_names=("read_file", "glob", "grep", "search_code"),
        instructions=(
            "你处在只读项目问答模式。只能使用搜索和文件读取工具回答仓库问题。"
            "不要声称已经编辑文件、运行命令、安装依赖或修改工作区，因为这些工具在当前模式不可用。"
            "回答默认使用中文，并引用你查看过的文件。"
        ),
    ),
    "review": AgentProfile(
        name="review",
        description="Read-only code review mode focused on bugs, risks, and missing tests.",
        tool_names=("read_file", "glob", "grep", "search_code"),
        instructions=(
            "你处在只读代码审查模式。默认使用中文。"
            "结论必须优先列出具体问题，并按严重级别排序。"
            "重点关注 bug、行为回归、安全风险、边界条件、错误处理和测试缺口。"
            "每个问题都要尽量给出文件路径、行号或可定位的函数/代码片段、影响说明和修改建议。"
            "不要修改文件，不要运行命令。"
        ),
    ),
}


def available_profiles() -> list[str]:
    """Return the supported profile names in CLI display order."""
    return list(PROFILES)


def get_profile(name: str) -> AgentProfile:
    """Return a profile or raise a clear error for invalid names."""
    try:
        return PROFILES[name]
    except KeyError as e:
        names = ", ".join(available_profiles())
        raise ValueError(f"unknown profile '{name}' (available: {names})") from e


def tools_for_profile(name: str) -> list[Tool]:
    """Build the tool list for a profile."""
    profile = get_profile(name)
    if profile.tool_names is None:
        return list(ALL_TOOLS)

    tools = []
    for tool_name in profile.tool_names:
        tool = get_tool(tool_name)
        if tool is None:
            raise RuntimeError(f"profile '{name}' references missing tool '{tool_name}'")
        tools.append(tool)
    return tools
