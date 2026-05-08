#!/usr/bin/env python3
"""NiceGUI dashboard for archived alpha artifacts."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from nicegui import app, ui


DEFAULT_RUN_DIR = Path("archive")
MAX_LINE_POINTS = 2000
METRIC_COLUMNS = [
    "run_id",
    "alpha_id",
    "status",
    "os_return",
    "os_sharpe",
    "os_trades",
    "is_return",
    "is_sharpe",
    "is_trades",
    "flags",
]
TABLE_COLUMNS = [
    ("run_id", "run", "left"),
    ("alpha_id", "alpha_id", "left"),
    ("status", "status", "left"),
    ("os_return_fmt", "OS ret", "right"),
    ("os_sharpe_fmt", "OS sh", "right"),
    ("os_trades", "OS tr", "right"),
    ("is_return_fmt", "IS ret", "right"),
    ("is_sharpe_fmt", "IS sh", "right"),
    ("is_trades", "IS tr", "right"),
    ("flags", "flags", "left"),
]
VALIDATION_RULES = {
    "RETURN_COLLAPSE": "IS return > 0, OS return < IS return * return_ratio.",
    "SHARPE_COLLAPSE": "IS Sharpe > 0, OS Sharpe < IS Sharpe * sharpe_ratio.",
    "SHARPE_SIGN_FLIP": "IS Sharpe > 0 and OS Sharpe < 0.",
    "DRAWDOWN_EXPANSION": "abs(OS drawdown) > abs(IS drawdown) * drawdown_ratio.",
    "WIN_RATE_DRIFT": "abs(OS win_rate - IS win_rate) > win_rate_gap.",
    "OS_TRADE_COUNT_TOO_LOW": "OS total_trades < min_os_trades.",
}
DEFAULT_THRESHOLDS = {
    "return_ratio": 0.30,
    "sharpe_ratio": 0.30,
    "drawdown_ratio": 2.0,
    "win_rate_gap": 0.20,
    "min_os_trades": 5,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Alpha archive dashboard")
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    return parser.parse_args()


def _missing(value: Any) -> bool:
    try:
        return bool(pd.isna(value))
    except Exception:
        return value is None


def _fmt_pct(value: Any) -> str:
    try:
        if _missing(value):
            return "-"
        return f"{float(value) * 100:.2f}%"
    except Exception:
        return "-"


def _fmt_num(value: Any) -> str:
    try:
        if _missing(value):
            return "-"
        return f"{float(value):.3f}"
    except Exception:
        return "-"


def _fmt_int(value: Any) -> str:
    try:
        if _missing(value):
            return "-"
        return f"{int(float(value)):,}"
    except Exception:
        return "-"


def _fmt_turnover(value: Any) -> str:
    try:
        if _missing(value):
            return "-"
        return f"{float(value):.2f}x"
    except Exception:
        return "-"


def _threshold_text(thresholds: dict[str, Any]) -> str:
    merged = dict(DEFAULT_THRESHOLDS)
    merged.update(thresholds or {})
    return (
        f"return_ratio={merged['return_ratio']}, "
        f"sharpe_ratio={merged['sharpe_ratio']}, "
        f"drawdown_ratio={merged['drawdown_ratio']}, "
        f"win_rate_gap={merged['win_rate_gap']}, "
        f"min_os_trades={merged['min_os_trades']}"
    )


def _duration_days(start: Any, end: Any) -> float | None:
    try:
        start_dt = datetime.fromisoformat(str(start))
        end_dt = datetime.fromisoformat(str(end))
    except Exception:
        return None
    return (end_dt - start_dt).total_seconds() / 86400.0 + 1 / 1440.0


def _fmt_days(days: float | None) -> str:
    if days is None:
        return "-"
    if days < 1:
        return f"{days * 24:.1f}h"
    if days < 10:
        return f"{days:.1f}d"
    return f"{days:.0f}d"


def load_index(run_dir: Path) -> pd.DataFrame:
    paths = [run_dir / "alpha_index.csv"] if (run_dir / "alpha_index.csv").exists() else sorted(run_dir.glob("*/alpha_index.csv"))
    if not paths:
        raise FileNotFoundError(f"missing alpha_index.csv under: {run_dir}")
    frames = []
    for path in paths:
        df = pd.read_csv(path)
        child_run_dir = path.parent
        df["run_id"] = child_run_dir.name
        df["_run_dir"] = str(child_run_dir)
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    for col in ("os_return", "os_sharpe", "os_trades", "is_return", "is_sharpe", "is_trades"):
        if col not in df.columns:
            df[col] = pd.NA
    for col in ("flags", "status"):
        if col in df.columns:
            df[col] = df[col].fillna("")
    return df


def load_splits(run_dir: Path) -> dict[str, Any]:
    return read_json(run_dir / "splits.json")


def alpha_dir(run_dir: Path, alpha_id: str) -> Path:
    return run_dir / "alphas" / alpha_id


def row_run_dir(row: dict[str, Any], default_run_dir: Path) -> Path:
    return Path(str(row.get("_run_dir") or default_run_dir))


@lru_cache(maxsize=2048)
def read_json_cached(path_text: str) -> dict[str, Any]:
    path = Path(path_text)
    return json.loads(path.read_text()) if path.exists() else {}


def read_json(path: Path) -> dict[str, Any]:
    return read_json_cached(str(path))


@lru_cache(maxsize=512)
def read_parquet_cached(path_text: str) -> pd.DataFrame:
    path = Path(path_text)
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


def read_parquet(path: Path) -> pd.DataFrame:
    return read_parquet_cached(str(path))


def _x(values: pd.Series) -> list[str]:
    return pd.to_datetime(values).astype(str).tolist()


def _downsample_frame(df: pd.DataFrame, max_points: int = MAX_LINE_POINTS) -> pd.DataFrame:
    if len(df) <= max_points:
        return df
    step = max(1, len(df) // max_points)
    sampled = df.iloc[::step].copy()
    if sampled.index[-1] != df.index[-1]:
        sampled = pd.concat([sampled, df.iloc[[-1]]])
    return sampled


def equity_figure(run_dir: Path, alpha_id: str) -> go.Figure:
    fig = go.Figure()
    for split, color in (("is", "#2563eb"), ("os", "#dc2626")):
        df = read_parquet(alpha_dir(run_dir, alpha_id) / split / "equity_curve.parquet")
        if df.empty:
            continue
        df = _downsample_frame(df)
        equity = df["equity"].astype(float)
        cumulative_return = equity / equity.iloc[0] - 1.0
        fig.add_trace(
            go.Scatter(
                x=_x(df["timestamp"]),
                y=cumulative_return,
                mode="lines",
                name=split.upper(),
                line={"color": color, "width": 1.5},
                hovertemplate="%{x}<br>%{y:.2%}<extra>%{fullData.name}</extra>",
            )
        )
    fig.update_layout(
        height=285,
        margin=dict(l=35, r=20, t=35, b=25),
        title="Cumulative Return",
        legend=dict(orientation="h"),
    )
    fig.update_yaxes(tickformat=".1%")
    return fig


def drawdown_figure(run_dir: Path, alpha_id: str) -> go.Figure:
    fig = go.Figure()
    for split, color in (("is", "#2563eb"), ("os", "#dc2626")):
        df = read_parquet(alpha_dir(run_dir, alpha_id) / split / "equity_curve.parquet")
        if df.empty:
            continue
        df = _downsample_frame(df)
        equity = df["equity"].astype(float)
        dd = equity / equity.cummax() - 1.0
        fig.add_trace(
            go.Scatter(
                x=_x(df["timestamp"]),
                y=dd,
                mode="lines",
                name=split.upper(),
                line={"color": color, "width": 1.5},
            )
        )
    fig.update_layout(height=250, margin=dict(l=35, r=20, t=35, b=25), title="Drawdown")
    fig.update_yaxes(tickformat=".1%")
    return fig


def return_distribution_figure(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if not df.empty and "os_return" in df and df["os_return"].notna().any():
        fig.add_trace(
            go.Histogram(
                x=df["os_return"],
                name="OS total return",
                marker_color="#334155",
                hovertemplate="OS return=%{x:.2%}<br>count=%{y}<extra></extra>",
            )
        )
        fig.add_vline(
            x=0,
            line_width=1,
            line_dash="dash",
            line_color="#dc2626",
        )
    fig.update_layout(
        height=230,
        margin=dict(l=35, r=20, t=35, b=35),
        title="OS Return Distribution",
        showlegend=False,
    )
    fig.update_xaxes(tickformat=".1%")
    return fig


def _weight_pivot(run_dir: Path, alpha_id: str, split: str) -> pd.DataFrame:
    df = read_parquet(alpha_dir(run_dir, alpha_id) / split / "weights.parquet")
    if df.empty:
        return pd.DataFrame()
    pivot = (
        df.sort_values("timestamp")
        .pivot_table(
            index="timestamp",
            columns="symbol",
            values="target_weight",
            aggfunc="last",
        )
        .sort_index()
    )
    return pivot.ffill().fillna(0.0)


def turnover_from_weights(run_dir: Path, alpha_id: str, split: str) -> float | None:
    pivot = _weight_pivot(run_dir, alpha_id, split)
    if pivot.empty:
        return None
    zero = pd.DataFrame([[0.0] * len(pivot.columns)], columns=pivot.columns)
    aligned = pd.concat([zero, pivot.reset_index(drop=True)], ignore_index=True)
    return float(aligned.diff().abs().sum(axis=1).sum())


def hourly_weight_stack_figure(run_dir: Path, alpha_id: str, split: str = "os") -> go.Figure:
    fig = go.Figure()
    pivot = _weight_pivot(run_dir, alpha_id, split)
    if not pivot.empty:
        equity = read_parquet(alpha_dir(run_dir, alpha_id) / split / "equity_curve.parquet")
        if not equity.empty:
            start = pd.to_datetime(equity["timestamp"]).min()
            end = pd.to_datetime(equity["timestamp"]).max()
            minute_index = pd.date_range(start=start, end=end, freq="1min")
            timeline = (
                pivot.reindex(pivot.index.union(minute_index))
                .sort_index()
                .ffill()
                .reindex(minute_index)
                .fillna(0.0)
            )
            hourly = timeline.resample("1h").mean()
        else:
            hourly = pivot.resample("1h").mean().ffill().fillna(0.0)
        abs_hourly = hourly.abs()
        for symbol in abs_hourly.columns:
            fig.add_trace(
                go.Scatter(
                    x=_x(pd.Series(abs_hourly.index)),
                    y=abs_hourly[symbol],
                    mode="lines",
                    name=symbol,
                    stackgroup="weights",
                    hovertemplate=(
                        "%{x}<br>abs weight=%{y:.1%}<extra>" + symbol + "</extra>"
                    ),
                )
            )
    fig.update_layout(
        height=300,
        margin=dict(l=35, r=20, t=35, b=25),
        title=f"{split.upper()} Hourly Weight Distribution",
        legend=dict(orientation="h"),
    )
    fig.update_yaxes(tickformat=".0%")
    return fig


def weights_figure(run_dir: Path, alpha_id: str, split: str = "os") -> go.Figure:
    df = read_parquet(alpha_dir(run_dir, alpha_id) / split / "weights.parquet")
    fig = go.Figure()
    if not df.empty:
        pivot = (
            df.pivot_table(
                index="symbol",
                columns="timestamp",
                values="target_weight",
                aggfunc="last",
            )
            .sort_index()
            .fillna(0.0)
        )
        fig.add_trace(
            go.Heatmap(
                x=[str(value) for value in pivot.columns],
                y=list(pivot.index),
                z=pivot.values,
                colorscale="RdBu",
                zmid=0,
                colorbar=dict(title="weight"),
            )
        )
    fig.update_layout(height=300, margin=dict(l=35, r=20, t=35, b=25), title=f"{split.upper()} Target Weights")
    return fig


def metric_card(label: str, value: str):
    with ui.card().classes("metric-card"):
        ui.label(label).classes("metric-label")
        ui.label(value).classes("metric-value")


def artifact_path(run_dir: Path, alpha_id: str) -> str:
    return str(alpha_dir(run_dir, alpha_id))


def validation_rules_card(thresholds: dict[str, Any] | None = None) -> None:
    with ui.card().classes("dense-panel grow"):
        ui.label("Validation warning rules").classes("section-title")
        with ui.row().classes("w-full gap-2"):
            ui.badge("PASS = no rule fired", color="green")
            ui.badge("WARNING = one or more rules fired", color="orange")
            ui.badge("not a profitability label", color="grey")
        ui.label(_threshold_text(thresholds or {})).classes("path-text")
        rows = [{"flag": flag, "rule": rule} for flag, rule in VALIDATION_RULES.items()]
        ui.table(
            columns=[
                {"name": "flag", "label": "flag", "field": "flag", "align": "left"},
                {"name": "rule", "label": "trigger", "field": "rule", "align": "left"},
            ],
            rows=rows,
            row_key="flag",
            pagination=0,
        ).classes("w-full validation-table")


def split_cards(splits: dict[str, Any]) -> None:
    if not splits:
        return
    for name in ("warmup", "is", "os"):
        split = splits.get(name, {})
        start = split.get("start", "?")
        end = split.get("end", "?")
        days = _duration_days(start, end)
        metric_card(f"{name.upper()} period", f"{_fmt_days(days)}")
    is_days = _duration_days(splits.get("is", {}).get("start"), splits.get("is", {}).get("end")) or 0
    os_days = _duration_days(splits.get("os", {}).get("start"), splits.get("os", {}).get("end")) or 0
    label = "SCOUT" if is_days < 30 or os_days < 7 else "RESEARCH"
    metric_card("Run type", label)


def field_contract_card() -> None:
    with ui.card().classes("dense-panel grow"):
        ui.label("Field contract").classes("section-title")
        with ui.grid(columns=2).classes("w-full gap-2"):
            with ui.card().classes("mini-card"):
                ui.label("status").classes("metric-label")
                ui.label("IS/OS warning label").classes("mini-value")
            with ui.card().classes("mini-card"):
                ui.label("return").classes("metric-label")
                ui.label("split total return, not CAGR").classes("mini-value")


def add_styles() -> None:
    ui.add_head_html(
        """
        <style>
        body { background: #f8fafc; color: #0f172a; }
        .page-wrap { max-width: 1500px; margin: 0 auto; padding: 14px; }
        .metric-card { min-width: 145px; padding: 10px 12px; border-radius: 6px; }
        .metric-label { color: #64748b; font-size: 12px; }
        .metric-value { font-size: 20px; font-weight: 650; color: #0f172a; }
        .section-title { font-size: 16px; font-weight: 650; color: #111827; }
        .q-table th { font-size: 11px; color: #475569; font-weight: 650; }
        .q-table td { font-size: 12px; white-space: nowrap; }
        .q-table tbody tr { cursor: pointer; }
        .q-table tbody tr:hover { background: #eef2ff; }
        .dense-panel { background: white; border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px; }
        .mini-card { border-radius: 6px; padding: 10px 12px; box-shadow: none; border: 1px solid #e5e7eb; }
        .mini-value { color: #0f172a; font-size: 13px; font-weight: 650; }
        .validation-table .q-table__top,
        .validation-table .q-table__bottom { display: none; }
        .validation-table .q-table td { height: 30px; padding: 4px 8px; }
        .validation-table .q-table th { height: 28px; padding: 4px 8px; }
        .path-text { color: #64748b; font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
        .note-text { color: #475569; font-size: 12px; line-height: 1.45; }
        </style>
        """
    )


def display_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    cols = [col for col in METRIC_COLUMNS if col in df.columns]
    for raw in df[cols].to_dict("records"):
        row = dict(raw)
        row["os_return_fmt"] = _fmt_pct(raw.get("os_return"))
        row["is_return_fmt"] = _fmt_pct(raw.get("is_return"))
        row["os_sharpe_fmt"] = _fmt_num(raw.get("os_sharpe"))
        row["is_sharpe_fmt"] = _fmt_num(raw.get("is_sharpe"))
        row["os_trades"] = _fmt_int(raw.get("os_trades"))
        row["is_trades"] = _fmt_int(raw.get("is_trades"))
        rows.append(row)
    return rows


def load_alpha_params(run_dir: Path, alpha_id: str) -> dict[str, Any]:
    queue = read_json(run_dir / "queue.json")
    for variant in queue.get("variants", []):
        if variant.get("alpha_id") == alpha_id:
            return variant.get("params", {})
    return {}


def build_search_text(run_dir: Path, df: pd.DataFrame) -> pd.Series:
    values = []
    for row in df.to_dict("records"):
        alpha_id = str(row.get("alpha_id", ""))
        row_dir = row_run_dir(row, run_dir)
        params = load_alpha_params(row_dir, alpha_id)
        values.append(
            " ".join(
                [
                    str(row.get("run_id", "")),
                    alpha_id,
                    str(row.get("status", "")),
                    str(row.get("flags", "")),
                    json.dumps(params, sort_keys=True),
                ]
            ).lower()
        )
    return pd.Series(values, index=df.index)


def main() -> None:
    args = parse_args()
    run_dir = Path(args.run_dir)
    app.storage.general["run_dir"] = str(run_dir)

    @ui.page("/")
    def page():
        df = load_index(run_dir)
        state = {"df": df, "search_text": build_search_text(run_dir, df)}
        add_styles()
        with ui.column().classes("page-wrap w-full gap-3"):
            ui.label("Alpha Archive Dashboard").classes("text-xl font-semibold")
            ui.label(str(run_dir)).classes("text-xs text-gray-500")

            df = state["df"]
            with ui.row().classes("w-full gap-2"):
                metric_card("Alphas", str(len(df)))
                metric_card("Runs", str(df["run_id"].nunique()))
                metric_card("IS Sharpe >= 1", str((pd.to_numeric(df["is_sharpe"], errors="coerce") >= 1).sum()))
                if (df["status"] == "IS_PASS").any():
                    metric_card("IS_PASS", str((df["status"] == "IS_PASS").sum()))
                metric_card("PASS", str((df["status"] == "PASS").sum()))
                metric_card("WARNING", str((df["status"] == "WARNING").sum()))
                metric_card("Best IS Sharpe", _fmt_num(pd.to_numeric(df["is_sharpe"], errors="coerce").max()))
                if "os_sharpe" in df and df["os_sharpe"].notna().any():
                    metric_card("Best OS Sharpe", _fmt_num(pd.to_numeric(df["os_sharpe"], errors="coerce").max()))

            with ui.row().classes("w-full gap-3"):
                field_contract_card()
                validation_rules_card()

            ui.plotly(return_distribution_figure(df)).classes("w-full dense-panel")

            with ui.row().classes("w-full items-end gap-3"):
                search_input = ui.input("Search").props("clearable dense").classes("w-96")
                status_values = sorted(str(v) for v in df["status"].dropna().unique().tolist())
                status_filter = ui.select(status_values, multiple=True, label="Status").classes("w-48")
                sort_select = ui.select(
                    ["is_sharpe", "is_return", "is_trades", "os_return", "os_sharpe", "os_trades"],
                    value="is_sharpe",
                    label="Sort",
                ).classes("w-48")
                min_is_sharpe = ui.number("Min IS Sharpe", value=None, step=0.1).classes("w-40")
                min_trades = ui.number("Min trades", value=0, min=0, step=1).classes("w-40")

            rows_container = ui.column().classes("w-full")

            table_ref = {"table": None}

            def filtered_rows() -> list[dict[str, Any]]:
                view = state["df"].copy()
                query = str(search_input.value or "").strip().lower()
                if query:
                    mask = state["search_text"].str.contains(query, regex=False, na=False)
                    view = view[mask]
                if status_filter.value:
                    view = view[view["status"].isin(status_filter.value)]
                if min_is_sharpe.value is not None:
                    is_sharpe = pd.to_numeric(view["is_sharpe"], errors="coerce")
                    view = view[is_sharpe >= float(min_is_sharpe.value)]
                if min_trades.value:
                    is_trades = pd.to_numeric(view["is_trades"], errors="coerce").fillna(0)
                    os_trades = pd.to_numeric(view["os_trades"], errors="coerce").fillna(0)
                    view = view[(is_trades >= int(min_trades.value)) | (os_trades >= int(min_trades.value))]
                view = view.sort_values(sort_select.value, ascending=False, na_position="last")
                return display_rows(view)

            def render_table():
                rows_container.clear()
                rows = filtered_rows()
                with rows_container:
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label(f"Alpha Table ({len(rows)})").classes("section-title")
                        ui.label("Click a row to inspect artifacts, IS/OS equity, weights, params, and validation flags.").classes("text-xs text-gray-500")
                    table = ui.table(
                        columns=[
                            {
                                "name": name,
                                "label": label,
                                "field": name,
                                "sortable": True,
                                "align": align,
                            }
                            for name, label, align in TABLE_COLUMNS
                        ],
                        rows=rows,
                        row_key="alpha_id",
                        pagination=25,
                    ).classes("w-full dense-panel")
                    table.on(
                        "rowClick",
                        lambda e: ui.navigate.to(f"/alpha/{e.args[1]['run_id']}/{e.args[1]['alpha_id']}"),
                    )
                    table_ref["table"] = table

            for control in (search_input, status_filter, sort_select, min_is_sharpe, min_trades):
                control.on_value_change(lambda _: render_table())

            render_table()

    @ui.page("/alpha/{run_id}/{alpha_id}")
    def alpha_page(run_id: str, alpha_id: str):
        add_styles()
        df = load_index(run_dir)
        selected_rows = df[(df["run_id"] == run_id) & (df["alpha_id"] == alpha_id)]
        with ui.column().classes("page-wrap w-full gap-3"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.button("Back", icon="arrow_back", on_click=lambda: ui.navigate.to("/"))
                detail_run_dir = Path(run_id) if (Path(run_id) / "alpha_index.csv").exists() else run_dir / run_id
                ui.label(artifact_path(detail_run_dir, alpha_id)).classes("path-text")
            if selected_rows.empty:
                ui.label(f"Unknown alpha_id: {alpha_id}").classes("text-lg font-semibold")
                return

            selected = selected_rows.iloc[0].to_dict()
            detail_run_dir = row_run_dir(selected, detail_run_dir)
            validation = read_json(alpha_dir(detail_run_dir, alpha_id) / "validation.json")
            params = load_alpha_params(detail_run_dir, alpha_id)
            is_turnover = turnover_from_weights(detail_run_dir, alpha_id, "is")
            os_turnover = turnover_from_weights(detail_run_dir, alpha_id, "os")

            ui.label(alpha_id).classes("text-xl font-semibold")
            with ui.row().classes("w-full gap-3"):
                field_contract_card()
                validation_rules_card(validation.get("thresholds", {}))
            with ui.row().classes("gap-2"):
                metric_card("Status", str(selected.get("status", "-")))
                metric_card("OS Return", _fmt_pct(selected.get("os_return")))
                metric_card("OS Sharpe", _fmt_num(selected.get("os_sharpe")))
                metric_card("OS Trades", _fmt_int(selected.get("os_trades", 0)))
                metric_card("OS Turnover", _fmt_turnover(os_turnover))
                metric_card("IS Return", _fmt_pct(selected.get("is_return")))
                metric_card("IS Sharpe", _fmt_num(selected.get("is_sharpe")))
                metric_card("IS Trades", _fmt_int(selected.get("is_trades", 0)))
                metric_card("IS Turnover", _fmt_turnover(is_turnover))
            with ui.grid(columns=2).classes("w-full gap-3"):
                ui.plotly(equity_figure(detail_run_dir, alpha_id)).classes("w-full dense-panel")
                ui.plotly(drawdown_figure(detail_run_dir, alpha_id)).classes("w-full dense-panel")
                ui.plotly(hourly_weight_stack_figure(detail_run_dir, alpha_id, "is")).classes("w-full dense-panel")
                ui.plotly(weights_figure(detail_run_dir, alpha_id, "is")).classes("w-full dense-panel")
            with ui.tabs().classes("w-full") as tabs:
                tab_params = ui.tab("Params")
                tab_validation = ui.tab("Validation")
            with ui.tab_panels(tabs, value=tab_params).classes("w-full"):
                with ui.tab_panel(tab_params):
                    ui.code(json.dumps(params, indent=2), language="json").classes("w-full")
                with ui.tab_panel(tab_validation):
                    ui.code(json.dumps(validation, indent=2), language="json").classes("w-full")

    ui.run(host=args.host, port=args.port, title="Alpha Dashboard", reload=False)


if __name__ == "__main__":
    main()
