"""
Funding Rate 모듈

선물 거래의 Funding Rate 정산 기능을 제공합니다.

교육 포인트:
    - Funding Rate: 선물 가격과 현물 가격을 수렴시키기 위한 메커니즘
    - 8시간마다 정산 (00:00, 08:00, 16:00 UTC)
    - 양수 펀딩레이트: 롱이 숏에게 지불
    - 음수 펀딩레이트: 숏이 롱에게 지불
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .strategy import Side


@dataclass
class FundingRate:
    """
    Funding Rate 데이터

    Attributes:
        timestamp: 정산 시간 (UTC)
        symbol: 거래쌍
        funding_rate: 펀딩레이트 (예: 0.0001 = 0.01%)
        mark_price: 마크 가격 (정산 기준가)

    교육 포인트:
        - funding_rate는 보통 -0.01% ~ 0.01% 범위
        - 극단적 시장에서는 더 크게 변동
        - 연환산 시 × 3 × 365 (8시간마다 3번, 365일)
    """

    timestamp: datetime
    symbol: str
    funding_rate: float
    mark_price: float

    @property
    def annual_rate(self) -> float:
        """
        연환산 이율

        Returns:
            연간 예상 이율 (예: 0.1095 = 10.95%)
        """
        return self.funding_rate * 3 * 365


class FundingSettlement:
    """
    Funding 정산 로직

    교육 포인트:
        - Binance 기준 00:00, 08:00, 16:00 UTC에 정산
        - 정산 시점에 포지션을 보유한 경우에만 적용
        - 정산 금액 = 포지션 크기 × 마크 가격 × 펀딩레이트
    """

    FUNDING_HOURS = [0, 8, 16]

    def is_funding_time(self, timestamp: datetime) -> bool:
        """
        정산 시간인지 확인

        Args:
            timestamp: 확인할 시간 (UTC)

        Returns:
            True: 정산 시간
            False: 정산 시간 아님
        """
        # UTC로 변환
        if timestamp.tzinfo is None:
            ts = timestamp.replace(tzinfo=timezone.utc)
        else:
            ts = timestamp.astimezone(timezone.utc)

        return ts.hour in self.FUNDING_HOURS and ts.minute == 0

    def should_settle(self, current: datetime, last_settlement: datetime) -> bool:
        """
        정산해야 하는지 확인

        Args:
            current: 현재 시간
            last_settlement: 마지막 정산 확인 시간

        Returns:
            True: 정산 필요
            False: 정산 불필요

        교육 포인트:
            - 정산 시간을 지났으면 정산 필요
            - 같은 정산 기간 내에서는 중복 정산 방지
        """
        # UTC로 변환
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        else:
            current = current.astimezone(timezone.utc)

        if last_settlement.tzinfo is None:
            last_settlement = last_settlement.replace(tzinfo=timezone.utc)
        else:
            last_settlement = last_settlement.astimezone(timezone.utc)

        # 각 시간의 정산 기간 인덱스 계산 (0, 1, 2)
        def get_period_index(dt: datetime) -> tuple[int, int]:
            """(날짜 기준 일수, 정산 기간 인덱스)"""
            days = (dt - datetime(2020, 1, 1, tzinfo=timezone.utc)).days
            hour = dt.hour
            if hour < 8:
                period = 0
            elif hour < 16:
                period = 1
            else:
                period = 2
            return (days, period)

        current_period = get_period_index(current)
        last_period = get_period_index(last_settlement)

        return current_period > last_period

    def calculate_payment(
        self,
        position_side: Side,
        position_size: float,
        mark_price: float,
        funding_rate: float,
    ) -> float:
        """
        Funding 정산 금액 계산

        Args:
            position_side: 포지션 방향
            position_size: 포지션 크기 (BTC 등)
            mark_price: 마크 가격
            funding_rate: 펀딩레이트

        Returns:
            정산 금액 (양수: 수취, 음수: 지불)

        교육 포인트:
            - 롱 + 양수 펀딩 = 지불 (숏에게)
            - 숏 + 양수 펀딩 = 수취 (롱에서)
            - 롱 + 음수 펀딩 = 수취 (숏에서)
            - 숏 + 음수 펀딩 = 지불 (롱에게)
        """
        notional = position_size * mark_price
        payment = notional * funding_rate

        if position_side == Side.BUY:
            # 롱: 양수 펀딩레이트면 지불
            return -payment
        else:
            # 숏: 양수 펀딩레이트면 수취
            return payment


class FundingRateLoader:
    """
    Funding Rate 데이터 로더

    히스토리컬 펀딩레이트 데이터를 로드하고 조회합니다.
    """

    def __init__(self, rates: list[FundingRate]):
        """
        Args:
            rates: 펀딩레이트 리스트 (시간순 정렬 권장)
        """
        self._rates = sorted(rates, key=lambda r: r.timestamp)
        self._rate_map: dict[datetime, FundingRate] = {r.timestamp: r for r in rates}

    @classmethod
    def from_list(cls, rates: list[FundingRate]) -> "FundingRateLoader":
        """리스트에서 로더 생성"""
        return cls(rates)

    def __len__(self) -> int:
        return len(self._rates)

    def get_rate_at(self, timestamp: datetime) -> Optional[FundingRate]:
        """
        특정 시간의 펀딩레이트 조회

        Args:
            timestamp: 조회할 시간

        Returns:
            FundingRate 또는 None
        """
        # 정확히 일치하는 시간 찾기
        return self._rate_map.get(timestamp)

    def get_latest_rate_before(self, timestamp: datetime) -> Optional[FundingRate]:
        """
        특정 시간 이전의 최신 펀딩레이트 조회

        Args:
            timestamp: 기준 시간

        Returns:
            가장 최근 FundingRate 또는 None
        """
        # timezone 통일 (naive -> UTC)
        if timestamp.tzinfo is None:
            ts = timestamp.replace(tzinfo=timezone.utc)
        else:
            ts = timestamp.astimezone(timezone.utc)

        result = None
        for rate in self._rates:
            rate_ts = rate.timestamp
            if rate_ts.tzinfo is None:
                rate_ts = rate_ts.replace(tzinfo=timezone.utc)

            if rate_ts <= ts:
                result = rate
            else:
                break
        return result

    def iter_rates(
        self, start: Optional[datetime] = None, end: Optional[datetime] = None
    ):
        """
        시간 범위 내 펀딩레이트 이터레이터

        Args:
            start: 시작 시간 (포함)
            end: 종료 시간 (포함)

        Yields:
            FundingRate
        """
        for rate in self._rates:
            if start and rate.timestamp < start:
                continue
            if end and rate.timestamp > end:
                break
            yield rate
