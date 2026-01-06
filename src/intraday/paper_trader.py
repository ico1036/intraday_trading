"""
PaperTrader 모듈

가상 거래 시뮬레이터를 제공합니다.
교육 목적으로 상세한 주석을 포함합니다.
"""

import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from .strategy import Side, OrderType, Order


@dataclass
class Trade:
    """
    체결된 거래 기록
    
    Attributes:
        timestamp: 체결 시간
        side: 거래 방향 (BUY/SELL)
        price: 체결 가격
        quantity: 체결 수량
        fee: 수수료
        pnl: 이 거래의 손익 (청산 시에만 계산됨)
    
    교육 포인트:
        - 진입 거래의 pnl은 0
        - 청산 거래의 pnl은 (청산가 - 진입가) * 수량 - 수수료
    """
    timestamp: datetime
    side: Side
    price: float
    quantity: float
    fee: float
    pnl: float = 0.0


@dataclass
class Position:
    """
    현재 포지션

    Attributes:
        side: 포지션 방향 (None이면 포지션 없음)
        quantity: 포지션 수량
        entry_price: 진입 가격
        unrealized_pnl: 미실현 손익
        leverage: 레버리지 배율 (1=현물, 2+=선물)
        liquidation_price: 청산가 (선물 전용, 현물은 None)
        margin: 포지션에 할당된 마진 (선물 전용)

    교육 포인트:
        - 미실현 손익은 현재 가격 기준 예상 손익
        - 실제 청산 시 실현 손익과 다를 수 있음
        - 선물 거래에서 leverage > 1이면 청산가가 설정됨
        - 청산가에 도달하면 포지션이 강제 청산됨
    """
    side: Optional[Side] = None
    quantity: float = 0.0
    entry_price: float = 0.0
    unrealized_pnl: float = 0.0
    # 선물 거래 필드 (현물에서는 기본값 사용)
    leverage: int = 1
    liquidation_price: Optional[float] = None
    margin: float = 0.0


@dataclass
class PendingOrder:
    """
    대기 중인 주문 (큐에 저장되는 단위)
    
    Attributes:
        order_id: 고유 주문 ID
        order: 주문 정보
        submitted_at: 제출 시간
        expires_at: 만료 시간 (None이면 만료 없음)
    """
    order_id: str
    order: Order
    submitted_at: datetime
    expires_at: Optional[datetime] = None


class PaperTrader:
    """
    가상 거래 시뮬레이터

    실제 거래소에 주문을 보내지 않고 가상으로 거래를 시뮬레이션합니다.
    포워드 테스트와 백테스트에서 동일하게 사용할 수 있습니다.

    교육 포인트:
        - 실제 거래 전에 전략을 검증하는 데 필수
        - 수수료, 슬리피지 등을 시뮬레이션
        - 실제 체결과 다를 수 있음 (특히 유동성 부족 시)

    주문 큐:
        - 여러 주문을 동시에 대기열에 저장 가능
        - FIFO 순서로 체결
        - TTL 지원 (만료 시간)
        - 주문 취소 가능

    잔고 관리:
        - usd_balance: 현재 USD 잔고 (Quant가 조회 가능)
        - btc_balance: 현재 BTC 잔고 (Quant가 조회 가능)
        - 잔고 부족 시 주문 자동 거부

    선물 거래:
        - leverage > 1이면 선물 모드 활성화
        - 마진 기반 거래, 공매도 가능
        - 청산가 자동 계산 및 청산 처리
    """

    # Binance BTCUSDT 선물 유지마진율 (Maintenance Margin Rate)
    # 포지션 크기에 따라 다르지만, 단순화를 위해 소규모 포지션 기준 사용
    MAINTENANCE_MARGIN_RATE = 0.004  # 0.4%

    def __init__(
        self,
        initial_capital: float,
        fee_rate: float = 0.001,
        leverage: int = 1,
    ):
        """
        Args:
            initial_capital: 초기 자본금 (USD)
            fee_rate: 수수료율 (기본 0.1% = 0.001)
            leverage: 레버리지 배율 (1=현물, 2+=선물)

        교육 포인트:
            - Binance 기본 수수료: 현물 0.1%, 선물 0.04% (taker)
            - 수수료는 왕복으로 발생 (진입 + 청산)
            - leverage=1: 현물 모드 (기존 동작)
            - leverage>1: 선물 모드 (마진 거래, 청산 있음)
        """
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.leverage = leverage
        self.capital = initial_capital

        # 잔고 관리 (Information Hiding: property로만 노출)
        self._usd_balance = initial_capital
        self._btc_balance = 0.0

        self._position = Position()
        self._pending_orders: deque[PendingOrder] = deque()  # 주문 큐 (FIFO 최적화)
        self._trades: list[Trade] = []
        self._realized_pnl: float = 0.0
        self._entry_fee: float = 0.0  # 진입 시 수수료 저장

    @property
    def is_futures_mode(self) -> bool:
        """선물 모드 여부"""
        return self.leverage > 1
    
    @property
    def position(self) -> Position:
        """현재 포지션"""
        return self._position
    
    @property
    def usd_balance(self) -> float:
        """
        현재 USD 잔고
        
        Quant 연구원이 조회할 수 있는 인터페이스입니다.
        내부 구현은 숨겨집니다 (Information Hiding).
        
        Returns:
            현재 보유 USD
        """
        return self._usd_balance
    
    @property
    def btc_balance(self) -> float:
        """
        현재 BTC 잔고
        
        Quant 연구원이 조회할 수 있는 인터페이스입니다.
        내부 구현은 숨겨집니다 (Information Hiding).
        
        Returns:
            현재 보유 BTC
        """
        return self._btc_balance
    
    @property
    def realized_pnl(self) -> float:
        """실현 손익"""
        return self._realized_pnl
    
    @property
    def total_pnl(self) -> float:
        """총 손익 (실현 + 미실현)"""
        return self._realized_pnl + self._position.unrealized_pnl
    
    @property
    def trades(self) -> list[Trade]:
        """체결 기록"""
        return self._trades.copy()
    
    @property
    def pending_orders(self) -> list[PendingOrder]:
        """대기 중인 주문 목록"""
        return list(self._pending_orders)  # deque를 list로 변환하여 반환
    
    def submit_order(
        self,
        order: Order,
        ttl_seconds: Optional[float] = None,
        timestamp: Optional[datetime] = None,
    ) -> str:
        """
        주문 제출
        
        Args:
            order: 제출할 주문
            ttl_seconds: 주문 유효 시간 (초). None이면 만료 없음
            timestamp: 주문 제출 시간 (백테스트용). None이면 현재 시간
        
        Returns:
            order_id: 주문 ID (취소 시 사용)
        
        교육 포인트:
            - 주문은 대기열에 저장됨
            - 다음 가격 업데이트에서 체결 여부 판단
            - TTL을 설정하면 시간 경과 후 자동 만료
            - 백테스트 시 timestamp를 전달하여 시뮬레이션 시간 사용
        """
        order_id = str(uuid.uuid4())[:8]
        now = timestamp if timestamp is not None else datetime.now()
        
        expires_at = None
        if ttl_seconds is not None:
            expires_at = now + timedelta(seconds=ttl_seconds)
        
        pending = PendingOrder(
            order_id=order_id,
            order=order,
            submitted_at=now,
            expires_at=expires_at,
        )
        
        self._pending_orders.append(pending)
        return order_id
    
    def cancel_order(self, order_id: str) -> bool:
        """
        주문 취소
        
        Args:
            order_id: 취소할 주문 ID
        
        Returns:
            True: 취소 성공
            False: 주문을 찾을 수 없음
        
        Note:
            deque는 중간 삭제를 지원하지 않으므로, 해당 주문을 제외한 새 deque를 생성합니다.
        """
        found = False
        new_orders = deque()
        for pending in self._pending_orders:
            if pending.order_id == order_id:
                found = True
            else:
                new_orders.append(pending)
        
        if found:
            self._pending_orders = new_orders
        return found
    
    def cancel_all_orders(self) -> int:
        """
        모든 주문 취소
        
        Returns:
            취소된 주문 수
        """
        count = len(self._pending_orders)
        self._pending_orders.clear()
        return count
    
    def cancel_orders_by_side(self, side: Side) -> int:
        """
        방향별 주문 취소
        
        Args:
            side: 취소할 주문 방향 (BUY/SELL)
        
        Returns:
            취소된 주문 수
        """
        before = len(self._pending_orders)
        self._pending_orders = deque([
            po for po in self._pending_orders if po.order.side != side
        ])
        return before - len(self._pending_orders)
    
    def expire_orders(self, current_time: Optional[datetime] = None) -> int:
        """
        만료된 주문 제거
        
        Args:
            current_time: 현재 시간 (테스트용, None이면 datetime.now())
        
        Returns:
            만료된 주문 수
        """
        now = current_time or datetime.now()
        before = len(self._pending_orders)
        
        self._pending_orders = deque([
            po for po in self._pending_orders
            if po.expires_at is None or po.expires_at > now
        ])
        
        return before - len(self._pending_orders)
    
    def on_price_update(
        self,
        price: float,
        best_bid: float,
        best_ask: float,
        timestamp: datetime,
        latency_ms: float = 0.0,
    ) -> Optional[Trade]:
        """
        가격 업데이트 시 체결 확인 (첫 번째 주문만)

        Args:
            price: 현재 시장 가격 (체결 판단용, 선물에서는 청산 체크용)
            best_bid: 최고 매수 호가
            best_ask: 최저 매도 호가
            timestamp: 현재 시간
            latency_ms: 주문 전송 지연 시간 (밀리초).
                        주문 제출 후 이 시간이 지나야 체결 시도.
                        백테스트에서 현실적인 지연 시뮬레이션에 사용.

        Returns:
            Trade: 체결된 거래 (체결 시)
            None: 체결 없음

        교육 포인트:
            - MARKET BUY: best_ask에 즉시 체결
            - MARKET SELL: best_bid에 즉시 체결
            - LIMIT BUY: price <= limit_price 시 체결
            - LIMIT SELL: price >= limit_price 시 체결
            - latency_ms > 0: 주문 제출 후 지연 시간이 지나야 체결 가능
            - 선물 모드: 청산 조건 확인 후 포지션 강제 청산

        Note:
            하위 호환성을 위해 첫 번째 주문만 체결합니다.
            여러 주문을 한 번에 체결하려면 on_price_update_all()을 사용하세요.
        """
        # 선물 모드: 청산 체크 (주문 처리 전에 먼저 확인)
        if self._check_liquidation(price):
            self._execute_liquidation(price, timestamp)
            # 청산 후 대기 주문 모두 취소
            self.cancel_all_orders()
            return None

        # 만료된 주문 제거
        self.expire_orders(timestamp)
        
        if not self._pending_orders:
            return None
        
        pending = self._pending_orders[0]
        order = pending.order
        trade: Optional[Trade] = None
        
        # Latency 조건 확인: 주문 제출 후 충분한 시간이 지났는지
        if latency_ms > 0:
            elapsed_ms = (timestamp - pending.submitted_at).total_seconds() * 1000
            if elapsed_ms < latency_ms:
                # 아직 지연 시간이 지나지 않음 - 체결 불가
                return None
        
        should_remove = False
        
        if order.order_type == OrderType.MARKET:
            # MARKET 주문: 즉시 체결 시도
            if order.side == Side.BUY:
                trade = self._execute_trade(order, best_ask, timestamp)
            else:
                trade = self._execute_trade(order, best_bid, timestamp)
            # MARKET 주문은 성공/실패 관계없이 제거 (재시도 없음)
            should_remove = True
        
        elif order.order_type == OrderType.LIMIT:
            # LIMIT 주문: 조건 충족 시 체결
            if order.side == Side.BUY and price <= order.limit_price:
                trade = self._execute_trade(order, order.limit_price, timestamp)
                # 체결 시도됨 (성공/잔고부족 관계없이 제거)
                should_remove = True
            elif order.side == Side.SELL and price >= order.limit_price:
                trade = self._execute_trade(order, order.limit_price, timestamp)
                should_remove = True
            # 조건 미충족: 주문 유지 (should_remove = False)
        
        if should_remove:
            self._pending_orders.popleft()  # O(1) - deque 최적화
        
        return trade
    
    def on_price_update_all(
        self,
        price: float,
        best_bid: float,
        best_ask: float,
        timestamp: datetime,
        latency_ms: float = 0.0,
    ) -> list[Trade]:
        """
        가격 업데이트 시 모든 체결 가능한 주문 처리

        Args:
            price: 현재 시장 가격 (체결 판단용)
            best_bid: 최고 매수 호가
            best_ask: 최저 매도 호가
            timestamp: 현재 시간
            latency_ms: 주문 전송 지연 시간 (밀리초)

        Returns:
            체결된 거래 목록

        교육 포인트:
            - Market Making 등에서 양방향 주문 동시 체결에 유용
            - latency_ms > 0: 주문 제출 후 지연 시간이 지나야 체결 가능
            - 선물 모드: 청산 조건 확인 후 포지션 강제 청산
        """
        # 선물 모드: 청산 체크 (주문 처리 전에 먼저 확인)
        if self._check_liquidation(price):
            self._execute_liquidation(price, timestamp)
            # 청산 후 대기 주문 모두 취소
            self.cancel_all_orders()
            return []

        # 만료된 주문 제거
        self.expire_orders(timestamp)
        
        trades: list[Trade] = []
        remaining: deque[PendingOrder] = deque()
        
        for pending in self._pending_orders:
            order = pending.order
            trade: Optional[Trade] = None
            should_remove = False
            
            # Latency 조건 확인
            if latency_ms > 0:
                elapsed_ms = (timestamp - pending.submitted_at).total_seconds() * 1000
                if elapsed_ms < latency_ms:
                    # 아직 지연 시간이 지나지 않음 - 주문 유지
                    remaining.append(pending)
                    continue
            
            if order.order_type == OrderType.MARKET:
                if order.side == Side.BUY:
                    trade = self._execute_trade(order, best_ask, timestamp)
                else:
                    trade = self._execute_trade(order, best_bid, timestamp)
                # MARKET 주문은 성공/실패 관계없이 제거
                should_remove = True
            
            elif order.order_type == OrderType.LIMIT:
                if order.side == Side.BUY and price <= order.limit_price:
                    trade = self._execute_trade(order, order.limit_price, timestamp)
                    should_remove = True
                elif order.side == Side.SELL and price >= order.limit_price:
                    trade = self._execute_trade(order, order.limit_price, timestamp)
                    should_remove = True
                # 조건 미충족: 주문 유지
            
            if trade is not None:
                trades.append(trade)
            
            if not should_remove:
                remaining.append(pending)
        
        self._pending_orders = remaining
        return trades
    
    def _check_balance(self, order: Order, execution_price: float) -> bool:
        """
        잔고 확인

        Args:
            order: 체결할 주문
            execution_price: 체결 가격

        Returns:
            True: 잔고 충분
            False: 잔고 부족

        교육 포인트:
            - 현물 매수: USD 잔고 >= 주문금액 + 수수료
            - 현물 매도: BTC 잔고 >= 주문수량
            - 선물: 마진만 확인 (공매도 가능)
            - 부동소수점 오차를 허용 (epsilon = 1e-9)
        """
        epsilon = 1e-9  # 부동소수점 오차 허용
        notional = execution_price * order.quantity
        fee = notional * self.fee_rate

        if self.is_futures_mode:
            # 선물 모드: 마진만 확인 (롱/숏 모두 USD로 마진)
            required_margin = notional / self.leverage + fee
            return self._usd_balance >= required_margin - epsilon
        else:
            # 현물 모드
            if order.side == Side.BUY:
                # 매수: USD 잔고 확인
                required_usd = notional + fee
                return self._usd_balance >= required_usd - epsilon
            else:
                # 매도: BTC 잔고 확인 (공매도 불가)
                return self._btc_balance >= order.quantity - epsilon
    
    def _execute_trade(self, order: Order, execution_price: float, timestamp: datetime) -> Optional[Trade]:
        """
        거래 체결 처리

        Args:
            order: 체결할 주문
            execution_price: 체결 가격
            timestamp: 체결 시간

        Returns:
            체결된 Trade (성공 시)
            None (잔고 부족 시)
        """
        # 잔고 확인
        if not self._check_balance(order, execution_price):
            return None

        # 수수료 계산
        notional = execution_price * order.quantity
        fee = notional * self.fee_rate

        pnl = 0.0

        if self.is_futures_mode:
            # 선물 모드: 마진 기반 거래
            return self._execute_futures_trade(order, execution_price, timestamp, notional, fee)
        else:
            # 현물 모드: 기존 로직
            return self._execute_spot_trade(order, execution_price, timestamp, notional, fee)

    def _execute_spot_trade(
        self,
        order: Order,
        execution_price: float,
        timestamp: datetime,
        notional: float,
        fee: float,
    ) -> Optional[Trade]:
        """현물 거래 체결 처리"""
        pnl = 0.0

        # 잔고 업데이트
        if order.side == Side.BUY:
            self._usd_balance -= notional + fee
            self._btc_balance += order.quantity
        else:
            self._usd_balance += notional - fee
            self._btc_balance -= order.quantity

        # 포지션 처리
        if self._position.side is None:
            # 신규 진입
            self._position = Position(
                side=order.side,
                quantity=order.quantity,
                entry_price=execution_price,
                unrealized_pnl=0.0,
            )
            self._entry_fee = fee

        elif self._position.side == order.side:
            # 추가 진입 (같은 방향)
            total_qty = self._position.quantity + order.quantity
            avg_price = (
                (self._position.entry_price * self._position.quantity + execution_price * order.quantity)
                / total_qty
            )
            self._position = Position(
                side=order.side,
                quantity=total_qty,
                entry_price=avg_price,
                unrealized_pnl=0.0,
            )
            self._entry_fee += fee

        else:
            # 청산 (반대 방향)
            if order.quantity >= self._position.quantity:
                # 전량 청산
                if self._position.side == Side.BUY:
                    gross_pnl = (execution_price - self._position.entry_price) * self._position.quantity
                else:
                    gross_pnl = (self._position.entry_price - execution_price) * self._position.quantity

                pnl = gross_pnl - self._entry_fee - fee
                self._realized_pnl += pnl

                # 포지션 초기화
                self._position = Position()
                self._entry_fee = 0.0
            else:
                # 부분 청산
                close_ratio = order.quantity / self._position.quantity

                # 부분 청산 PnL 계산
                if self._position.side == Side.BUY:
                    gross_pnl = (execution_price - self._position.entry_price) * order.quantity
                else:
                    gross_pnl = (self._position.entry_price - execution_price) * order.quantity

                # 진입 수수료 비례 배분
                allocated_entry_fee = self._entry_fee * close_ratio
                pnl = gross_pnl - allocated_entry_fee - fee
                self._realized_pnl += pnl

                # 남은 포지션 업데이트
                remaining_qty = self._position.quantity - order.quantity
                self._position = Position(
                    side=self._position.side,
                    quantity=remaining_qty,
                    entry_price=self._position.entry_price,  # 평균가 유지
                    unrealized_pnl=0.0,
                )
                self._entry_fee -= allocated_entry_fee  # 남은 진입수수료

        # 거래 기록
        trade = Trade(
            timestamp=timestamp,
            side=order.side,
            price=execution_price,
            quantity=order.quantity,
            fee=fee,
            pnl=pnl,
        )

        self._trades.append(trade)
        self.capital -= fee

        return trade

    def _execute_futures_trade(
        self,
        order: Order,
        execution_price: float,
        timestamp: datetime,
        notional: float,
        fee: float,
    ) -> Optional[Trade]:
        """선물 거래 체결 처리"""
        pnl = 0.0
        margin = notional / self.leverage

        # 포지션 처리
        if self._position.side is None:
            # 신규 진입
            liq_price = self._calculate_liquidation_price(execution_price, order.side)

            self._usd_balance -= margin + fee
            self._position = Position(
                side=order.side,
                quantity=order.quantity,
                entry_price=execution_price,
                unrealized_pnl=0.0,
                leverage=self.leverage,
                liquidation_price=liq_price,
                margin=margin,
            )
            self._entry_fee = fee

        elif self._position.side == order.side:
            # 추가 진입 (같은 방향)
            total_qty = self._position.quantity + order.quantity
            avg_price = (
                (self._position.entry_price * self._position.quantity + execution_price * order.quantity)
                / total_qty
            )
            total_margin = self._position.margin + margin
            liq_price = self._calculate_liquidation_price(avg_price, order.side)

            self._usd_balance -= margin + fee
            self._position = Position(
                side=order.side,
                quantity=total_qty,
                entry_price=avg_price,
                unrealized_pnl=0.0,
                leverage=self.leverage,
                liquidation_price=liq_price,
                margin=total_margin,
            )
            self._entry_fee += fee

        else:
            # 청산 (반대 방향)
            if order.quantity >= self._position.quantity:
                # 전량 청산
                if self._position.side == Side.BUY:
                    gross_pnl = (execution_price - self._position.entry_price) * self._position.quantity
                else:
                    gross_pnl = (self._position.entry_price - execution_price) * self._position.quantity

                pnl = gross_pnl - self._entry_fee - fee
                self._realized_pnl += pnl

                # 마진 반환 + PnL
                self._usd_balance += self._position.margin + gross_pnl - fee

                # 포지션 초기화
                self._position = Position()
                self._entry_fee = 0.0
            else:
                # 부분 청산
                close_ratio = order.quantity / self._position.quantity

                # 부분 청산 PnL 계산
                if self._position.side == Side.BUY:
                    gross_pnl = (execution_price - self._position.entry_price) * order.quantity
                else:
                    gross_pnl = (self._position.entry_price - execution_price) * order.quantity

                # 진입 수수료 비례 배분
                allocated_entry_fee = self._entry_fee * close_ratio
                pnl = gross_pnl - allocated_entry_fee - fee
                self._realized_pnl += pnl

                # 마진 비례 반환
                released_margin = self._position.margin * close_ratio
                self._usd_balance += released_margin + gross_pnl - fee

                # 남은 포지션 업데이트
                remaining_qty = self._position.quantity - order.quantity
                remaining_margin = self._position.margin - released_margin
                self._position = Position(
                    side=self._position.side,
                    quantity=remaining_qty,
                    entry_price=self._position.entry_price,
                    unrealized_pnl=0.0,
                    leverage=self.leverage,
                    liquidation_price=self._position.liquidation_price,
                    margin=remaining_margin,
                )
                self._entry_fee -= allocated_entry_fee

        # 거래 기록
        trade = Trade(
            timestamp=timestamp,
            side=order.side,
            price=execution_price,
            quantity=order.quantity,
            fee=fee,
            pnl=pnl,
        )

        self._trades.append(trade)
        self.capital -= fee

        return trade
    
    def update_unrealized_pnl(self, current_price: float) -> None:
        """
        미실현 손익 업데이트

        Args:
            current_price: 현재 시장 가격

        교육 포인트:
            - 미실현 손익은 지금 청산하면 얼마인지 보여줌
            - 실시간 모니터링에 필요
        """
        if self._position.side is None:
            self._position.unrealized_pnl = 0.0
            return

        if self._position.side == Side.BUY:
            self._position.unrealized_pnl = (current_price - self._position.entry_price) * self._position.quantity
        else:
            self._position.unrealized_pnl = (self._position.entry_price - current_price) * self._position.quantity

    def _calculate_liquidation_price(
        self, entry_price: float, side: Side
    ) -> Optional[float]:
        """
        청산가 계산 (Binance USDT-M Futures Isolated Margin 공식)

        Args:
            entry_price: 진입 가격
            side: 포지션 방향

        Returns:
            청산가 (현물 모드에서는 None)

        Binance 공식 (Isolated Margin, cum=0 가정):
            Long:  LP = (WB - Position×EP) / (Position×MMR - Position)
                     = EP × (1/L - 1) / (MMR - 1)
            Short: LP = (WB + Position×EP) / (Position×MMR + Position)
                     = EP × (1/L + 1) / (MMR + 1)

        교육 포인트:
            - MMR(유지마진율)은 포지션 크기에 따라 다름 (여기서는 0.4% 고정, Tier 1)
            - cum(누적 유지마진액)은 Tier 1에서 0
            - 실제 Binance에서는 포지션 크기에 따라 Tier가 달라짐

        Reference:
            https://www.binance.com/en/support/faq/b3c689c1f50a44cabb3a84e663b81d93
        """
        if not self.is_futures_mode:
            return None

        mmr = self.MAINTENANCE_MARGIN_RATE
        L = self.leverage

        if side == Side.BUY:
            # Long: LP = EP × (1/L - 1) / (MMR - 1)
            return entry_price * (1 / L - 1) / (mmr - 1)
        else:
            # Short: LP = EP × (1/L + 1) / (MMR + 1)
            return entry_price * (1 / L + 1) / (mmr + 1)

    def _check_liquidation(self, current_price: float) -> bool:
        """
        청산 조건 확인

        Args:
            current_price: 현재 시장 가격 (Mark Price 권장)

        Returns:
            True: 청산 조건 충족
            False: 청산 조건 미충족

        교육 포인트:
            - 실제 거래소는 Mark Price 기준으로 청산
            - 백테스트에서는 Last Price 사용 (근사치)
        """
        if not self.is_futures_mode:
            return False

        if self._position.side is None:
            return False

        liq_price = self._position.liquidation_price
        if liq_price is None:
            return False

        if self._position.side == Side.BUY:
            return current_price <= liq_price
        else:
            return current_price >= liq_price

    def _execute_liquidation(self, current_price: float, timestamp: datetime) -> None:
        """
        청산 실행

        Args:
            current_price: 청산 가격
            timestamp: 청산 시간

        교육 포인트:
            - 청산 시 마진 대부분 손실
            - 잔여 마진이 있을 수 있음 (청산가 != 파산가)
        """
        if self._position.side is None:
            return

        # 청산 손실 계산 (마진의 대부분 손실)
        margin = self._position.margin
        entry_price = self._position.entry_price
        quantity = self._position.quantity
        liq_price = self._position.liquidation_price or current_price

        # 실제 손실 계산
        if self._position.side == Side.BUY:
            pnl = (liq_price - entry_price) * quantity
        else:
            pnl = (entry_price - liq_price) * quantity

        # 청산 시 잔여 마진 (보통 거의 0에 가까움)
        remaining_margin = max(0, margin + pnl - self._entry_fee)

        # USD 잔고 업데이트: 마진 반환 (잔여분만)
        self._usd_balance += remaining_margin

        # 실현 손익 업데이트
        loss = margin - remaining_margin + self._entry_fee
        self._realized_pnl -= loss

        # 거래 기록
        trade = Trade(
            timestamp=timestamp,
            side=Side.SELL if self._position.side == Side.BUY else Side.BUY,
            price=liq_price,
            quantity=quantity,
            fee=0.0,  # 청산 시 별도 수수료 없음 (마진에서 차감됨)
            pnl=-loss,
        )
        self._trades.append(trade)

        # 포지션 초기화
        self._position = Position()
        self._entry_fee = 0.0

    def apply_funding(self, funding_rate: float, mark_price: float) -> float:
        """
        Funding Rate 정산 적용

        Args:
            funding_rate: 펀딩레이트 (예: 0.0001 = 0.01%)
            mark_price: 마크 가격

        Returns:
            정산 금액 (양수: 수취, 음수: 지불)

        교육 포인트:
            - 선물 모드에서만 적용
            - 포지션 보유 시에만 적용
            - 롱 + 양수 펀딩 = 지불
            - 숏 + 양수 펀딩 = 수취
        """
        # 현물 모드 또는 포지션 없으면 무시
        if not self.is_futures_mode:
            return 0.0

        if self._position.side is None:
            return 0.0

        # 정산 금액 계산
        notional = self._position.quantity * mark_price
        payment = notional * funding_rate

        if self._position.side == Side.BUY:
            # 롱: 양수 펀딩레이트면 지불
            payment = -payment

        # 잔고 업데이트
        self._usd_balance += payment

        return payment
