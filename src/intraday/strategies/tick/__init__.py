"""
Tick-based Strategies

TickBacktestRunner와 함께 사용하세요.

사용 가능한 데이터:
    - Volume Imbalance (매수/매도 체결량 비율)
    - VWAP
    - Candle OHLCV

전략 추가 방법:
    1. 새 .py 파일 생성 (예: my_strategy.py)
    2. 클래스 이름을 *Strategy로 끝내기 (예: MyStrategy)
    3. 자동으로 발견됨 - __init__.py 수정 불필요
"""

import importlib
import pkgutil
from pathlib import Path

# 자동 발견된 전략들
_strategies: dict[str, type] = {}

# 현재 패키지의 모든 .py 파일 자동 임포트
_package_dir = Path(__file__).parent

for _, module_name, _ in pkgutil.iter_modules([str(_package_dir)]):
    # _로 시작하는 파일 스킵 (_template.py, __init__.py 등)
    if module_name.startswith("_"):
        continue

    try:
        module = importlib.import_module(f".{module_name}", __package__)

        # *Strategy로 끝나는 클래스 찾기
        for attr_name in dir(module):
            if attr_name.endswith("Strategy") and not attr_name.startswith("_"):
                cls = getattr(module, attr_name)
                if isinstance(cls, type):
                    _strategies[attr_name] = cls

    except ImportError as e:
        # 임포트 실패 시 경고만 출력하고 계속
        import warnings
        warnings.warn(f"Failed to import {module_name}: {e}")

# RegimeAnalyzer, RegimeState 등 Strategy가 아닌 것들도 명시적 임포트
try:
    from .regime import RegimeAnalyzer, RegimeState
    _strategies["RegimeAnalyzer"] = RegimeAnalyzer
    _strategies["RegimeState"] = RegimeState
except ImportError:
    pass

# 동적으로 __all__ 생성
__all__: list[str] = list(_strategies.keys())

# 모듈 레벨에 전략 클래스들 노출
globals().update(_strategies)


# 타입 체커를 위한 명시적 re-export (런타임에는 이미 globals()에 있음)
def __getattr__(name: str) -> type:
    """동적 속성 접근 지원."""
    if name in _strategies:
        return _strategies[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
