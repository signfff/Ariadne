"""CoreCoder - A minimal, read-first agent for understanding codebases."""

__version__ = "0.4.0"

from corecoder.agent import Agent
from corecoder.llm import LLM
from corecoder.config import Config
from corecoder.tools import ALL_TOOLS
from corecoder.profiles import PROFILES, tools_for_profile

__all__ = ["Agent", "LLM", "Config", "ALL_TOOLS", "PROFILES", "tools_for_profile", "__version__"]
