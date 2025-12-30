"""
CandleBuilder 테스트

사용자 관점:
    "틱 데이터를 원하는 단위(볼륨, 틱 수, 시간, 달러)로 캔들을 만들 수 있어야 한다"
"""

from datetime import datetime, timedelta

import pytest

from intraday import CandleBuilder, CandleType, Candle
from intraday.client import AggTrade


def make_trade(
    price: float,
    quantity: float,
    timestamp: datetime,
    is_buyer_maker: bool = False,
    symbol: str = "BTCUSDT",
) -> AggTrade:
    """테스트용 AggTrade 생성"""
    return AggTrade(
        timestamp=timestamp,
        symbol=symbol,
        price=price,
        quantity=quantity,
        is_buyer_maker=is_buyer_maker,
    )


class TestCandleType:
    """캔들 타입 기본 테스트"""
    
    def test_candle_type_values(self):
        """캔들 타입에 올바른 값이 있어야 한다"""
        assert CandleType.VOLUME.value == "volume"
        assert CandleType.TICK.value == "tick"
        assert CandleType.TIME.value == "time"
        assert CandleType.DOLLAR.value == "dollar"


class TestVolumeCandle:
    """볼륨 캔들 테스트: 특정 거래량마다 캔들이 생성되어야 한다"""
    
    def test_volume_candle_created_when_volume_threshold_reached(self):
        """10 BTC 거래되면 캔들이 생성되어야 한다"""
        # Given: 10 BTC 볼륨 캔들 빌더
        builder = CandleBuilder(CandleType.VOLUME, size=10.0)
        
        # When: 5 BTC + 5 BTC 틱 = 총 10 BTC
        trades = [
            make_trade(50000.0, 5.0, datetime(2024, 1, 1, 0, 0, 0), False),
            make_trade(50100.0, 5.0, datetime(2024, 1, 1, 0, 0, 1), True),
        ]
        
        candles = builder.build_from_trades(iter(trades))
        
        # Then: 캔들 1개 생성
        assert len(candles) == 1
        assert candles[0].volume >= 10.0
    
    def test_volume_candle_ohlc_correct(self):
        """OHLC가 올바르게 계산되어야 한다"""
        builder = CandleBuilder(CandleType.VOLUME, size=10.0)
        
        trades = [
            make_trade(50000.0, 3.0, datetime(2024, 1, 1, 0, 0, 0), False),  # Open
            make_trade(50500.0, 3.0, datetime(2024, 1, 1, 0, 0, 1), False),  # High
            make_trade(49500.0, 3.0, datetime(2024, 1, 1, 0, 0, 2), True),   # Low
            make_trade(50100.0, 3.0, datetime(2024, 1, 1, 0, 0, 3), True),   # Close
        ]
        
        candles = builder.build_from_trades(iter(trades))
        
        assert len(candles) == 1
        assert candles[0].open == 50000.0
        assert candles[0].high == 50500.0
        assert candles[0].low == 49500.0
        assert candles[0].close == 50100.0


class TestTickCandle:
    """틱 캔들 테스트: 특정 틱 수마다 캔들이 생성되어야 한다"""
    
    def test_tick_candle_created_when_tick_count_reached(self):
        """100틱마다 캔들이 생성되어야 한다"""
        builder = CandleBuilder(CandleType.TICK, size=100)
        
        # 100개 틱 생성
        trades = [
            make_trade(
                price=50000.0 + i,
                quantity=0.1,
                timestamp=datetime(2024, 1, 1, 0, 0, 0) + timedelta(seconds=i),
                is_buyer_maker=(i % 2 == 0),
            )
            for i in range(100)
        ]
        
        candles = builder.build_from_trades(iter(trades))
        
        assert len(candles) == 1
        assert candles[0].trade_count >= 100


class TestTimeCandle:
    """시간 캔들 테스트: 특정 시간마다 캔들이 생성되어야 한다"""
    
    def test_time_candle_created_every_60_seconds(self):
        """60초마다 캔들이 생성되어야 한다"""
        builder = CandleBuilder(CandleType.TIME, size=60)
        
        # 1분 30초 = 90초 동안의 틱 (10초 간격)
        trades = [
            make_trade(
                price=50000.0,
                quantity=1.0,
                timestamp=datetime(2024, 1, 1, 0, 0, 0) + timedelta(seconds=i * 10),
            )
            for i in range(10)  # 0, 10, 20, ..., 90초
        ]
        
        candles = builder.build_from_trades(iter(trades))
        
        # 60초가 지나면 첫 번째 캔들 생성
        assert len(candles) >= 1


class TestDollarCandle:
    """달러 캔들 테스트: 특정 달러 금액마다 캔들이 생성되어야 한다"""
    
    def test_dollar_candle_created_when_dollar_threshold_reached(self):
        """100만 달러 거래되면 캔들이 생성되어야 한다"""
        builder = CandleBuilder(CandleType.DOLLAR, size=1_000_000)
        
        # 50000 * 10 = 500,000 달러 씩 2개 = 1,000,000 달러
        trades = [
            make_trade(50000.0, 10.0, datetime(2024, 1, 1, 0, 0, 0), False),
            make_trade(50000.0, 10.0, datetime(2024, 1, 1, 0, 0, 1), True),
        ]
        
        candles = builder.build_from_trades(iter(trades))
        
        assert len(candles) == 1
        assert candles[0].quote_volume >= 1_000_000


class TestCandleBuilderStreamingMode:
    """
    스트리밍 모드 테스트
    
    사용자 관점:
        "백테스터에서 틱마다 update()를 호출하면 캔들 완성 시에만 반환해야 한다"
    """
    
    def test_update_returns_none_until_candle_complete(self):
        """캔들 완성 전까지는 None을 반환해야 한다"""
        builder = CandleBuilder(CandleType.VOLUME, size=10.0)
        
        # 5 BTC 틱 (아직 10 BTC 미달)
        trade1 = make_trade(50000.0, 5.0, datetime(2024, 1, 1, 0, 0, 0))
        
        result = builder.update(trade1)
        
        assert result is None  # 아직 캔들 미완성
    
    def test_update_returns_candle_when_complete(self):
        """캔들 완성 시 Candle 객체를 반환해야 한다"""
        builder = CandleBuilder(CandleType.VOLUME, size=10.0)
        
        # 첫 번째 틱: 5 BTC
        trade1 = make_trade(50000.0, 5.0, datetime(2024, 1, 1, 0, 0, 0))
        result1 = builder.update(trade1)
        assert result1 is None
        
        # 두 번째 틱: 5 BTC → 총 10 BTC → 캔들 완성
        trade2 = make_trade(50100.0, 5.0, datetime(2024, 1, 1, 0, 0, 1))
        result2 = builder.update(trade2)
        
        assert result2 is not None
        assert result2.volume >= 10.0
    
    def test_update_resets_after_candle_complete(self):
        """캔들 완성 후 새 캔들이 시작되어야 한다"""
        builder = CandleBuilder(CandleType.VOLUME, size=10.0)
        
        # 첫 번째 캔들 완성 (10 BTC)
        builder.update(make_trade(50000.0, 5.0, datetime(2024, 1, 1, 0, 0, 0)))
        candle1 = builder.update(make_trade(50100.0, 5.0, datetime(2024, 1, 1, 0, 0, 1)))
        assert candle1 is not None
        assert candle1.open == 50000.0  # 첫 번째 캔들 시작가
        assert candle1.close == 50100.0  # 첫 번째 캔들 종가
        
        # 새 캔들 시작 - reset() 후 다음 trade가 새 캔들의 시작
        result = builder.update(make_trade(50200.0, 5.0, datetime(2024, 1, 1, 0, 0, 2)))
        assert result is None  # 새 캔들 진행 중
        
        # 두 번째 캔들 완성 (10 BTC)
        candle2 = builder.update(make_trade(50300.0, 5.0, datetime(2024, 1, 1, 0, 0, 3)))
        assert candle2 is not None
        # 새 캔들은 reset() 후 첫 trade(50200)부터 시작
        assert candle2.open == 50200.0
        assert candle2.close == 50300.0
    
    def test_current_candle_property_shows_in_progress(self):
        """current_candle 속성으로 진행 중인 캔들을 확인할 수 있어야 한다"""
        builder = CandleBuilder(CandleType.VOLUME, size=10.0)
        
        # 아직 시작 전
        assert builder.current_candle is None
        
        # 틱 추가
        builder.update(make_trade(50000.0, 3.0, datetime(2024, 1, 1, 0, 0, 0)))
        
        # 진행 중인 캔들 확인
        in_progress = builder.current_candle
        assert in_progress is not None
        assert in_progress.volume == 3.0


class TestCandleProperties:
    """캔들 속성 테스트"""
    
    def test_vwap_calculation(self):
        """VWAP가 올바르게 계산되어야 한다"""
        candle = Candle(
            timestamp=datetime(2024, 1, 1),
            open=100.0,
            high=110.0,
            low=90.0,
            close=105.0,
            volume=10.0,
            quote_volume=1000.0,  # 10 * 100 평균
        )
        
        # VWAP = quote_volume / volume = 1000 / 10 = 100
        assert candle.vwap == 100.0
    
    def test_volume_imbalance_calculation(self):
        """볼륨 불균형이 올바르게 계산되어야 한다"""
        # 매수 8, 매도 2 → (8-2)/(8+2) = 0.6
        candle = Candle(
            timestamp=datetime(2024, 1, 1),
            open=100.0, high=100.0, low=100.0, close=100.0,
            volume=10.0,
            buy_volume=8.0,
            sell_volume=2.0,
        )
        
        assert candle.volume_imbalance == 0.6
    
    def test_bullish_candle(self):
        """양봉 판별이 정확해야 한다"""
        bullish = Candle(
            timestamp=datetime(2024, 1, 1),
            open=100.0, high=110.0, low=95.0, close=108.0,
            volume=10.0,
        )
        bearish = Candle(
            timestamp=datetime(2024, 1, 1),
            open=100.0, high=105.0, low=90.0, close=92.0,
            volume=10.0,
        )
        
        assert bullish.is_bullish is True
        assert bearish.is_bullish is False
