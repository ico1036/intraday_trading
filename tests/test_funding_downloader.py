"""
Funding Rate 다운로더 테스트

TDD 방식으로 Funding Rate 다운로드 기능을 검증합니다.
"""

import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import json

from intraday.funding import FundingRate, FundingRateLoader


class TestFundingRateDownloader:
    """Funding Rate 다운로더 테스트"""

    def test_downloader_exists(self):
        """FundingRateDownloader 클래스가 존재해야 한다"""
        from intraday.data.funding_downloader import FundingRateDownloader

        downloader = FundingRateDownloader()
        assert downloader is not None

    def test_downloader_has_download_range_method(self):
        """download_range 메서드가 있어야 한다"""
        from intraday.data.funding_downloader import FundingRateDownloader

        downloader = FundingRateDownloader()
        assert hasattr(downloader, "download_range")

    def test_download_range_returns_funding_rate_list(self):
        """download_range는 FundingRate 리스트를 반환해야 한다"""
        from intraday.data.funding_downloader import FundingRateDownloader

        # Mock API 응답
        mock_response = [
            {
                "symbol": "BTCUSDT",
                "fundingTime": 1704067200000,  # 2024-01-01 00:00:00 UTC
                "fundingRate": "0.0001",
                "markPrice": "42000.00",
            },
            {
                "symbol": "BTCUSDT",
                "fundingTime": 1704096000000,  # 2024-01-01 08:00:00 UTC
                "fundingRate": "0.00015",
                "markPrice": "42500.00",
            },
        ]

        with patch("requests.get") as mock_get:
            mock_get.return_value.json.return_value = mock_response
            mock_get.return_value.raise_for_status = Mock()

            downloader = FundingRateDownloader()
            rates = downloader.download_range(
                symbol="BTCUSDT",
                start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
            )

            assert len(rates) == 2
            assert all(isinstance(r, FundingRate) for r in rates)

    def test_download_range_parses_funding_rate_correctly(self):
        """펀딩레이트 파싱이 정확해야 한다"""
        from intraday.data.funding_downloader import FundingRateDownloader

        mock_response = [
            {
                "symbol": "BTCUSDT",
                "fundingTime": 1704067200000,  # 2024-01-01 00:00:00 UTC
                "fundingRate": "0.0001",
                "markPrice": "42000.00",
            },
        ]

        with patch("requests.get") as mock_get:
            mock_get.return_value.json.return_value = mock_response
            mock_get.return_value.raise_for_status = Mock()

            downloader = FundingRateDownloader()
            rates = downloader.download_range(
                symbol="BTCUSDT",
                start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
            )

            rate = rates[0]
            assert rate.symbol == "BTCUSDT"
            assert rate.funding_rate == 0.0001
            assert rate.mark_price == 42000.0
            assert rate.timestamp == datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def test_download_range_uses_correct_api_endpoint(self):
        """올바른 API 엔드포인트를 사용해야 한다"""
        from intraday.data.funding_downloader import FundingRateDownloader

        with patch("requests.get") as mock_get:
            mock_get.return_value.json.return_value = []
            mock_get.return_value.raise_for_status = Mock()

            downloader = FundingRateDownloader()
            downloader.download_range(
                symbol="BTCUSDT",
                start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
            )

            # Binance Futures API 엔드포인트 확인
            call_url = mock_get.call_args[0][0]
            assert "fapi.binance.com" in call_url
            assert "fundingRate" in call_url

    def test_download_range_handles_pagination(self):
        """API 페이지네이션을 처리해야 한다"""
        from intraday.data.funding_downloader import FundingRateDownloader

        # 첫 번째 응답 (limit=1000개 가득)
        first_response = [
            {
                "symbol": "BTCUSDT",
                "fundingTime": 1704067200000 + i * 28800000,  # 8시간 간격
                "fundingRate": "0.0001",
                "markPrice": "42000.00",
            }
            for i in range(1000)
        ]

        # 두 번째 응답 (나머지)
        second_response = [
            {
                "symbol": "BTCUSDT",
                "fundingTime": 1704067200000 + 1000 * 28800000,
                "fundingRate": "0.0001",
                "markPrice": "42000.00",
            },
        ]

        with patch("requests.get") as mock_get:
            mock_response_1 = Mock()
            mock_response_1.json.return_value = first_response
            mock_response_1.raise_for_status = Mock()

            mock_response_2 = Mock()
            mock_response_2.json.return_value = second_response
            mock_response_2.raise_for_status = Mock()

            mock_get.side_effect = [mock_response_1, mock_response_2]

            downloader = FundingRateDownloader()
            rates = downloader.download_range(
                symbol="BTCUSDT",
                start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
            )

            # 총 1001개 반환
            assert len(rates) == 1001
            # 2번 호출됨
            assert mock_get.call_count == 2


class TestFundingRateDownloaderSaveLoad:
    """Funding Rate 저장/로드 테스트"""

    def test_save_to_parquet(self, tmp_path):
        """Parquet 파일로 저장할 수 있어야 한다"""
        from intraday.data.funding_downloader import FundingRateDownloader

        rates = [
            FundingRate(
                timestamp=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                funding_rate=0.0001,
                mark_price=42000.0,
            ),
            FundingRate(
                timestamp=datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                funding_rate=0.00015,
                mark_price=42500.0,
            ),
        ]

        downloader = FundingRateDownloader()
        output_file = downloader.save_to_parquet(rates, tmp_path)

        assert output_file.exists()
        assert output_file.suffix == ".parquet"

    def test_load_from_parquet(self, tmp_path):
        """Parquet 파일에서 로드할 수 있어야 한다"""
        from intraday.data.funding_downloader import FundingRateDownloader

        rates = [
            FundingRate(
                timestamp=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                funding_rate=0.0001,
                mark_price=42000.0,
            ),
            FundingRate(
                timestamp=datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                funding_rate=0.00015,
                mark_price=42500.0,
            ),
        ]

        downloader = FundingRateDownloader()
        output_file = downloader.save_to_parquet(rates, tmp_path)

        # 로드
        loaded_rates = downloader.load_from_parquet(output_file)

        assert len(loaded_rates) == 2
        assert loaded_rates[0].funding_rate == 0.0001
        assert loaded_rates[1].funding_rate == 0.00015

    def test_load_returns_funding_rate_loader(self, tmp_path):
        """로드 결과로 FundingRateLoader를 반환할 수 있어야 한다"""
        from intraday.data.funding_downloader import FundingRateDownloader

        rates = [
            FundingRate(
                timestamp=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                funding_rate=0.0001,
                mark_price=42000.0,
            ),
        ]

        downloader = FundingRateDownloader()
        output_file = downloader.save_to_parquet(rates, tmp_path)

        # FundingRateLoader로 로드
        loader = downloader.load_as_loader(output_file)

        assert isinstance(loader, FundingRateLoader)
        assert len(loader) == 1
