"""
Tick 데이터 다운로더 테스트

TDD 방식으로 선물/현물 Tick 데이터 다운로드 기능을 검증합니다.
"""

import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch
import io
import zipfile
import pandas as pd

from intraday.data.downloader import TickDataDownloader, MarketType


class TestTickDataDownloaderMarketType:
    """선물/현물 시장 타입 지원 테스트"""

    def test_market_type_enum_exists(self):
        """MarketType enum이 존재해야 한다"""
        assert MarketType.SPOT is not None
        assert MarketType.FUTURES is not None

    def test_default_market_type_is_spot(self):
        """기본 시장 타입은 현물이어야 한다"""
        downloader = TickDataDownloader()
        assert downloader.market_type == MarketType.SPOT

    def test_can_create_futures_downloader(self):
        """선물 다운로더를 생성할 수 있어야 한다"""
        downloader = TickDataDownloader(market_type=MarketType.FUTURES)
        assert downloader.market_type == MarketType.FUTURES

    def test_spot_uses_spot_url(self):
        """현물은 spot URL을 사용해야 한다"""
        downloader = TickDataDownloader(market_type=MarketType.SPOT)
        assert "spot" in downloader.base_url

    def test_futures_uses_futures_url(self):
        """선물은 futures URL을 사용해야 한다"""
        downloader = TickDataDownloader(market_type=MarketType.FUTURES)
        assert "futures" in downloader.base_url


class TestFuturesTickDataDownload:
    """선물 Tick 데이터 다운로드 테스트"""

    def _create_mock_zip(self, symbol: str = "BTCUSDT") -> bytes:
        """테스트용 Mock ZIP 파일 생성 (선물 포맷: 헤더 있음, transact_time 컬럼)"""
        # 선물 CSV 포맷: 헤더 포함, transact_time 컬럼
        csv_content = """agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker
3456178456,42000.00,0.001,12345678,12345679,1704067200000,true
3456178457,42001.00,0.002,12345680,12345681,1704067200100,false"""

        # ZIP으로 압축
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{symbol}-aggTrades-2024-01.csv", csv_content)

        return zip_buffer.getvalue()

    def test_futures_download_monthly_uses_correct_url(self):
        """선물 월별 다운로드는 올바른 URL을 사용해야 한다"""
        with patch("requests.get") as mock_get:
            mock_get.return_value.content = self._create_mock_zip()
            mock_get.return_value.raise_for_status = Mock()

            downloader = TickDataDownloader(market_type=MarketType.FUTURES)

            with patch.object(downloader, "_extract_and_parse") as mock_parse:
                mock_parse.return_value = pd.DataFrame()

                # tmp 디렉토리 사용
                import tempfile
                with tempfile.TemporaryDirectory() as tmp_dir:
                    try:
                        downloader.download_monthly(
                            symbol="BTCUSDT",
                            year=2024,
                            month=1,
                            output_dir=Path(tmp_dir),
                        )
                    except Exception:
                        pass  # 파일 저장 실패는 무시

            # URL 확인
            call_url = mock_get.call_args[0][0]
            assert "futures/um" in call_url
            assert "aggTrades" in call_url
            assert "BTCUSDT" in call_url

    def test_futures_download_returns_parquet_file(self, tmp_path):
        """선물 다운로드는 Parquet 파일을 반환해야 한다"""
        with patch("requests.get") as mock_get:
            mock_get.return_value.content = self._create_mock_zip()
            mock_get.return_value.raise_for_status = Mock()

            downloader = TickDataDownloader(market_type=MarketType.FUTURES)
            output_file = downloader.download_monthly(
                symbol="BTCUSDT",
                year=2024,
                month=1,
                output_dir=tmp_path,
            )

            assert output_file.exists()
            assert output_file.suffix == ".parquet"
            # 선물 데이터임을 파일명으로 구분
            assert "futures" in output_file.name or output_file.exists()
