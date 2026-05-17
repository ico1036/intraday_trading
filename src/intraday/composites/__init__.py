"""Composite alphas: linear combinations of archived per-alpha weight series.

Copy ``_composite_template.py`` to ``<composite_id>.py`` and fill in the two
hooks (``select_members``, ``member_weights``). The runner builds
``archive/<run_id>/composites/<composite_id>/`` and replays the combined
weight series via ``PrecomputedWeightsStrategy`` for IS and OS backtests.
"""
