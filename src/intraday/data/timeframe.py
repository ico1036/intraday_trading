"""
Timeframe 설정 로더

config/timeframes.yaml에서 EDA/IS/OS 기간 설정을 로드합니다.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import os
from typing import Optional

import yaml

from ..config import get_default_config_path, get_default_data_dir


@dataclass
class Period:
    """기간 정의"""
    start: datetime
    end: datetime
    
    @classmethod
    def from_months(cls, start: str, end: str) -> "Period":
        """
        월 문자열에서 Period 생성
        
        Args:
            start: "YYYY-MM" 형식 (해당 월 1일 00:00:00)
            end: "YYYY-MM" 형식 (해당 월 말일 23:59:59)
        """
        start_year, start_month = map(int, start.split("-"))
        end_year, end_month = map(int, end.split("-"))
        
        # 시작: 해당 월 1일
        start_dt = datetime(start_year, start_month, 1)
        
        # 종료: 다음 월 1일 - 1초 (해당 월 마지막 순간)
        if end_month == 12:
            end_dt = datetime(end_year + 1, 1, 1)
        else:
            end_dt = datetime(end_year, end_month + 1, 1)
        
        return cls(start=start_dt, end=end_dt)
    
    def __str__(self) -> str:
        return f"{self.start.strftime('%Y-%m-%d')} ~ {self.end.strftime('%Y-%m-%d')}"


@dataclass
class Timeframe:
    """타임프레임 설정"""
    name: str
    description: str
    eda: Period
    is_period: Period  # 'is'는 예약어라 is_period 사용
    os: Period
    
    def get_period(self, period_type: str) -> Period:
        """
        기간 타입으로 Period 반환
        
        Args:
            period_type: "eda", "is", "os"
        """
        mapping = {
            "eda": self.eda,
            "is": self.is_period,
            "os": self.os,
        }
        if period_type not in mapping:
            raise ValueError(f"Unknown period type: {period_type}. Use 'eda', 'is', or 'os'")
        return mapping[period_type]


class TimeframeConfig:
    """
    Timeframe 설정 관리자
    
    사용 예시:
        config = TimeframeConfig()
        tf = config.get_timeframe("tf1")
        
        print(tf.eda)  # 2025-01-01 ~ 2025-02-28
        print(tf.is_period)  # 2025-03-01 ~ 2025-09-30
        print(tf.os)  # 2025-10-01 ~ 2026-01-31
    """
    
    DEFAULT_CONFIG_PATH = get_default_config_path()
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        Args:
            config_path: 설정 파일 경로 (None이면 기본 경로)
        """
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self._config: dict = {}
        self._timeframes: dict[str, Timeframe] = {}
        self._load_config()
    
    def _load_config(self) -> None:
        """설정 파일 로드"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
        
        with open(self.config_path) as f:
            self._config = yaml.safe_load(f)
        
        # Timeframe 객체로 변환
        for tf_id, tf_data in self._config.get("timeframes", {}).items():
            self._timeframes[tf_id] = Timeframe(
                name=tf_data.get("name", tf_id),
                description=tf_data.get("description", ""),
                eda=Period.from_months(
                    tf_data["eda"]["start"],
                    tf_data["eda"]["end"],
                ),
                is_period=Period.from_months(
                    tf_data["is"]["start"],
                    tf_data["is"]["end"],
                ),
                os=Period.from_months(
                    tf_data["os"]["start"],
                    tf_data["os"]["end"],
                ),
            )
    
    @property
    def symbols(self) -> list[str]:
        """설정된 심볼 목록"""
        return self._config.get("symbols", [])
    
    @property
    def data_dir(self) -> Path:
        """데이터 디렉토리"""
        cfg_value = self._config.get("data_dir")
        if cfg_value is not None:
            expanded = os.path.expandvars(str(cfg_value))
            data_dir = Path(expanded).expanduser()
            if not data_dir.is_absolute():
                data_dir = get_default_config_path().parent.parent / data_dir
            return data_dir
        return get_default_data_dir()
    
    def get_timeframe(self, tf_id: str) -> Timeframe:
        """
        타임프레임 가져오기
        
        Args:
            tf_id: 타임프레임 ID (예: "tf1")
        """
        if tf_id not in self._timeframes:
            available = list(self._timeframes.keys())
            raise ValueError(f"Unknown timeframe: {tf_id}. Available: {available}")
        return self._timeframes[tf_id]
    
    def list_timeframes(self) -> list[str]:
        """사용 가능한 타임프레임 목록"""
        return list(self._timeframes.keys())
    
    def get_data_path(self, symbol: str) -> Path:
        """
        심볼의 데이터 경로 반환
        
        Args:
            symbol: 거래쌍 (예: "BTCUSDT")
        """
        return self.data_dir / symbol.upper()


# 글로벌 인스턴스 (편의용)
_default_config: Optional[TimeframeConfig] = None


def get_config() -> TimeframeConfig:
    """기본 설정 인스턴스 반환"""
    global _default_config
    if _default_config is None:
        _default_config = TimeframeConfig()
    return _default_config
