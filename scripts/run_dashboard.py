#!/usr/bin/env python3
"""
Forward Tester Dashboard 실행 스크립트

NiceGUI 기반 웹 대시보드를 실행합니다.

사용법:
    python scripts/run_dashboard.py
    python scripts/run_dashboard.py --port 3000
"""

import argparse


def main():
    parser = argparse.ArgumentParser(description="Run Forward Tester Dashboard")
    parser.add_argument("--port", type=int, default=8080, help="Server port (default: 8080)")
    parser.add_argument("--no-show", action="store_true", help="Don't open browser automatically")
    
    args = parser.parse_args()
    
    # UI 모듈 임포트 (nicegui 의존성 필요)
    from intraday.ui.app import create_app
    from nicegui import ui
    
    print("=" * 60)
    print("Intraday Forward Tester Dashboard")
    print("=" * 60)
    print(f"Server running at: http://localhost:{args.port}")
    print("Press Ctrl+C to stop")
    print("=" * 60)
    
    create_app()
    ui.run(
        title="Intraday Forward Tester",
        port=args.port,
        reload=False,
        show=not args.no_show,
    )


if __name__ == "__main__":
    main()

