"""
데이터 파이프라인 테스트 (사용자 관점)

"이 기능은 이렇게 작동해야 한다"는 철학으로 작성된 테스트입니다.

테스트 철학:
    - Mockup 데이터 사용 금지 (실제 형식의 데이터 사용)
    - 통과를 위한 테스트 금지 (실제 기능 검증)
    - 클라이언트 입장에서 "이게 되면 이게 나와야 한다" 베이스
"""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from intraday import (
    AggTrade,
    OrderbookSnapshot,
    TickDataLoader,
    OrderbookDataLoader,
)


class TestTickDataLoader:
    """
    TickDataLoader 사용자 관점 테스트
    
    사용자 시나리오:
        "Binance Public Data 형식의 CSV/Parquet 파일을 로드하면
        AggTrade 객체를 시간순으로 받을 수 있어야 한다"
    """
    
    def test_binance_aggtrades_format_should_be_parsed_correctly(self, tmp_path: Path):
        """
        Binance aggTrades CSV 형식의 데이터를 올바르게 파싱해야 한다
        
        Given: Binance Public Data 형식의 aggTrades 데이터
               (agg_trade_id, price, quantity, first_trade_id, last_trade_id, 
                timestamp, is_buyer_maker, is_best_match, symbol)
        When: TickDataLoader로 로드
        Then: 각 필드가 AggTrade 객체로 올바르게 변환됨
        """
        # Given: Binance 형식의 데이터
        data = {
            "agg_trade_id": [12345, 12346, 12347],
            "price": [50000.50, 50001.00, 49999.75],
            "quantity": [0.5, 0.25, 1.0],
            "first_trade_id": [100, 101, 102],
            "last_trade_id": [100, 101, 103],
            "timestamp": [
                datetime(2024, 1, 15, 10, 0, 0),
                datetime(2024, 1, 15, 10, 0, 1),
                datetime(2024, 1, 15, 10, 0, 2),
            ],
            "is_buyer_maker": [False, True, False],  # False=매수주도, True=매도주도
            "is_best_match": [True, True, True],
            "symbol": ["BTCUSDT", "BTCUSDT", "BTCUSDT"],
        }
        df = pd.DataFrame(data)
        filepath = tmp_path / "BTCUSDT-aggTrades-2024-01.parquet"
        df.to_parquet(filepath, index=False)
        
        # When: 로더로 데이터 로드
        loader = TickDataLoader(tmp_path, symbol="BTCUSDT")
        trades = list(loader.iter_trades())
        
        # Then: AggTrade 객체로 올바르게 변환됨
        assert len(trades) == 3
        
        # 첫 번째 거래 검증
        first = trades[0]
        assert isinstance(first, AggTrade)
        assert first.price == 50000.50
        assert first.quantity == 0.5
        assert first.is_buyer_maker == False  # 매수 주도
        assert first.symbol == "BTCUSDT"
    
    def test_trades_should_be_sorted_by_timestamp(self, tmp_path: Path):
        """
        거래는 시간순으로 정렬되어 반환되어야 한다
        
        Given: 시간 순서가 뒤섞인 거래 데이터
        When: TickDataLoader로 로드
        Then: 시간순으로 정렬된 AggTrade 반환
        """
        # Given: 시간 순서 뒤섞인 데이터
        data = {
            "timestamp": [
                datetime(2024, 1, 15, 10, 0, 2),  # 세 번째
                datetime(2024, 1, 15, 10, 0, 0),  # 첫 번째
                datetime(2024, 1, 15, 10, 0, 1),  # 두 번째
            ],
            "price": [100.0, 200.0, 300.0],  # 가격으로 순서 확인
            "quantity": [1.0, 1.0, 1.0],
            "is_buyer_maker": [False, False, False],
            "symbol": ["BTCUSDT", "BTCUSDT", "BTCUSDT"],
        }
        df = pd.DataFrame(data)
        filepath = tmp_path / "BTCUSDT-aggTrades-test.parquet"
        df.to_parquet(filepath, index=False)
        
        # When
        loader = TickDataLoader(tmp_path, symbol="BTCUSDT")
        trades = list(loader.iter_trades())
        
        # Then: 시간순 (200 → 300 → 100)
        assert trades[0].price == 200.0  # 가장 이른 시간
        assert trades[1].price == 300.0
        assert trades[2].price == 100.0  # 가장 늦은 시간
    
    def test_time_filter_should_work(self, tmp_path: Path):
        """
        시간 필터가 정확히 작동해야 한다
        
        Given: 1시간 분량의 거래 데이터
        When: 특정 10분 구간만 필터링
        Then: 해당 구간의 데이터만 반환
        """
        # Given: 1시간 분량 데이터 (1분 간격 60개)
        base = datetime(2024, 1, 15, 10, 0, 0)
        data = {
            "timestamp": [base + timedelta(minutes=i) for i in range(60)],
            "price": [50000 + i for i in range(60)],
            "quantity": [0.1] * 60,
            "is_buyer_maker": [False] * 60,
            "symbol": ["BTCUSDT"] * 60,
        }
        df = pd.DataFrame(data)
        filepath = tmp_path / "BTCUSDT-aggTrades-test.parquet"
        df.to_parquet(filepath, index=False)
        
        # When: 10:15 ~ 10:25 구간만 필터
        loader = TickDataLoader(tmp_path, symbol="BTCUSDT")
        start = datetime(2024, 1, 15, 10, 15, 0)
        end = datetime(2024, 1, 15, 10, 25, 0)
        trades = list(loader.iter_trades(start_time=start, end_time=end))
        
        # Then: 15~25분 사이의 11개 데이터만 반환
        assert len(trades) == 11  # 15, 16, ..., 25
        assert all(start <= t.timestamp <= end for t in trades)


class TestOrderbookDataLoader:
    """
    OrderbookDataLoader 사용자 관점 테스트
    
    사용자 시나리오:
        "저장된 오더북 스냅샷 파일을 로드하면
        OrderbookSnapshot 객체를 시간순으로 받을 수 있어야 한다"
    """
    
    def test_flat_parquet_should_be_restored_to_orderbook_snapshot(self, tmp_path: Path):
        """
        플랫 구조로 저장된 Parquet이 OrderbookSnapshot으로 복원되어야 한다
        
        Given: bid_price_0, bid_qty_0, ... 형태로 저장된 플랫 데이터
        When: OrderbookDataLoader로 로드
        Then: bids=[(price, qty), ...] 형태의 OrderbookSnapshot으로 복원
        """
        # Given: OrderbookRecorder가 저장하는 플랫 형식
        ts = datetime(2024, 1, 15, 10, 0, 0)
        record = {
            "timestamp": ts,
            "last_update_id": 12345,
            "symbol": "BTCUSDT",
        }
        
        # 20레벨 호가 (실제 바이낸스 depth20과 동일)
        for i in range(20):
            record[f"bid_price_{i}"] = 50000.0 - i * 0.1  # 50000, 49999.9, ...
            record[f"bid_qty_{i}"] = 1.0 + i * 0.1
            record[f"ask_price_{i}"] = 50000.1 + i * 0.1  # 50000.1, 50000.2, ...
            record[f"ask_qty_{i}"] = 1.0 + i * 0.1
        
        df = pd.DataFrame([record])
        filepath = tmp_path / "orderbook_btcusdt_test.parquet"
        df.to_parquet(filepath, index=False)
        
        # When
        loader = OrderbookDataLoader(tmp_path, symbol="btcusdt")
        snapshots = list(loader.iter_snapshots())
        
        # Then
        assert len(snapshots) == 1
        snapshot = snapshots[0]
        
        assert isinstance(snapshot, OrderbookSnapshot)
        assert len(snapshot.bids) == 20
        assert len(snapshot.asks) == 20
        
        # Best bid/ask 검증
        assert snapshot.bids[0] == (50000.0, 1.0)  # 최고 매수가
        assert snapshot.asks[0] == (50000.1, 1.0)  # 최저 매도가
        
        # 정렬 검증: bids는 내림차순, asks는 오름차순
        assert snapshot.bids[0][0] > snapshot.bids[1][0]  # bid 내림차순
        assert snapshot.asks[0][0] < snapshot.asks[1][0]  # ask 오름차순
    
    def test_orderbook_imbalance_should_be_calculable(self, tmp_path: Path):
        """
        로드된 OrderbookSnapshot으로 imbalance를 계산할 수 있어야 한다
        
        Given: 매수 물량이 매도 물량보다 많은 오더북
        When: OrderbookDataLoader로 로드 후 imbalance 계산
        Then: 양수 imbalance 값
        """
        # Given: 매수 물량 > 매도 물량
        ts = datetime.now()
        record = {
            "timestamp": ts,
            "last_update_id": 1,
            "symbol": "BTCUSDT",
        }
        
        # Best level만 설정 (매수 10, 매도 2)
        record["bid_price_0"] = 50000.0
        record["bid_qty_0"] = 10.0  # 매수 물량 많음
        record["ask_price_0"] = 50001.0
        record["ask_qty_0"] = 2.0   # 매도 물량 적음
        
        # 나머지 레벨 채우기
        for i in range(1, 20):
            record[f"bid_price_{i}"] = 50000.0 - i
            record[f"bid_qty_{i}"] = 1.0
            record[f"ask_price_{i}"] = 50001.0 + i
            record[f"ask_qty_{i}"] = 1.0
        
        df = pd.DataFrame([record])
        filepath = tmp_path / "orderbook_btcusdt_test.parquet"
        df.to_parquet(filepath, index=False)
        
        # When
        loader = OrderbookDataLoader(tmp_path, symbol="btcusdt")
        snapshot = next(loader.iter_snapshots())
        
        # Then: imbalance 계산 가능
        bid_qty = snapshot.bids[0][1]
        ask_qty = snapshot.asks[0][1]
        imbalance = (bid_qty - ask_qty) / (bid_qty + ask_qty)
        
        assert imbalance == pytest.approx((10 - 2) / (10 + 2))  # 0.667
        assert imbalance > 0  # 매수 압력 강함


class TestDataPipelineIntegration:
    """
    데이터 파이프라인 통합 테스트
    
    사용자 시나리오:
        "저장 → 로드의 전체 파이프라인이 데이터 무결성을 보장해야 한다"
    """
    
    def test_tick_data_roundtrip_preserves_all_fields(self, tmp_path: Path):
        """
        틱 데이터 저장 → 로드 시 모든 필드가 보존되어야 한다
        
        Given: 원본 틱 데이터
        When: Parquet로 저장 후 로드
        Then: 모든 필드 값이 동일
        """
        # Given: 원본 데이터
        original = {
            "timestamp": datetime(2024, 1, 15, 10, 30, 45, 123000),
            "price": 50123.456789,  # 소수점 정밀도
            "quantity": 0.00001234,  # 작은 수량
            "is_buyer_maker": True,
            "symbol": "BTCUSDT",
        }
        
        df = pd.DataFrame([original])
        filepath = tmp_path / "BTCUSDT-test.parquet"
        df.to_parquet(filepath, index=False)
        
        # When
        loader = TickDataLoader(tmp_path, symbol="BTCUSDT")
        loaded = next(loader.iter_trades())
        
        # Then: 모든 필드 보존
        assert loaded.price == pytest.approx(original["price"])
        assert loaded.quantity == pytest.approx(original["quantity"])
        assert loaded.is_buyer_maker == original["is_buyer_maker"]
        assert loaded.symbol == original["symbol"]
    
    def test_orderbook_data_roundtrip_preserves_price_levels(self, tmp_path: Path):
        """
        오더북 데이터 저장 → 로드 시 모든 호가 레벨이 보존되어야 한다
        
        Given: 20레벨 오더북 스냅샷
        When: 플랫 구조로 저장 후 로드
        Then: 20레벨 모두 정확히 복원
        """
        # Given: 원본 호가 레벨
        ts = datetime.now()
        original_bids = [(50000 - i * 0.5, 1.0 + i * 0.01) for i in range(20)]
        original_asks = [(50000.5 + i * 0.5, 2.0 + i * 0.01) for i in range(20)]
        
        record = {"timestamp": ts, "last_update_id": 999, "symbol": "BTCUSDT"}
        for i, (price, qty) in enumerate(original_bids):
            record[f"bid_price_{i}"] = price
            record[f"bid_qty_{i}"] = qty
        for i, (price, qty) in enumerate(original_asks):
            record[f"ask_price_{i}"] = price
            record[f"ask_qty_{i}"] = qty
        
        df = pd.DataFrame([record])
        filepath = tmp_path / "orderbook_btcusdt_test.parquet"
        df.to_parquet(filepath, index=False)
        
        # When
        loader = OrderbookDataLoader(tmp_path, symbol="btcusdt")
        loaded = next(loader.iter_snapshots())
        
        # Then: 모든 레벨 정확히 보존
        assert len(loaded.bids) == 20
        assert len(loaded.asks) == 20
        
        for i in range(20):
            assert loaded.bids[i][0] == pytest.approx(original_bids[i][0])
            assert loaded.bids[i][1] == pytest.approx(original_bids[i][1])
            assert loaded.asks[i][0] == pytest.approx(original_asks[i][0])
            assert loaded.asks[i][1] == pytest.approx(original_asks[i][1])





