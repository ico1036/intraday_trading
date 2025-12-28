"""
백테스터 테스트

OrderbookBacktestRunner와 TickBacktestRunner의 기본 동작을 테스트합니다.
"""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from intraday import (
    OrderbookSnapshot,
    AggTrade,
    OBIStrategy,
    OrderbookBacktestRunner,
    TickBacktestRunner,
    BarType,
)
from intraday.data.loader import OrderbookDataLoader, TickDataLoader


class TestOrderbookBacktestRunner:
    """OrderbookBacktestRunner 테스트"""
    
    def test_run_with_sample_data(self, tmp_path: Path):
        """샘플 오더북 데이터로 백테스트 실행"""
        # Given: 샘플 오더북 데이터 생성
        base_price = 50000.0
        timestamps = [datetime.now() + timedelta(milliseconds=i * 100) for i in range(100)]
        
        records = []
        for i, ts in enumerate(timestamps):
            # 가격 약간씩 변동
            price = base_price + (i % 10) - 5
            
            record = {
                "timestamp": ts,
                "last_update_id": i,
                "symbol": "BTCUSDT",
            }
            
            # Bid/Ask 레벨 생성 (20 레벨)
            for j in range(20):
                record[f"bid_price_{j}"] = price - j - 1
                record[f"bid_qty_{j}"] = 1.0 + j * 0.1
                record[f"ask_price_{j}"] = price + j + 1
                record[f"ask_qty_{j}"] = 1.0 + j * 0.1
            
            # 불균형 시뮬레이션: 일부 스냅샷에서 bid_qty >> ask_qty
            if i % 20 < 5:
                record["bid_qty_0"] = 10.0  # 매수 압력 강함
                record["ask_qty_0"] = 1.0
            elif i % 20 >= 15:
                record["bid_qty_0"] = 1.0
                record["ask_qty_0"] = 10.0  # 매도 압력 강함
            
            records.append(record)
        
        df = pd.DataFrame(records)
        parquet_path = tmp_path / "orderbook_btcusdt_test.parquet"
        df.to_parquet(parquet_path, index=False)
        
        # When: 백테스트 실행
        loader = OrderbookDataLoader(tmp_path, symbol="btcusdt")
        strategy = OBIStrategy(buy_threshold=0.3, sell_threshold=-0.3, quantity=0.01)
        
        runner = OrderbookBacktestRunner(
            strategy=strategy,
            data_loader=loader,
            initial_capital=10000.0,
        )
        
        report = runner.run(progress_interval=1000)
        
        # Then: 결과 검증
        assert runner.snapshot_count == 100
        assert report is not None
        assert report.total_trades >= 0  # 거래 발생 여부는 데이터에 따라 다름
    
    def test_runner_uses_paper_trader(self, tmp_path: Path):
        """PaperTrader가 정상적으로 재사용되는지 확인"""
        # Given: 최소 데이터
        ts = datetime.now()
        record = {
            "timestamp": ts,
            "last_update_id": 1,
            "symbol": "BTCUSDT",
        }
        for j in range(20):
            record[f"bid_price_{j}"] = 50000 - j
            record[f"bid_qty_{j}"] = 1.0
            record[f"ask_price_{j}"] = 50001 + j
            record[f"ask_qty_{j}"] = 1.0
        
        df = pd.DataFrame([record])
        parquet_path = tmp_path / "orderbook_btcusdt_test.parquet"
        df.to_parquet(parquet_path, index=False)
        
        loader = OrderbookDataLoader(tmp_path, symbol="btcusdt")
        strategy = OBIStrategy()
        
        runner = OrderbookBacktestRunner(
            strategy=strategy,
            data_loader=loader,
            initial_capital=5000.0,
            fee_rate=0.002,
        )
        
        # When: 러너의 trader 확인
        # Then: PaperTrader가 올바른 초기값으로 설정됨
        assert runner.trader.initial_capital == 5000.0
        assert runner.trader.fee_rate == 0.002


class TestTickBacktestRunner:
    """TickBacktestRunner 테스트"""
    
    def test_run_with_volume_bar(self, tmp_path: Path):
        """볼륨바 기반 백테스트 실행"""
        # Given: 샘플 틱 데이터 생성
        base_time = datetime.now()
        records = []
        
        for i in range(1000):
            records.append({
                "timestamp": base_time + timedelta(milliseconds=i * 10),
                "symbol": "BTCUSDT",
                "price": 50000.0 + (i % 100) - 50,  # 가격 변동
                "quantity": 0.1,  # 각 틱 0.1 BTC
                "is_buyer_maker": i % 3 == 0,  # 33%는 매도 주도
            })
        
        df = pd.DataFrame(records)
        parquet_path = tmp_path / "BTCUSDT-aggTrades-test.parquet"
        df.to_parquet(parquet_path, index=False)
        
        # When: 볼륨바 백테스트 실행 (1 BTC마다 바 생성)
        loader = TickDataLoader(tmp_path, symbol="BTCUSDT")
        strategy = OBIStrategy(buy_threshold=0.3, sell_threshold=-0.3, quantity=0.01)
        
        runner = TickBacktestRunner(
            strategy=strategy,
            data_loader=loader,
            bar_type=BarType.VOLUME,
            bar_size=1.0,  # 1 BTC마다 바
            initial_capital=10000.0,
        )
        
        report = runner.run(progress_interval=10000)
        
        # Then: 결과 검증
        assert runner.tick_count == 1000
        # 1000틱 * 0.1 BTC = 100 BTC → 100개 바 예상
        assert runner.bar_count >= 90  # 약간의 오차 허용
    
    def test_run_with_tick_bar(self, tmp_path: Path):
        """틱바 기반 백테스트 실행"""
        # Given: 샘플 틱 데이터
        base_time = datetime.now()
        records = []
        
        for i in range(500):
            records.append({
                "timestamp": base_time + timedelta(milliseconds=i * 10),
                "symbol": "BTCUSDT",
                "price": 50000.0,
                "quantity": 0.05,
                "is_buyer_maker": False,
            })
        
        df = pd.DataFrame(records)
        parquet_path = tmp_path / "BTCUSDT-aggTrades-test.parquet"
        df.to_parquet(parquet_path, index=False)
        
        # When: 틱바 백테스트 (100틱마다 바 생성)
        loader = TickDataLoader(tmp_path, symbol="BTCUSDT")
        strategy = OBIStrategy()
        
        runner = TickBacktestRunner(
            strategy=strategy,
            data_loader=loader,
            bar_type=BarType.TICK,
            bar_size=100,  # 100틱마다 바
        )
        
        report = runner.run(progress_interval=10000)
        
        # Then: 500틱 / 100 = 5개 바 예상
        assert runner.tick_count == 500
        assert runner.bar_count == 5
    
    def test_run_with_time_bar(self, tmp_path: Path):
        """시간바 기반 백테스트 실행"""
        # Given: 샘플 틱 데이터 (10초 분량)
        base_time = datetime.now()
        records = []
        
        for i in range(100):
            records.append({
                "timestamp": base_time + timedelta(milliseconds=i * 100),  # 100ms 간격
                "symbol": "BTCUSDT",
                "price": 50000.0,
                "quantity": 0.1,
                "is_buyer_maker": False,
            })
        
        df = pd.DataFrame(records)
        parquet_path = tmp_path / "BTCUSDT-aggTrades-test.parquet"
        df.to_parquet(parquet_path, index=False)
        
        # When: 시간바 백테스트 (1초마다 바 생성)
        loader = TickDataLoader(tmp_path, symbol="BTCUSDT")
        strategy = OBIStrategy()
        
        runner = TickBacktestRunner(
            strategy=strategy,
            data_loader=loader,
            bar_type=BarType.TIME,
            bar_size=1.0,  # 1초마다 바
        )
        
        report = runner.run(progress_interval=10000)
        
        # Then: 10초 / 1초 = 10개 바 예상
        assert runner.tick_count == 100
        assert runner.bar_count >= 9  # 마지막 바는 미완성일 수 있음


class TestBarBuilder:
    """Bar 및 BarBuilder 테스트"""
    
    def test_bar_volume_imbalance(self):
        """Bar의 volume_imbalance 계산 테스트"""
        from intraday.backtest.tick_runner import Bar
        
        # Given: 매수 주도 바
        buy_bar = Bar(
            timestamp=datetime.now(),
            open=50000,
            high=50100,
            low=49900,
            close=50050,
            volume=10.0,
            trade_count=100,
            buy_volume=8.0,
            sell_volume=2.0,
        )
        
        # Then: 양수 imbalance
        assert buy_bar.volume_imbalance == pytest.approx(0.6)  # (8-2)/(8+2) = 0.6
        
        # Given: 매도 주도 바
        sell_bar = Bar(
            timestamp=datetime.now(),
            open=50000,
            high=50100,
            low=49900,
            close=49950,
            volume=10.0,
            trade_count=100,
            buy_volume=3.0,
            sell_volume=7.0,
        )
        
        # Then: 음수 imbalance
        assert sell_bar.volume_imbalance == pytest.approx(-0.4)  # (3-7)/(3+7) = -0.4





