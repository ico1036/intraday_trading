"""
Pytest 설정

- 통합 테스트는 --integration 플래그로 제어
- .env 기반 환경 구성값을 테스트 시작 시 주입
  - INTRADAY_DATA_DIR
  - INTRADAY_CONFIG_PATH
"""

from __future__ import annotations

import os

import pytest

from intraday.config import load_environment, get_default_config_path, get_default_data_dir


def pytest_addoption(parser):
    """커스텀 옵션 추가"""
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="통합 테스트 실행 (네트워크 필요)",
    )

    parser.addoption(
        "--data-dir",
        type=str,
        default=None,
        help="백테스트/로더 기본 데이터 경로 (없으면 INTRADAY_DATA_DIR 사용)",
    )


def pytest_configure(config):
    """마커 등록 + 테스트 환경 주입"""
    # 하드코딩 경로 배제: .env 먼저 읽고, 기본값은 프로젝트 기준으로 채움
    load_environment()
    os.environ.setdefault("INTRADAY_DATA_DIR", str(get_default_data_dir()))
    os.environ.setdefault("INTRADAY_CONFIG_PATH", str(get_default_config_path()))

    custom_data_dir = config.getoption("--data-dir")
    if custom_data_dir:
        os.environ["INTRADAY_DATA_DIR"] = custom_data_dir

    config.addinivalue_line(
        "markers",
        "integration: 실제 네트워크 연결이 필요한 통합 테스트",
    )

    # 경고 방지를 위한 가독성 표기
    print(
        f"[conftest] INTRADAY_DATA_DIR={os.environ.get('INTRADAY_DATA_DIR')} | "
        f"INTRADAY_CONFIG_PATH={os.environ.get('INTRADAY_CONFIG_PATH')}"
    )


def pytest_collection_modifyitems(config, items):
    """통합 테스트 스킵 처리"""
    if config.getoption("--integration"):
        return

    skip_integration = pytest.mark.skip(reason="--integration 옵션 필요")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
