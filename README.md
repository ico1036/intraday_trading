# Intraday Trading Education

Binance Orderbook 분석을 통한 Intraday Trading 교육 프로젝트입니다.

## 학습 내용

1. **Orderbook (호가창)** - 매수/매도 주문 데이터 이해
2. **Bid-Ask Spread** - 유동성 지표 분석
3. **Mid-price vs Micro-price** - 가격 예측 지표 비교

## 설치

```bash
uv sync
```

## 실행

### Jupyter Notebook (학습용)

```bash
uv run jupyter notebook notebooks/01_orderbook_basics.ipynb
```

### 실시간 대시보드

```bash
uv run python -m intraday.dashboard
```

## 환경 변수

`.env` 파일에 Binance API 키를 설정하세요:

```
BINANCE_API_KEY=your_api_key_here
```










