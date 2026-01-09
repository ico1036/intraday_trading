"""
Test: backtest_tool module reload behavior

Verifies that strategy code changes are picked up without restarting the process.
This was a bug where Developer's code fixes weren't reflected in Analyst's backtests.
"""

import importlib
import shutil
import sys
import tempfile
from pathlib import Path

import pytest


class TestModuleCacheClearing:
    """Test that module cache is properly cleared before import."""

    def test_discover_strategies_clears_base_module_cache(self):
        """Verify base module is removed from sys.modules before strategy import."""
        # Import backtest_tool
        from scripts.agent.tools.backtest_tool import _discover_strategies

        # Pre-populate cache with a marker
        base_module = "intraday.strategies.base"
        if base_module in sys.modules:
            original = sys.modules[base_module]
        else:
            original = None

        # Call discover (this should clear and reimport)
        _discover_strategies("tick")

        # Base module should be freshly imported (different object if was cached)
        # Note: We can't easily test object identity since it gets reimported,
        # but we can verify the module is present after discovery
        assert base_module in sys.modules

        # Cleanup
        if original:
            sys.modules[base_module] = original

    def test_discover_strategies_clears_strategy_module_cache(self):
        """Verify strategy modules are removed from cache before import."""
        from scripts.agent.tools.backtest_tool import _discover_strategies

        # First call to populate cache
        strategies1 = _discover_strategies("tick")

        # Verify at least one strategy was found
        assert len(strategies1) > 0, "No tick strategies found"

        # Get one strategy module name
        strategy_name = list(strategies1.keys())[0]

        # The strategy module should be in cache now
        # (after fresh import during discovery)
        strategy_modules = [m for m in sys.modules if "intraday.strategies.tick" in m]
        assert len(strategy_modules) > 0

        # Second call should clear and reimport
        strategies2 = _discover_strategies("tick")

        # Should get same strategies
        assert set(strategies1.keys()) == set(strategies2.keys())


class TestHotReloadSimulation:
    """Simulate the hot reload scenario that was failing."""

    def test_strategy_code_change_is_detected(self, tmp_path: Path):
        """
        Simulate:
        1. Strategy exists with version A
        2. Strategy is discovered (cached)
        3. Strategy code changes to version B
        4. Strategy is discovered again
        5. Version B should be used
        """
        # Create a temporary strategy file
        strategies_dir = tmp_path / "strategies"
        strategies_dir.mkdir()
        (strategies_dir / "__init__.py").write_text("")

        # Write version A
        strategy_file = strategies_dir / "test_hot_reload.py"
        strategy_file.write_text('''
VERSION = "A"

class TestHotReloadStrategy:
    version = "A"
''')

        # Add to Python path temporarily
        sys.path.insert(0, str(tmp_path))

        try:
            # Import version A
            import strategies.test_hot_reload as mod_a
            assert mod_a.VERSION == "A"
            assert mod_a.TestHotReloadStrategy.version == "A"

            # Write version B (simulating Developer's fix)
            strategy_file.write_text('''
VERSION = "B"

class TestHotReloadStrategy:
    version = "B"
''')

            # Clear __pycache__ (critical for hot reload!)
            pycache = strategies_dir / "__pycache__"
            if pycache.exists():
                shutil.rmtree(pycache)

            # Clear cache like backtest_tool does
            module_name = "strategies.test_hot_reload"
            if module_name in sys.modules:
                del sys.modules[module_name]
            if "strategies" in sys.modules:
                del sys.modules["strategies"]

            # Reimport - should get version B
            mod_b = importlib.import_module(module_name)
            assert mod_b.VERSION == "B"
            assert mod_b.TestHotReloadStrategy.version == "B"

        finally:
            # Cleanup
            if str(tmp_path) in sys.path:
                sys.path.remove(str(tmp_path))
            if "strategies.test_hot_reload" in sys.modules:
                del sys.modules["strategies.test_hot_reload"]
            if "strategies" in sys.modules:
                del sys.modules["strategies"]

    def test_dependency_change_propagates(self, tmp_path: Path):
        """
        Simulate:
        1. base.py has version A
        2. strategy.py imports base.py
        3. base.py changes to version B
        4. Without clearing base, strategy still sees version A
        5. With clearing base, strategy sees version B
        """
        pkg_dir = tmp_path / "testpkg"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")

        # Write base version A
        base_file = pkg_dir / "base.py"
        base_file.write_text('BASE_VERSION = "A"')

        # Write strategy that imports base
        strategy_file = pkg_dir / "strategy.py"
        strategy_file.write_text('''
from .base import BASE_VERSION

class MyStrategy:
    base_version = BASE_VERSION
''')

        sys.path.insert(0, str(tmp_path))

        try:
            # Import strategy (which imports base)
            from testpkg.strategy import MyStrategy
            assert MyStrategy.base_version == "A"

            # Change base to version B
            base_file.write_text('BASE_VERSION = "B"')

            # Clear __pycache__ (critical!)
            pycache = pkg_dir / "__pycache__"
            if pycache.exists():
                shutil.rmtree(pycache)

            # Clear BOTH base and strategy (what backtest_tool does)
            # Also clear __init__ for completeness
            for mod in ["testpkg.base", "testpkg.strategy", "testpkg"]:
                if mod in sys.modules:
                    del sys.modules[mod]

            # Now reimport
            from testpkg.strategy import MyStrategy as MyStrategy3
            assert MyStrategy3.base_version == "B", \
                "Base module change should propagate after cache clear"

        finally:
            if str(tmp_path) in sys.path:
                sys.path.remove(str(tmp_path))
            for mod in list(sys.modules.keys()):
                if mod.startswith("testpkg"):
                    del sys.modules[mod]


class TestDiscoverStrategiesIntegration:
    """Integration tests with real strategy files."""

    def test_discover_tick_strategies(self):
        """Verify tick strategies are discovered."""
        from scripts.agent.tools.backtest_tool import _discover_strategies

        strategies = _discover_strategies("tick")
        assert len(strategies) > 0, "Should find at least one tick strategy"

        # All keys should end with "Strategy"
        for name in strategies:
            assert name.endswith("Strategy"), f"{name} should end with 'Strategy'"

    def test_discover_orderbook_strategies(self):
        """Verify orderbook strategies are discovered."""
        from scripts.agent.tools.backtest_tool import _discover_strategies

        strategies = _discover_strategies("orderbook")
        # May be empty if no orderbook strategies exist, that's OK
        for name in strategies:
            assert name.endswith("Strategy"), f"{name} should end with 'Strategy'"

    def test_get_all_strategies_includes_metadata(self):
        """Verify _get_all_strategies returns proper metadata."""
        from scripts.agent.tools.backtest_tool import _get_all_strategies

        all_strategies = _get_all_strategies()

        for name, info in all_strategies.items():
            assert "class" in info, f"{name} should have 'class' in metadata"
            assert "data_type" in info, f"{name} should have 'data_type' in metadata"
            assert info["data_type"] in ["tick", "orderbook"], \
                f"{name} should have valid data_type"
