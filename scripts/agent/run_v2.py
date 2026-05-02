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


def _resolve_cli_path() -> str | None:
    """Pick a claude CLI binary that the SDK can drive successfully.

    The shipped ``claude`` CLI 2.1.118 has a regression that crashes inside
    the SDK subprocess with ``TypeError: null is not an object (evaluating
    'T.effortLevel')`` — visible only with ``extra_args={"debug-to-stderr":
    None}``. The subprocess emits ``SystemMessage(init)`` then
    ``ResultMessage(subtype='error_during_execution')`` with
    ``usage.input_tokens=0`` because the model is never called.

    Resolution order:
        1. ``CLAUDE_SDK_CLI_PATH`` env var, if set and executable.
        2. The newest ``~/.local/share/claude/versions/<ver>`` binary that
           is NOT 2.1.118 (prefer 2.1.117, fall back to 2.1.114).
        3. ``None`` — let the SDK fall back to ``shutil.which("claude")``
           and hope the user has a working CLI on PATH.
    """
    import os as _os
    from pathlib import Path as _Path

    override = _os.environ.get("CLAUDE_SDK_CLI_PATH")
    if override and _Path(override).is_file() and _os.access(override, _os.X_OK):
        return override

    versions_dir = _Path.home() / ".local/share/claude/versions"
    if not versions_dir.is_dir():
        return None

    def _sort_key(p: _Path) -> tuple[int, ...]:
        try:
            return tuple(int(x) for x in p.name.split("."))
        except ValueError:
            return (0,)

    candidates = [
        p
        for p in versions_dir.iterdir()
        if p.is_file() and _os.access(p, _os.X_OK) and p.name != "2.1.118"
    ]
    if not candidates:
        return None
    candidates.sort(key=_sort_key, reverse=True)
    return str(candidates[0])


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
        ToolUseBlock,
        create_sdk_mcp_server,
    )

    # MCP backtest server — without this, the analyst's `mcp__backtest__*`
    # tool references are dead names.
    from scripts.agent.tools.backtest_tool import (  # noqa: E402
        get_available_strategies,
        run_backtest,
        run_portfolio_backtest,
    )

    backtest_server = create_sdk_mcp_server(
        name="backtest",
        version="1.0.0",
        tools=[run_backtest, run_portfolio_backtest, get_available_strategies],
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

    _ = oos_clamp.build_hook(os_end=os_end)  # noqa: F841 — kept for re-enable

    cli_path = _resolve_cli_path()
    if cli_path:
        print(f"[sdk] using claude CLI: {cli_path}", flush=True)

    orchestrator_system = (
        "You are a dispatch orchestrator. Your only job is to invoke the "
        "specified subagent via the Task tool with the given prompt. You "
        "do not have file I/O or code-execution tools — you cannot do the "
        "subagent's work yourself. Call Task, then wait for it to return."
    )

    async def _invoke_async(agent_name: str, task_prompt: str) -> None:
        # NOTE: the OOS clamp hook is temporarily disabled while we diagnose
        # an SDK error_during_execution. Phase 3 ships the hook factory and
        # tests; wiring it back here depends on the correct return signature
        # for this SDK version.
        options = ClaudeAgentOptions(
            system_prompt=orchestrator_system,
            permission_mode="bypassPermissions",
            agents=agents,
            mcp_servers={"backtest": backtest_server},
            # Task only — denies the orchestrator any escape hatch to do the
            # subagent's work itself. All file I/O happens inside subagents
            # via the tools declared on each AgentDefinition.
            allowed_tools=["Task"],
            cli_path=cli_path,
        )
        user_message = (
            f"Please invoke the `{agent_name}` subagent using the Task "
            f"tool. Use this prompt verbatim:\n\n{task_prompt}"
        )

        print(f"\n[sdk] ▶ invoking {agent_name} ...", flush=True)
        task_called = False
        message_count = 0
        async with ClaudeSDKClient(options=options) as client:
            await client.query(user_message)
            async for message in client.receive_response():
                message_count += 1
                msg_type = type(message).__name__
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        block_type = type(block).__name__
                        if isinstance(block, TextBlock):
                            sys.stdout.write(block.text)
                        elif isinstance(block, ToolUseBlock):
                            sys.stdout.write(
                                f"\n[sdk] ▸ tool={block.name} "
                                f"input_keys={list((block.input or {}).keys())}"
                            )
                            if block.name == "Task":
                                task_called = True
                        else:
                            sys.stdout.write(f"\n[sdk] ▸ block={block_type}")
                        sys.stdout.flush()
                else:
                    # Dump anything that's not an AssistantMessage so we can
                    # see what the SDK actually returned (stats, errors, etc.)
                    sys.stdout.write(f"\n[sdk] ▸ message={msg_type}")
                    for attr in (
                        "subtype",
                        "num_turns",
                        "total_cost_usd",
                        "usage",
                        "is_error",
                        "result",
                        "session_id",
                    ):
                        if hasattr(message, attr):
                            sys.stdout.write(f" {attr}={getattr(message, attr)!r}")
                    sys.stdout.flush()
        print(
            f"\n[sdk] ✓ {agent_name} returned "
            f"(messages={message_count}, task_called={task_called})",
            flush=True,
        )
        if not task_called:
            print(
                f"[sdk] WARNING: orchestrator returned without calling Task. "
                f"The `{agent_name}` subagent was NOT invoked.",
                file=sys.stderr,
                flush=True,
            )

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

    # Open editor on fresh scaffold OR explicit --edit/--force, unless
    # --no-edit/--prepare. ``--run`` on a fresh scaffold still triggers the
    # editor so the user can't accidentally start the loop with an unedited
    # PLAN.
    should_edit = not args.no_edit and (
        args.edit or args.force or (result.created and not args.prepare)
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

    def _is_placeholder(p):
        return (
            not p.strategy_request
            or plan_mod.PLACEHOLDER_MARKER in p.strategy_request
        )

    # If PLAN still has the placeholder, open the editor once (unless
    # --no-edit), then re-parse. Fail only if the user leaves it unedited.
    if _is_placeholder(plan) and not args.no_edit:
        print(
            "[run_v2] PLAN.md still has placeholder ``<write here>``. "
            "Opening editor — fill in Strategy request and save.",
            file=sys.stderr,
        )
        rc = open_editor(result.plan_path)
        if rc != 0:
            print(f"[run_v2] editor exited {rc}", file=sys.stderr)
            return rc
        try:
            plan = plan_mod.parse_file(result.plan_path)
        except plan_mod.PlanError as exc:
            print(f"[run_v2] PLAN.md invalid after edit: {exc}", file=sys.stderr)
            return 3

    if _is_placeholder(plan):
        print(
            "[run_v2] PLAN.md still has placeholder. Aborting.",
            file=sys.stderr,
        )
        return 4

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
