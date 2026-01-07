"""
Agent definitions for the Quant Research Automation System.

Agents:
- Researcher: Idea analysis, hypothesis generation, data EDA
- Developer: Strategy code implementation using templates
- Analyst: Backtest execution, performance analysis, feedback generation
"""

from .researcher import get_system_prompt as researcher_prompt, get_allowed_tools as researcher_tools
from .developer import get_system_prompt as developer_prompt, get_allowed_tools as developer_tools
from .analyst import get_system_prompt as analyst_prompt, get_allowed_tools as analyst_tools

__all__ = [
    "researcher_prompt",
    "researcher_tools",
    "developer_prompt",
    "developer_tools",
    "analyst_prompt",
    "analyst_tools",
]
