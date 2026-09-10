"""CoreCoder - A minimal, read-first agent for understanding codebases."""

__version__ = "0.4.0"

from corecoder.agent import Agent
from corecoder.config import Config
from corecoder.llm import LLM
from corecoder.profiles import PROFILES, tools_for_profile
from corecoder.tools import ALL_TOOLS

__all__ = ["ALL_TOOLS", "LLM", "PROFILES", "Agent", "Config", "__version__", "tools_for_profile"]
