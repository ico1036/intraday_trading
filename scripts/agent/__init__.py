"""
Claude Agent SDK based backtest analyst agent.

Simple architecture:
- MCP Tool: run_backtest (wraps TickBacktestRunner)
- Hook: PostToolUse logging
- Agent: backtest_analyst (uses .claude/agents/backtest_analyst.md prompt)
"""
