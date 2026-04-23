#!/usr/bin/env python3
"""v2 harness entry point.

Three CLI modes:

    # Bootstrap the run directory + open PLAN.md in $EDITOR.
    uv run python scripts/agent/run_v2.py my_run

    # Scaffold only; don't open editor.
    uv run python scripts/agent/run_v2.py my_run --prepare

    # Kick off the agent loop (requires PLAN.md to be edited first).
    uv run python scripts/agent/run_v2.py my_run --run

Phase 1-5 status: SDK invoke is a pragmatic prototype — each agent call
spins up a short-lived ``ClaudeSDKClient``. Later phases can refactor to a
single long-lived session.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from datetime import date  # noqa: E402

from scripts.agent.v2 import orchestrator, sdk_coordinator  # noqa: E402
from scripts.agent.v2.agents import analyst, developer, researcher  # noqa: E402
from scripts.agent.v2.deterministic import oos_clamp  # noqa: E402
from scripts.agent.v2.deterministic import plan as plan_mod  # noqa: E402
from scripts.agent.v2.scaffold import (  # noqa: E402
    RunScaffoldError,
    is_done,
    run_path,
    scaffold_run,
)


# ---------------------------------------------------------------------------
# Editor helper.
# ---------------------------------------------------------------------------


def open_editor(path: Path) -> int:
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    return subprocess.call([editor, str(path)])


# ---------------------------------------------------------------------------
# SDK invoke — real LLM wiring. Synchronous wrapper over an async session.
# ---------------------------------------------------------------------------


def _build_sdk_invoke(*, os_end: date) -> sdk_coordinator.InvokeFn:
    """Return an invoke function backed by ``claude_agent_sdk``.

    The returned function spawns one ``ClaudeSDKClient`` per agent call with:
        - the agent definitions produced by ``scripts.agent.v2.agents``
        - a PreToolUse hook that clamps OOS dates to ``os_end``

    Imports happen at function build time so the tree stays importable even
    in environments where the SDK is not installed.
    """
    from claude_agent_sdk import (  # type: ignore
        AgentDefinition,
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        HookMatcher,
        TextBlock,
    )

    agents = {
        "researcher": AgentDefinition(
            description="Proposes a thesis or composes a new expression.",
            prompt=researcher.identity_prompt(),
            tools=["Read", "Write", "WebSearch"],
        ),
        "developer": AgentDefinition(
            description="Implements a strategy and its tests.",
            prompt=developer.identity_prompt(),
            tools=["Read", "Write", "Edit", "Bash"],
        ),
        "analyst": AgentDefinition(
            description="Runs backtests and tags failure modes.",
            prompt=analyst.identity_prompt(),
            tools=[
                "Read",
                "Write",
                "mcp__backtest__run_backtest",
                "mcp__backtest__run_portfolio_backtest",
            ],
        ),
    }

    clamp_hook = oos_clamp.build_hook(os_end=os_end)

    async def _invoke_async(agent_name: str, task_prompt: str) -> None:
        options = ClaudeAgentOptions(
            permission_mode="bypassPermissions",
            agents=agents,
            allowed_tools=["Task", "Read", "Write"],
            hooks={
                "PreToolUse": [
                    HookMatcher(matcher="Write|Edit", hooks=[clamp_hook])
                ],
            },
        )
        system_message = (
            f"Delegate the task to the `{agent_name}` subagent via the Task "
            "tool. Pass the following prompt verbatim:\n\n" + task_prompt
        )
        async with ClaudeSDKClient(options=options) as client:
            await client.query(system_message)
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            sys.stdout.write(block.text)
                            sys.stdout.flush()

    def _invoke(agent_name: str, task_prompt: str) -> None:
        asyncio.run(_invoke_async(agent_name, task_prompt))

    return _invoke


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_v2",
        description="v2 research harness entry point.",
    )
    parser.add_argument("run_id", help="identifier for this run")
    parser.add_argument(
        "--prepare", action="store_true", help="scaffold only; no editor"
    )
    parser.add_argument(
        "--edit",
        action="store_true",
        help="open PLAN.md in editor even if the run already exists",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite PLAN.md and clear DONE sentinel",
    )
    parser.add_argument(
        "--no-edit",
        action="store_true",
        help="never open editor (useful for CI)",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="start the agent loop after scaffolding",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=1000,
        help="hard cap on orchestrator iterations",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        result = scaffold_run(args.run_id, force=args.force)
    except RunScaffoldError as exc:
        print(f"[run_v2] {exc}", file=sys.stderr)
        return 2

    print(
        f"[run_v2] {'scaffolded' if result.created else 'resuming'} {result.path}"
    )

    should_edit = not args.no_edit and (
        args.edit or args.force or (result.created and not args.prepare and not args.run)
    )
    if should_edit:
        rc = open_editor(result.plan_path)
        if rc != 0:
            print(f"[run_v2] editor exited {rc}", file=sys.stderr)
            return rc

    if not args.run:
        print(f"[run_v2] PLAN.md → {result.plan_path}")
        print("[run_v2] re-run with --run to start the agent loop.")
        return 0

    # --run path ------------------------------------------------------------

    try:
        plan = plan_mod.parse_file(result.plan_path)
    except plan_mod.PlanError as exc:
        print(f"[run_v2] PLAN.md invalid: {exc}", file=sys.stderr)
        return 3

    invoke = _build_sdk_invoke(os_end=plan.os_end)
    coord = sdk_coordinator.SDKCoordinator(
        run_dir=result.path,
        plan=plan,
        invoke=invoke,
        plan_path=result.plan_path,
    )

    outcome = orchestrator.run(
        run_dir=result.path,
        plan=plan,
        coord=coord,
        max_iterations=args.max_iterations,
    )

    print(f"\n[run_v2] iterations: {outcome.iterations}")
    print(f"[run_v2] reason: {outcome.decision.reason}")
    if outcome.decision.winning_expression:
        print(f"[run_v2] winning: {outcome.decision.winning_expression}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
