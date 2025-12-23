"""
Pytest 설정

통합 테스트는 --integration 플래그로 실행
"""

import pytest


def pytest_addoption(parser):
    """커스텀 옵션 추가"""
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="통합 테스트 실행 (네트워크 필요)"
    )


def pytest_configure(config):
    """마커 등록"""
    config.addinivalue_line(
        "markers",
        "integration: 실제 네트워크 연결이 필요한 통합 테스트"
    )


def pytest_collection_modifyitems(config, items):
    """통합 테스트 스킵 처리"""
    if config.getoption("--integration"):
        # --integration 옵션이 있으면 모든 테스트 실행
        return
    
    skip_integration = pytest.mark.skip(reason="--integration 옵션 필요")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)










