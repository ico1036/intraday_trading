"""
PostToolUse Logging Hook

Logs all tool executions to a JSONL file for analysis and debugging.

Usage:
    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher
    from scripts.agent.hooks import log_tool_result

    options = ClaudeAgentOptions(
        hooks={
            "PostToolUse": [
                HookMatcher(matcher="*", hooks=[log_tool_result])
            ]
        }
    )
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

# Log file path
LOG_DIR = Path(__file__).parent.parent.parent.parent / "logs"
LOG_FILE = LOG_DIR / "agent_runs.jsonl"


async def log_tool_result(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: dict[str, Any]
) -> dict[str, Any]:
    """
    Log tool execution results to JSONL file.

    This hook is called after every tool execution, capturing:
    - Tool name and input
    - Tool response
    - Timestamp
    - Session context

    Args:
        input_data: Contains tool_name, tool_input, tool_response
        tool_use_id: Unique ID for this tool invocation
        context: Session context

    Returns:
        Empty dict (no modification to agent behavior)
    """
    try:
        # Ensure log directory exists
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        # Extract tool info
        tool_name = input_data.get("tool_name", "unknown")
        tool_input = input_data.get("tool_input", {})
        tool_response = input_data.get("tool_response", "")

        # Create log entry
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "tool_use_id": tool_use_id,
            "tool_name": tool_name,
            "tool_input": _sanitize_for_json(tool_input),
            "tool_response_preview": _truncate(str(tool_response), 500),
            "is_error": "error" in str(tool_response).lower(),
        }

        # Append to JSONL file
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

        # If this was a backtest, provide summary in context
        if tool_name == "mcp__backtest__run_backtest":
            return _analyze_backtest_result(tool_response)

    except Exception as e:
        # Don't let logging errors affect the agent
        print(f"[Hook] Logging error: {e}")

    return {}


def _analyze_backtest_result(tool_response: str) -> dict[str, Any]:
    """
    Analyze backtest results and provide additional context.

    If the backtest shows concerning patterns, add a system message
    to guide the agent's analysis.
    """
    response_str = str(tool_response)

    # Check for concerning patterns
    warnings = []

    # Check win rate
    if "Win Rate" in response_str:
        import re
        match = re.search(r"Win Rate.*?(\d+\.?\d*)%", response_str)
        if match:
            win_rate = float(match.group(1))
            if win_rate < 20:
                warnings.append(f"Very low win rate ({win_rate}%) - strategy may be fundamentally flawed")
            elif win_rate > 80:
                warnings.append(f"Unusually high win rate ({win_rate}%) - check for overfitting")

    # Check profit factor
    if "Profit Factor" in response_str:
        import re
        match = re.search(r"Profit Factor.*?(\d+\.?\d*)", response_str)
        if match:
            pf = float(match.group(1))
            if pf < 0.5:
                warnings.append(f"Very low profit factor ({pf}) - losses far exceed wins")

    # Check total trades
    if "Total Trades" in response_str:
        import re
        match = re.search(r"Total Trades.*?(\d+)", response_str)
        if match:
            trades = int(match.group(1))
            if trades > 500:
                warnings.append(f"High trade count ({trades}) - check for over-trading")
            elif trades < 10:
                warnings.append(f"Very few trades ({trades}) - may not be statistically significant")

    if warnings:
        return {
            "systemMessage": "Backtest Warning:\n- " + "\n- ".join(warnings),
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "warnings": warnings,
            }
        }

    return {}


def _sanitize_for_json(obj: Any) -> Any:
    """Convert non-JSON-serializable objects to strings."""
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_for_json(item) for item in obj]
    elif isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    else:
        return str(obj)


def _truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len characters."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "... [truncated]"
