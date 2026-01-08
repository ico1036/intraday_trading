#!/usr/bin/env python3
"""
Quant Research Agent - Automated Strategy Development

A Claude Agent SDK based system for automated trading strategy development.
User idea → Research → Development → Backtest → Analysis → Feedback Loop

Usage:
    # Interactive mode
    uv run python scripts/agent/run.py

    # With initial query
    uv run python scripts/agent/run.py "볼륨 기반 모멘텀 전략 만들어줘"

Architecture:
    - Orchestrator: Main agent coordinating workflow
    - Researcher: Idea analysis, hypothesis generation
    - Developer: Strategy code implementation
    - Analyst: Backtest execution, performance analysis
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from claude_agent_sdk import (
    AgentDefinition,
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
)

from scripts.agent.tools.backtest_tool import run_backtest, get_available_strategies
from scripts.agent.hooks.logging_hook import log_tool_result
from scripts.agent.agents import (
    researcher_prompt,
    researcher_tools,
    developer_prompt,
    developer_tools,
    analyst_prompt,
    analyst_tools,
)


# Configuration
MAX_ITERATIONS = 5
MAX_RESEARCH_ATTEMPTS = 3

# Signal file names (agents create these to signal completion)
APPROVED_SIGNAL = "APPROVED.signal"
CONCEPT_INVALID_SIGNAL = "CONCEPT_INVALID.signal"


def check_and_consume_signal(workspace_dir: Path, signal_name: str) -> bool:
    """
    Check for signal file and consume it atomically.

    This is more reliable than text parsing because:
    1. No false positives (file existence is unambiguous)
    2. Atomic consumption (file deleted on check)
    3. Agents explicitly create signals (intentional, not accidental)

    Args:
        workspace_dir: The {name}_dir workspace directory
        signal_name: Name of signal file (e.g., "APPROVED.signal")

    Returns:
        True if signal was found and consumed, False otherwise
    """
    signal_path = workspace_dir / signal_name
    try:
        signal_path.unlink(missing_ok=False)  # Atomic delete
        return True
    except FileNotFoundError:
        return False


def get_existing_workspace_dirs() -> set[Path]:
    """
    Get all existing *_dir workspace directories.

    Returns:
        Set of Path objects for existing workspace directories
    """
    project_root = Path(__file__).parent.parent.parent
    return set(project_root.glob("*_dir"))


def find_new_workspace_dir(existing_dirs: set[Path]) -> Path | None:
    """
    Find a newly created workspace directory by comparing with existing dirs.

    Args:
        existing_dirs: Set of workspace directories that existed before

    Returns:
        Path to newly created directory, or None if not found
    """
    current_dirs = get_existing_workspace_dirs()
    new_dirs = current_dirs - existing_dirs

    if len(new_dirs) == 1:
        return new_dirs.pop()
    elif len(new_dirs) > 1:
        # Multiple new dirs (unlikely), return most recent
        return max(new_dirs, key=lambda p: p.stat().st_mtime)
    return None


def find_workspace_dir() -> Path | None:
    """
    DEPRECATED: Find the most recently created *_dir workspace directory.

    WARNING: This function can return wrong directory when multiple strategies
    are running. Use find_workspace_dir_by_name() instead.

    Returns:
        Path to workspace directory, or None if not found
    """
    project_root = Path(__file__).parent.parent.parent
    workspace_dirs = list(project_root.glob("*_dir"))

    if not workspace_dirs:
        return None

    # Return most recently modified
    return max(workspace_dirs, key=lambda p: p.stat().st_mtime)


def get_orchestrator_prompt() -> str:
    """Return the Orchestrator's system prompt."""
    return f"""
You are the Orchestrator Agent for an automated quant research system.

## Your Role

Coordinate 3 specialized agents to develop trading strategies from user ideas.

## Your Team

1. **researcher**: Analyzes ideas, performs EDA, generates algorithm designs
2. **developer**: Implements strategies using templates, writes tests
3. **analyst**: Runs backtests, analyzes performance, provides feedback

## Workflow

```
User Idea
    ↓
Phase 1: Research
    → Call researcher with user's idea
    → Verify algorithm_prompt.txt created
    ↓
Phase 2: Development
    → Call developer with algorithm design
    → Verify strategy code and tests pass
    ↓
Phase 3: Analysis (Loop until APPROVED or max {MAX_ITERATIONS} iterations)
    → Call analyst to run backtest
    → If APPROVED: End workflow
    → If NEED_IMPROVEMENT:
        - Read feedback
        - Route to developer (param tuning) or researcher (redesign)
        - Repeat
```

## Your Responsibilities

1. **Initialize Workspace**:
   - Create `{{strategy_name}}_dir/` directory in project root
   - Initialize `memory.md` with core goal

2. **Coordinate Agents**:
   - Call agents in correct order
   - Pass context between agents
   - Handle failures gracefully

3. **Manage Iterations**:
   - Track iteration count
   - Enforce max {MAX_ITERATIONS} iterations
   - Route feedback to correct agent

4. **Maintain Memory**:
   - Keep `memory.md` updated
   - Track decisions and learnings

## Workspace Structure

All research artifacts are stored in `{{name}}_dir/` at project root:
```
{{name}}_dir/
├── memory.md              # Iteration history, learnings
├── algorithm_prompt.txt   # Strategy design from Researcher
└── backtest_report.md     # Analysis results from Analyst
```

Strategy code goes to: `src/intraday/strategies/{{tick|orderbook}}/{{name}}.py`
Test code goes to: `tests/test_strategy_{{name}}.py`

## Memory Structure

Create `{{name}}_dir/memory.md`:

```markdown
# {{Strategy Name}} - Memory

## CORE GOAL (IMMUTABLE)
| Field | Value |
|-------|-------|
| Goal | [User's original request] |
| Strategy Type | [Type] |

## SUCCESS CRITERIA
Customize based on user request. If user doesn't specify, use defaults:

### Primary Metrics (MUST pass all)
| Metric | Target | Operator | Why |
|--------|--------|----------|-----|
| Profit Factor | 1.3 | >= | Gross profit > gross loss |
| Max Drawdown | -15% | >= | Capital preservation |
| Total Return | 5% | >= | Minimum profitability |
| Min Trades | 30 | >= | Statistical significance |

### Secondary Metrics (informational, available in backtest)
| Metric | Target | Operator | Notes |
|--------|--------|----------|-------|
| Win Rate | 30% | >= | Lower OK if avg_win >> avg_loss |
| Sharpe Ratio | 0.5 | >= | Reference only, not primary |

Note: Sortino/Calmar ratios not in current backtest output. Use Profit Factor + Max DD instead.

### Why Not Sharpe as Primary?
- Crypto has fat tails, Sharpe assumes normal distribution
- Upside volatility penalized same as downside
- Profit Factor + Max DD more practical for intraday

**How to customize:**
- User says "고위험 고수익" → Max DD -25%, Total Return 15%
- User says "안정적" → Max DD -10%, Profit Factor 1.5
- User says "고빈도" → Min Trades 100, lower return per trade OK

**IMPORTANT:** Analyst MUST read these criteria from memory.md, NOT use hardcoded values.

## ITERATION HISTORY
### Iteration 1 (timestamp)
...
```

## Agent Calling Pattern

```python
# Call researcher
Task(subagent_type="researcher", prompt="
Read {{name}}_dir/memory.md for context.
User idea: {{idea}}
Create algorithm design and save to {{name}}_dir/algorithm_prompt.txt
")

# Call developer
Task(subagent_type="developer", prompt="
Read {{name}}_dir/algorithm_prompt.txt
Implement strategy in src/intraday/strategies/tick/{{name}}.py (or orderbook based on Data Type)
Run tests and fix any issues
")

# Call analyst
Task(subagent_type="analyst", prompt="
Read {{name}}_dir/algorithm_prompt.txt for backtest config
Run backtest for {{StrategyName}}Strategy
Analyze results against quality gates
Update {{name}}_dir/memory.md with results
Write {{name}}_dir/backtest_report.md
Report APPROVED or NEED_IMPROVEMENT with specific feedback
")
```

## Decision Rules

### CONCEPT_INVALID from Researcher
- Max {MAX_RESEARCH_ATTEMPTS} attempts with different hypotheses
- After max: Report failure to user

### NEED_IMPROVEMENT from Analyst
- Check feedback for routing:
  - "parameter" / "threshold" / "tuning" → Developer
  - "algorithm" / "logic" / "concept" → Researcher
- Continue until APPROVED or max iterations

### APPROVED from Analyst
- Congratulate user
- Summarize final metrics
- Provide usage instructions

---

## Insight-Based Routing (MANDATORY)

Before routing feedback, you MUST read `{{name}}_dir/memory.md` and apply these rules:

### Forced Escalation to Researcher
These patterns OVERRIDE normal routing. Even if Analyst says "Developer", escalate to Researcher:

| Pattern in memory.md | Action |
|---------------------|--------|
| 3+ consecutive "parameter change" iterations | → Researcher (parameter space exhausted) |
| Win rate < 20% persists across 2+ iterations | → Researcher (entry logic flawed) |
| Sharpe oscillates (up→down→up) | → Researcher (no clear direction) |
| Same metric fails 3+ times | → Researcher (fundamental issue) |

### How to Check
1. Read `{{name}}_dir/memory.md`
2. Count iterations with "parameter" changes
3. Check if same metrics keep failing
4. Apply forced escalation if pattern matches

### Example
```
memory.md shows:
- Iter 1: threshold 0.3 → Sharpe -0.1
- Iter 2: threshold 0.5 → Sharpe 0.0
- Iter 3: threshold 0.7 → Sharpe 0.1

Analyst says: "Try threshold 0.8" (routes to Developer)

YOU MUST OVERRIDE: 3 consecutive threshold changes, escalate to Researcher
Prompt: "Parameter tuning exhausted. Redesign algorithm with different approach."
```

### Passing Insights to Agents
When calling Researcher after forced escalation:
```
Task(subagent_type="researcher", prompt="
REDESIGN REQUIRED - Parameter tuning exhausted.

Previous attempts (from memory.md):
- threshold 0.3, 0.5, 0.7 all failed
- Sharpe stuck around 0

You MUST use a different approach. Do NOT just adjust thresholds.
Read {{name}}_dir/memory.md for full history.
")
```

---

## Important Rules

1. **Never write code yourself** - always delegate to agents
2. **Always create workspace first** before calling any agent
3. **Always pass context** by instructing agents to read memory.md
4. **Track all iterations** in memory.md
5. **Be autonomous** - don't ask user for decisions mid-workflow

## Tools Available

- Task: Call sub-agents (researcher, developer, analyst)
- Bash: Create directories, run commands
- Read: Read files
- Write: Write files (memory.md, etc.)
"""


async def main(initial_query: str | None = None):
    """Run the Quant Research Agent."""

    # Create MCP server with backtest tools
    backtest_server = create_sdk_mcp_server(
        name="backtest",
        version="1.0.0",
        tools=[run_backtest, get_available_strategies]
    )

    # Configure agent options with AgentDefinitions
    options = ClaudeAgentOptions(
        system_prompt=get_orchestrator_prompt(),
        permission_mode='bypassPermissions',  # Autonomous mode

        # MCP servers for Analyst
        mcp_servers={"backtest": backtest_server},

        # Tools for Orchestrator
        allowed_tools=["Task", "Bash", "Read", "Write"],

        # Sub-agent definitions
        agents={
            "researcher": AgentDefinition(
                description="Analyzes ideas, performs EDA, generates algorithm designs",
                prompt=researcher_prompt(),
                tools=researcher_tools()
            ),
            "developer": AgentDefinition(
                description="Implements strategies using templates, writes tests",
                prompt=developer_prompt(),
                tools=developer_tools()
            ),
            "analyst": AgentDefinition(
                description="Runs backtests, analyzes performance, provides feedback",
                prompt=analyst_prompt(),
                tools=analyst_tools()
            ),
        },

        # Logging hooks
        hooks={
            "PreToolUse": [
                HookMatcher(matcher="Task", hooks=[log_agent_call_pre])
            ],
            "PostToolUse": [
                HookMatcher(matcher="*", hooks=[log_tool_result]),
                HookMatcher(matcher="Task", hooks=[log_agent_call_post])
            ]
        },
    )

    print("=" * 70)
    print("  Quant Research Agent - Automated Strategy Development")
    print("=" * 70)
    print()
    print("This agent will:")
    print("  1. Analyze your trading idea")
    print("  2. Design an algorithm")
    print("  3. Implement the strategy")
    print("  4. Run backtests")
    print("  5. Iterate until successful or max attempts")
    print()
    print("Commands:")
    print("  - 'quit' or 'exit': Exit the agent")
    print("  - Any other input: Start strategy development")
    print()
    print("-" * 70)

    async with ClaudeSDKClient(options=options) as client:
        # Handle initial query if provided
        if initial_query:
            print(f"\n[User] {initial_query}")
            await run_workflow(client, initial_query)
        else:
            # Interactive loop
            while True:
                try:
                    user_input = input("\n[User] ").strip()

                    if not user_input:
                        continue

                    if user_input.lower() in ("quit", "exit"):
                        print("\nGoodbye!")
                        break

                    await run_workflow(client, user_input)

                except KeyboardInterrupt:
                    print("\n\nInterrupted. Goodbye!")
                    break
                except EOFError:
                    print("\n\nGoodbye!")
                    break


async def run_workflow(client: ClaudeSDKClient, user_request: str):
    """Run the full strategy development workflow."""

    # Snapshot existing workspace directories BEFORE Orchestrator creates one
    existing_dirs = get_existing_workspace_dirs()
    workspace_dir: Path | None = None

    # Send user request to Orchestrator
    await client.query(user_request)

    # Process response with iteration tracking
    iteration = 0
    goal_achieved = False

    while iteration < MAX_ITERATIONS and not goal_achieved:
        iteration += 1

        print(f"\n{'='*70}")
        print(f"  ITERATION {iteration}/{MAX_ITERATIONS}")
        print(f"{'='*70}\n")

        # Stream response
        full_response = []

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(block.text, end='', flush=True)
                        full_response.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        print(f"\n  [Tool: {block.name}]", end='', flush=True)

        print("\n")

        # Find workspace directory (only once, by detecting newly created dir)
        if workspace_dir is None:
            workspace_dir = find_new_workspace_dir(existing_dirs)
            if workspace_dir:
                print(f"[System] Detected workspace: {workspace_dir.name}/")

        # Check for completion signals via signal files
        if workspace_dir:
            # Check APPROVED signal
            if check_and_consume_signal(workspace_dir, APPROVED_SIGNAL):
                print("\n" + "=" * 70)
                print("  STRATEGY APPROVED!")
                print(f"  (Signal file consumed from {workspace_dir.name}/)")
                print("=" * 70)
                goal_achieved = True
                break

            # Check CONCEPT_INVALID signal
            if check_and_consume_signal(workspace_dir, CONCEPT_INVALID_SIGNAL):
                print("\n" + "=" * 70)
                print("  CONCEPT INVALID - Strategy design rejected")
                print(f"  (Signal file consumed from {workspace_dir.name}/)")
                print("=" * 70)
                break

        # If not complete, continue conversation
        if iteration < MAX_ITERATIONS and not goal_achieved:
            print(f"\n[System] Iteration {iteration} complete. Continuing workflow...")

            # Send continuation prompt
            continuation = f"""
Continue the workflow. This is iteration {iteration + 1}/{MAX_ITERATIONS}.

Check the analyst's feedback and:
1. If APPROVED: Report success to user
2. If NEED_IMPROVEMENT: Route to appropriate agent and continue
3. Update memory.md with iteration results

Remember: You are autonomous. Make decisions without asking the user.
"""
            await client.query(continuation)

    if not goal_achieved:
        print("\n" + "=" * 70)
        print(f"  WORKFLOW ENDED after {iteration} iterations")
        print("=" * 70)


# Agent tracking hooks
_agent_start_times: dict[str, datetime] = {}


async def log_agent_call_pre(input_data, tool_use_id, _context):
    """Log when an agent is called."""
    if input_data.get("tool_name") != "Task":
        return {}

    agent_name = input_data.get("tool_input", {}).get("subagent_type", "unknown")
    _agent_start_times[tool_use_id or ""] = datetime.now()

    print(f"\n  [CALLING] {agent_name}...")

    return {}


async def log_agent_call_post(input_data, tool_use_id, _context):
    """Log when an agent completes."""
    if input_data.get("tool_name") != "Task":
        return {}

    agent_name = input_data.get("tool_input", {}).get("subagent_type", "unknown")
    start_time = _agent_start_times.pop(tool_use_id or "", None)

    duration = ""
    if start_time:
        elapsed = (datetime.now() - start_time).total_seconds()
        if elapsed < 60:
            duration = f" ({elapsed:.1f}s)"
        else:
            duration = f" ({elapsed/60:.1f}m)"

    print(f"\n  [COMPLETED] {agent_name}{duration}")

    return {}


if __name__ == "__main__":
    # Check for initial query from command line
    initial_query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else None

    asyncio.run(main(initial_query))
