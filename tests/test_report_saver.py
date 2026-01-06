"""
ReportSaver 테스트

백테스트 결과 저장 기능 테스트
"""

import pytest
from datetime import datetime
from pathlib import Path
import tempfile
import shutil

import pandas as pd

from intraday.performance import PerformanceReport, EquityPoint, ReportSaver
from intraday.paper_trader import Trade
from intraday.strategy import Side


class TestEquityPoint:
    """EquityPoint 데이터클래스 테스트"""

    def test_equity_point_creation(self):
        """EquityPoint 생성"""
        ep = EquityPoint(
            timestamp=datetime.now(),
            equity=10500.0,
            drawdown=1.5,
            cumulative_pnl=500.0,
            cumulative_return_pct=5.0,
        )

        assert ep.equity == 10500.0
        assert ep.drawdown == 1.5
        assert ep.cumulative_pnl == 500.0
        assert ep.cumulative_return_pct == 5.0


class TestReportSaver:
    """ReportSaver 테스트"""

    @pytest.fixture
    def sample_report(self) -> PerformanceReport:
        """테스트용 리포트"""
        return PerformanceReport(
            strategy_name="TestStrategy",
            symbol="BTCUSDT",
            start_time=datetime(2024, 1, 1, 0, 0, 0),
            end_time=datetime(2024, 1, 1, 1, 0, 0),
            initial_capital=10000.0,
            final_capital=10500.0,
            total_return=5.0,
            total_trades=10,
            winning_trades=6,
            losing_trades=4,
            win_rate=60.0,
            profit_factor=1.5,
            avg_win=100.0,
            avg_loss=50.0,
            max_drawdown=2.5,
            sharpe_ratio=1.2,
            total_fees=20.0,
        )

    @pytest.fixture
    def sample_trades(self) -> list[Trade]:
        """테스트용 거래 내역"""
        return [
            Trade(
                timestamp=datetime(2024, 1, 1, 0, 10, 0),
                side=Side.BUY,
                price=42000.0,
                quantity=0.01,
                fee=0.42,
                pnl=0.0,
            ),
            Trade(
                timestamp=datetime(2024, 1, 1, 0, 30, 0),
                side=Side.SELL,
                price=42500.0,
                quantity=0.01,
                fee=0.425,
                pnl=4.155,  # (42500-42000)*0.01 - 0.42 - 0.425
            ),
        ]

    @pytest.fixture
    def sample_equity_curve(self) -> list[EquityPoint]:
        """테스트용 equity curve"""
        return [
            EquityPoint(
                timestamp=datetime(2024, 1, 1, 0, 10, 0),
                equity=10000.0,
                drawdown=0.0,
                cumulative_pnl=0.0,
                cumulative_return_pct=0.0,
            ),
            EquityPoint(
                timestamp=datetime(2024, 1, 1, 0, 30, 0),
                equity=10004.155,
                drawdown=0.0,
                cumulative_pnl=4.155,
                cumulative_return_pct=0.04155,
            ),
        ]

    @pytest.fixture
    def temp_dir(self):
        """임시 디렉토리"""
        temp = tempfile.mkdtemp()
        yield temp
        shutil.rmtree(temp)

    def test_save_equity_curve(self, sample_report, sample_trades, sample_equity_curve, temp_dir):
        """Equity curve parquet 저장"""
        saver = ReportSaver(
            report=sample_report,
            trades=sample_trades,
            equity_curve=sample_equity_curve,
            output_dir=temp_dir,
        )

        filepath = saver.save_equity_curve()
        assert filepath.exists()

        df = pd.read_parquet(filepath)
        assert len(df) == 2
        assert "timestamp" in df.columns
        assert "equity" in df.columns
        assert "drawdown" in df.columns
        assert "cumulative_pnl" in df.columns
        assert "cumulative_return_pct" in df.columns

    def test_save_trades(self, sample_report, sample_trades, sample_equity_curve, temp_dir):
        """거래 내역 parquet 저장"""
        saver = ReportSaver(
            report=sample_report,
            trades=sample_trades,
            equity_curve=sample_equity_curve,
            output_dir=temp_dir,
        )

        filepath = saver.save_trades()
        assert filepath.exists()

        df = pd.read_parquet(filepath)
        assert len(df) == 2
        assert df.iloc[0]["side"] == "BUY"
        assert df.iloc[1]["side"] == "SELL"

    def test_save_summary(self, sample_report, sample_trades, sample_equity_curve, temp_dir):
        """요약 지표 parquet 저장"""
        saver = ReportSaver(
            report=sample_report,
            trades=sample_trades,
            equity_curve=sample_equity_curve,
            output_dir=temp_dir,
        )

        filepath = saver.save_summary()
        assert filepath.exists()

        df = pd.read_parquet(filepath)
        assert len(df) == 1
        assert df.iloc[0]["strategy_name"] == "TestStrategy"
        assert df.iloc[0]["total_return_pct"] == 5.0
        assert df.iloc[0]["win_rate_pct"] == 60.0

    def test_save_report_png(self, sample_report, sample_trades, sample_equity_curve, temp_dir):
        """PNG 리포트 생성"""
        saver = ReportSaver(
            report=sample_report,
            trades=sample_trades,
            equity_curve=sample_equity_curve,
            output_dir=temp_dir,
        )

        filepath = saver.save_report_png()
        assert filepath.exists()
        assert filepath.suffix == ".png"

    def test_save_all(self, sample_report, sample_trades, sample_equity_curve, temp_dir):
        """전체 저장"""
        saver = ReportSaver(
            report=sample_report,
            trades=sample_trades,
            equity_curve=sample_equity_curve,
            output_dir=temp_dir,
        )

        report_dir = saver.save_all()

        assert report_dir.exists()
        assert (report_dir / "equity_curve.parquet").exists()
        assert (report_dir / "trades.parquet").exists()
        assert (report_dir / "summary.parquet").exists()
        assert (report_dir / "report.png").exists()

    def test_empty_equity_curve_warning(self, sample_report, sample_trades, temp_dir, capsys):
        """빈 equity curve 경고"""
        saver = ReportSaver(
            report=sample_report,
            trades=sample_trades,
            equity_curve=[],
            output_dir=temp_dir,
        )

        saver.save_equity_curve()

        captured = capsys.readouterr()
        assert "Empty equity curve" in captured.out

    def test_empty_trades_warning(self, sample_report, sample_equity_curve, temp_dir, capsys):
        """빈 trades 경고"""
        saver = ReportSaver(
            report=sample_report,
            trades=[],
            equity_curve=sample_equity_curve,
            output_dir=temp_dir,
        )

        saver.save_trades()

        captured = capsys.readouterr()
        assert "Empty trades" in captured.out

    def test_report_dir_naming(self, sample_report, sample_trades, sample_equity_curve, temp_dir):
        """리포트 디렉토리 네이밍 패턴"""
        saver = ReportSaver(
            report=sample_report,
            trades=sample_trades,
            equity_curve=sample_equity_curve,
            output_dir=temp_dir,
        )

        # TestStrategy_{timestamp} 패턴 확인
        assert "TestStrategy_" in str(saver.report_dir)
