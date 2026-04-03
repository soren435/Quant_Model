# Quant Model — Investment Analysis Platform

A modular, production-minded investment analysis platform built with Python and Streamlit.
Connects to Saxo Bank OpenAPI for live portfolio data.

---

## Features

| Tab | Description |
|-----|-------------|
| Market Overview | Multi-asset price history, rolling metrics, correlation heatmap |
| Single Asset | Deep-dive: MA crossover, drawdown, monthly returns calendar |
| Portfolio | Custom allocation, attribution, rebalancing simulation |
| Portfolio Builder | Interactive weight builder with live preview |
| Investment Plan | Goal-based savings projections |
| Backtest | Trend-filter (MA200) strategy vs buy-and-hold |
| Scenario Analysis | Stress-test portfolios against historical shocks |
| Historical Strategies | XS Momentum · Dual Momentum · Inverse Vol · Walk-forward validation |
| Macro Regime | Growth/inflation regime detection from ETF proxies · Regime backtesting |
| Hybrid Allocation | Blend momentum + macro via α slider · Sensitivity analysis |
| Investor Profile | Risk questionnaire → score → personalized allocation + backtest |
| Saxo Connect | OAuth2 login · Token refresh · Live account + balance |

---

## Architecture

```
Quant_Model/
├── app.py                        # Entry point — navigation only
├── config.yml                    # Tickers, defaults, settings
├── .env                          # Secrets (never committed)
│
├── src/
│   ├── data/
│   │   └── loader.py             # yfinance downloader (Streamlit-cached)
│   │
│   ├── analytics/                # Pure functions — no Streamlit dependency
│   │   ├── returns.py            # daily/cumulative/annualized returns
│   │   ├── risk.py               # Sharpe, Sortino, MDD, Calmar, beta, TE, IR
│   │   ├── portfolio.py          # build_portfolio_returns, weights_over_time
│   │   └── backtest.py           # run_strategies, trend_filter_returns
│   │
│   ├── engines/                  # Quant engine layer — pure analytics
│   │   ├── historical.py         # XS Momentum, Dual Momentum, Inverse Vol, Walk-forward
│   │   ├── macro_regime.py       # Regime detection (2x2 growth/inflation) + allocation
│   │   ├── hybrid.py             # Signal blending (momentum x macro)
│   │   └── investor_profile.py   # Risk questionnaire → profile → allocation
│   │
│   ├── visualization/
│   │   └── charts.py             # All Plotly figures — return go.Figure
│   │
│   ├── ui/                       # One render_*() function per tab
│   │   ├── market_overview.py
│   │   ├── single_asset.py
│   │   ├── portfolio.py
│   │   ├── portfolio_builder.py
│   │   ├── investment_plan.py
│   │   ├── backtest.py
│   │   ├── scenario.py
│   │   ├── engine_historical.py
│   │   ├── engine_macro.py
│   │   ├── engine_hybrid.py
│   │   ├── engine_investor.py
│   │   └── saxo_connect.py
│   │
│   ├── integrations/
│   │   ├── saxo_auth.py          # OAuth2 token manager (exchange + refresh)
│   │   └── saxo_client.py        # Saxo OpenAPI client (sim + live)
│   │
│   └── utils/
│       └── formatting.py         # format_pct, format_number, parse_*
│
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

**Design principles:**
- Analytics are pure functions with no Streamlit dependency — easy to test and reuse
- Each UI tab has one `render_*()` function
- All charts return `go.Figure` — consistent, composable
- Engines layer sits between analytics and UI — no business logic in UI files

---

## Quickstart (local)

```bash
# 1. Clone and install
git clone <your-repo>
cd Quant_Model
pip install -r requirements.txt

# 2. Configure (optional — runs in simulation mode without this)
cp .env.example .env
# Edit .env with your Saxo credentials

# 3. Run
streamlit run app.py
```

App opens at **http://localhost:8501**

---

## Run with Docker

```bash
# Build
docker build -t quant-model .

# Run
docker run -p 8501:8501 --env-file .env quant-model
```

Or with docker-compose:

```bash
docker-compose up
```

---

## Deploy to Azure Container Apps

```bash
# 1. Login
az login
az acr login --name <your-registry>

# 2. Build and push
docker build -t <your-registry>.azurecr.io/quant-model:latest .
docker push <your-registry>.azurecr.io/quant-model:latest

# 3. Deploy
az containerapp create \
  --name quant-model \
  --resource-group <your-rg> \
  --image <your-registry>.azurecr.io/quant-model:latest \
  --target-port 8501 \
  --ingress external \
  --env-vars SAXO_ENV=sim SAXO_ACCESS_TOKEN=secretref:saxo-token
```

See `azure-deploy.sh` for a complete automated script.

---

## Saxo Bank Integration

The platform connects to Saxo Bank OpenAPI via OAuth2:

```
SAXO_CLIENT_ID      — from developer.saxobank.com
SAXO_CLIENT_SECRET  — from developer.saxobank.com
SAXO_REDIRECT_URI   — http://localhost:8501/ (local) or your Azure URL
SAXO_ENV            — sim (safe) | live (real money)
```

Tokens are managed automatically — access tokens refresh before expiry.
Use the **Saxo Connect** tab to authenticate without touching `.env` manually.

---

## Tech Stack

| Layer | Library |
|-------|---------|
| Frontend | Streamlit 1.46 |
| Data | yfinance, pandas |
| Analytics | numpy, pandas |
| Charts | Plotly |
| Broker API | Saxo OpenAPI (requests + OAuth2) |
| Config | PyYAML, python-dotenv |
| Container | Docker, Azure Container Apps |

---

## Macro Regime Model

Detects market regime from liquid ETF proxies — no proprietary data required:

| Signal | Proxy | Threshold |
|--------|-------|-----------|
| Growth | SPY 6-month return (smoothed 21d) | > 0 = expansion |
| Inflation | TIP/IEF ratio 3-month change | > 0 = rising |
| Credit | HYG/IEF ratio 3-month change | > 0 = risk-on |

Four regimes → four allocation templates:

| Regime | Equity | Bonds | Real Assets | Cash |
|--------|--------|-------|-------------|------|
| Expansion | 60% | 20% | 20% | — |
| Goldilocks | 60% | 35% | 5% | — |
| Stagflation | 10% | 20% | 45% | 25% |
| Recession | 5% | 60% | 20% | 15% |

---

## Disclaimer

This platform is for educational and research purposes only.
Nothing here constitutes investment advice.
Past performance does not guarantee future results.
