"""Compare view: any alphas and composites, any window, on one axis.

View only. Every number here arrives from ``alpha_dashboard_lib`` (bundle,
aligned returns, table rows, correlation) and the caller; this module draws.
"""
from __future__ import annotations

import html
from typing import Any, Callable

import pandas as pd
import plotly.graph_objects as go
from nicegui import ui

from alpha_dashboard_lib import (
    COMPARE_BASES,
    COMPARE_BASIS_LABELS,
    COMPARE_WINDOW_LABELS,
    COMPARE_WINDOWS,
    compare_cumulative,
    compare_url,
)

PALETTE = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2", "#be185d", "#4d7c0f"]

XFormatter = Callable[[pd.Series], list[str]]


def _line_width(kind: str, base: float) -> float:
    return base + 1.0 if kind == "composite" else base


def compare_figure(aligned: pd.DataFrame, names: dict[str, str], kinds: dict[str, str], basis: str,
                   btc: pd.DataFrame | None, window: str, x: XFormatter) -> go.Figure:
    fig = go.Figure()
    for i, col in enumerate(aligned.columns):
        cum = compare_cumulative(aligned[col], basis)
        fig.add_trace(go.Scatter(
            x=x(pd.Series(cum.index)), y=cum.values, mode="lines", name=names[col],
            line={"color": PALETTE[i % len(PALETTE)], "width": _line_width(kinds[col], 1.8)},
            hovertemplate="%{x}<br>%{y:.2%}<extra>%{fullData.name}</extra>",
        ))
    if aligned.shape[1] >= 2:
        blend = compare_cumulative(aligned.mean(axis=1), basis)
        fig.add_trace(go.Scatter(
            x=x(pd.Series(blend.index)), y=blend.values, mode="lines", name="1/N blend of selection",
            line={"color": "#64748b", "width": 2.0, "dash": "dash"},
            hovertemplate="%{x}<br>%{y:.2%}<extra>1/N blend</extra>",
        ))
    if btc is not None and not btc.empty:
        fig.add_trace(go.Scatter(
            x=x(btc["timestamp"]), y=btc["cumret"], mode="lines", name="BTCUSDT (compound)",
            line={"color": "#f59e0b", "width": 2.0, "dash": "dot"},
            hovertemplate="%{x}<br>%{y:.2%}<extra>BTCUSDT</extra>",
        ))
    fig.update_layout(
        height=460, autosize=True, margin=dict(l=52, r=18, t=48, b=96),
        title=f"{COMPARE_WINDOW_LABELS[window]} · cumulative return, {COMPARE_BASIS_LABELS[basis].lower()}, rebased to 0 at the common start",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="top", y=-0.16, xanchor="center", x=0.5, font={"size": 10}),
    )
    fig.update_yaxes(tickformat=".1%", zeroline=True, zerolinecolor="#94a3b8")
    return fig


def compare_drawdown_figure(aligned: pd.DataFrame, names: dict[str, str], kinds: dict[str, str],
                            basis: str, x: XFormatter) -> go.Figure:
    fig = go.Figure()
    for i, col in enumerate(aligned.columns):
        cum = compare_cumulative(aligned[col], basis)
        dd = (1.0 + cum) / (1.0 + cum).cummax() - 1.0 if basis == "compound" else cum - cum.cummax()
        fig.add_trace(go.Scatter(
            x=x(pd.Series(dd.index)), y=dd.values, mode="lines", name=names[col], showlegend=False,
            line={"color": PALETTE[i % len(PALETTE)], "width": _line_width(kinds[col], 1.5)},
            hovertemplate="%{x}<br>%{y:.2%}<extra>%{fullData.name}</extra>",
        ))
    fig.update_layout(height=240, autosize=True, margin=dict(l=52, r=18, t=36, b=36), title="Drawdown", hovermode="x unified")
    fig.update_yaxes(tickformat=".1%", zeroline=True, zerolinecolor="#94a3b8")
    return fig


def corr_html(corr: pd.DataFrame, names: dict[str, str]) -> str:
    cols = list(corr.columns)
    head = "".join(f"<th>{html.escape(names[c][:22])}</th>" for c in cols)
    body = ""
    for r in cols:
        cells = ""
        for c in cols:
            v = float(corr.loc[r, c])
            a = min(abs(v), 1.0) * 0.55
            bg = f"rgba(37,99,235,{a:.2f})" if v >= 0 else f"rgba(220,38,38,{a:.2f})"
            cells += f'<td style="background:{bg};text-align:right;padding:4px 8px;font-variant-numeric:tabular-nums">{v:+.2f}</td>'
        body += f'<tr><th style="text-align:left;padding:4px 8px">{html.escape(names[r][:22])}</th>{cells}</tr>'
    return (
        '<div class="wide" style="overflow-x:auto"><table style="border-collapse:collapse;font-size:12px">'
        f"<thead><tr><th></th>{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


METRIC_COLUMNS = [
    {"name": "name", "label": "strategy", "field": "name", "align": "left"},
    {"name": "kind", "label": "kind", "field": "kind", "align": "left"},
    {"name": "run", "label": "run", "field": "run", "align": "left"},
    {"name": "sharpe", "label": "Sharpe", "field": "sharpe", "align": "right"},
    {"name": "cagr", "label": "CAGR", "field": "cagr", "align": "right"},
    {"name": "mdd", "label": "MDD", "field": "mdd", "align": "right"},
    {"name": "cum", "label": "cum", "field": "cum", "align": "right"},
    {"name": "days", "label": "days", "field": "days", "align": "right"},
    {"name": "trades", "label": "trades", "field": "trades", "align": "right"},
    {"name": "fees", "label": "fees", "field": "fees", "align": "right"},
    {"name": "slippage", "label": "slippage", "field": "slippage", "align": "right"},
    {"name": "funding", "label": "funding", "field": "funding", "align": "right"},
]


def render_compare_launcher(options: dict[str, str], default_window: str = "os",
                            preselect: list[str] | None = None) -> None:
    """Compact picker for the Alphas and Composites tabs; opens /compare."""
    with ui.column().classes("section-panel w-full gap-2"):
        ui.label("Compare strategies").classes("section-title")
        with ui.row().classes("w-full items-end gap-3"):
            pick = ui.select(options, multiple=True, with_input=True, value=list(preselect or []),
                             label="Alphas and composites").classes("w-[560px]").props("dense use-chips")
            win = ui.toggle(COMPARE_WINDOW_LABELS, value=default_window).props("dense no-caps")
            ui.button("Open compare", icon="stacked_line_chart",
                      on_click=lambda: ui.navigate.to(compare_url(list(pick.value or []), str(win.value)))
                      ).props("dense")


def render_compare_page(*, options: dict[str, str], keys: list[str], window: str, basis: str,
                        include_btc: bool, bundle: dict[str, dict[str, Any]], aligned: pd.DataFrame,
                        rows: list[dict[str, Any]], corr: pd.DataFrame, btc: pd.DataFrame | None,
                        x: XFormatter) -> None:
    names = {k: v["name"] for k, v in bundle.items()}
    kinds = {k: v["kind"] for k, v in bundle.items()}
    with ui.column().classes("page-wrap w-full gap-3"):
        with ui.row().classes("items-center gap-3"):
            ui.button("Back", icon="arrow_back", on_click=lambda: ui.navigate.to("/")).props("flat").classes("detail-back")
            ui.label("Compare").classes("page-title")

        # One control row scopes everything below it.
        with ui.column().classes("section-panel w-full gap-2"):
            with ui.row().classes("w-full items-end gap-3"):
                pick = ui.select(options, multiple=True, with_input=True, value=[k for k in keys if k in options],
                                 label="Alphas and composites").classes("w-[640px]").props("dense use-chips")
                win = ui.toggle(COMPARE_WINDOW_LABELS, value=window if window in COMPARE_WINDOWS else "os").props("dense no-caps")
                bas = ui.toggle(COMPARE_BASIS_LABELS, value=basis if basis in COMPARE_BASES else "simple").props("dense no-caps")
                btc_sw = ui.switch("BTC overlay", value=include_btc).props("dense")
                ui.button("Apply", icon="refresh",
                          on_click=lambda: ui.navigate.to(compare_url(list(pick.value or []), str(win.value), str(bas.value), bool(btc_sw.value)))
                          ).props("dense")
            ui.label("Simple basis is PnL over the run's initial capital (fixed-AUM convention, additive across strategies); "
                     "compound is equity growth. Series are aligned on the common window and rebased to 0.").classes("mini-value")

        if not keys:
            ui.label("Pick at least one strategy and press Apply.").classes("empty-state")
            return
        skipped = [f"{v['name']}: {v['reason']}" for v in bundle.values() if v.get("reason")]
        if skipped:
            ui.label("Skipped — " + "; ".join(skipped)).classes("note-text")
        if aligned.empty:
            ui.label("Nothing to plot in this window.").classes("empty-state")
            return

        with ui.column().classes("section-panel w-full gap-2"):
            ui.plotly(compare_figure(aligned, names, kinds, basis, btc, window, x)).classes("w-full chart-host")
            ui.plotly(compare_drawdown_figure(aligned, names, kinds, basis, x)).classes("w-full chart-host")

        with ui.column().classes("section-panel w-full gap-2"):
            ui.label(f"{COMPARE_WINDOW_LABELS[window]} metrics on the common window "
                     f"({aligned.index.min().date()} → {aligned.index.max().date()}, {len(aligned)} days; "
                     "Sharpe on 365 days; costs as a share of initial capital)").classes("section-title")
            ui.table(columns=METRIC_COLUMNS, rows=rows, row_key="name").classes("w-full dense-panel")

        if not corr.empty:
            with ui.column().classes("section-panel w-full gap-2"):
                ui.label("Correlation of daily returns on the common window").classes("section-title")
                ui.html(corr_html(corr, names), sanitize=False)
