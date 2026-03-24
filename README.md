# CRPMS — Continuous Risk-Aware Portfolio Management System
An automated system orchestrating intelligent data ingestion, algorithmic risk scoring, and real-time portfolio management alerts.

## Tech Stack
| Component | Technology | Version |
| :--- | :--- | :--- |
| Backend | Django | 5.0.3 |
| Database | PostgreSQL | 16 |
| Cache | Redis | 7+ (via WSL) |
| Task Queue | Celery + Celery Beat | 5.3+ |
| NLP (Phase 1) | String Templates & Word Matching | v1 |
| NLP (Phase 2) | LLM / Advanced ML | v2 |
| Frontend | HTML5 / Chart.js | Latest |
| Backtesting | Python / Pandas | 2.2+ |
| ML Model | Feature Engineering Engine | v1 |

## Team Structure
| Person | Role | Phase 1 Responsibility | Branch |
| :--- | :--- | :--- | :--- |
| **Person 1** | Data Engineer | Web scraping, fundamental datasets | `feature/p1-data-engineering` |
| **Person 2** | Data Ingestion | Celery queueing, market/social API calls | `feature/p2-data-ingestion` |
| **Person 3** | Quant Analyst | Market Risk Agent, Opportunity Agent | `feature/p3-market-agents` |
| **Person 4** | NLP Engineer | Sentiment Agent, Fundamental Agent | `feature/p4-nlp-agents` |
| **Person 5** | Frontend Dev | Dashboard UI, Chart.js integrations | `feature/p5-dashboard-ui` |

## Prerequisites
1. Python 3.11+
2. PostgreSQL 16
3. Redis (via WSL on Windows)
4. Git
5. Antigravity IDE (Recommended)

## First Time Setup (Windows)
1. **Clone repo**
   ```bash
   git clone https://github.com/your-org/mini-aladdin.git
   cd mini-aladdin
   ```
2. **Create and activate venv**
   ```cmd
   python -m venv venv
   .\venv\Scripts\activate
   ```
3. **Install dependencies**
   ```cmd
   pip install -r requirements.txt
   ```
4. **Environment Variables**
   - Copy `.env.example` to `.env`
   - Fill in your local PostgreSQL passwords and required API Keys.
5. **Run migrations**
   ```cmd
   python manage.py migrate
   ```
6. **Create superuser**
   ```cmd
   python manage.py createsuperuser
   ```
7. **Start Redis in WSL**
   ```cmd
   wsl -d Ubuntu redis-server
   ```
8. **Run startup script**
   ```cmd
   .\start_dev.bat
   ```

## Running the System (Daily)

**Option A: Automated (Recommended)**
Double-click `start_dev.bat` or run it from your terminal. This opens 4 tabs automatically.

**Option B: Manual Tab Spin-up**
You must run these commands in 4 separate terminal tabs, activating `.\venv\Scripts\activate` in each:
1. `wsl -d Ubuntu redis-server`
2. `python manage.py runserver`
3. `celery -A config worker --loglevel=info --pool=solo`
4. `celery -A config beat --loglevel=info`

## Branch Strategy
All features must branch off `develop`. Do not push directly to `main`.
- `main`: Production-ready code only.
- `develop`: Integration branch. Merges from features land here.
- `feature/pX-*`: Personal task branches.

| Person | Branch Prefix | Example |
| :--- | :--- | :--- |
| Person 1 | `feature/p1-*` | `feature/p1-scrape-fundamentals` |
| Person 2 | `feature/p2-*` | `feature/p2-yahoo-finance-api` |
| Person 3 | `feature/p3-*` | `feature/p3-var-calculation` |
| Person 4 | `feature/p4-*` | `feature/p4-vader-sentiment` |
| Person 5 | `feature/p5-*` | `feature/p5-chartjs-render` |

## API Endpoints
| Method | Endpoint | Description | Owner |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/portfolio/` | Portfolio state snapshot | Person 5 |
| `GET` | `/api/positions/` | Active position list | Person 5 |
| `GET` | `/api/decisions/` | Historical/Current decisions | Person 5 |
| `GET` | `/api/agents/` | Raw agent NLP/Var outputs | Person 5 |
| `GET` | `/api/opportunities/` | Top tracked market opportunities | Person 5 |
| `GET` | `/api/alerts/` | System alerts requiring attention | Person 5 |
| `POST`| `/api/alerts/<id>/acknowledge/` | Dismiss alert via Dashboard | Person 5 |
| `GET` | `/api/backtest/` | Backtested strat performance | Person 5 |
| `POST`| `/api/backtest/run/` | Execute new simulation | Person 5 |
| `GET` | `/api/suggestion/` | Portfolio Agent NLP suggestion | Person 5 |
| `GET` | `/api/health/` | Active Postgres/Redis diagnosis | Infra |

## Environment Variables
| Variable | Required | Description |
| :--- | :--- | :--- |
| `SECRET_KEY` | YES | Django cryptography secret. |
| `DEBUG` | YES | `True` for local, `False` for production. |
| `DB_NAME` | YES | PostgreSQL Database Name (`portfolio_db`). |
| `DB_USER` | YES | PostgreSQL Username (`portfolio_user`). |
| `DB_PASSWORD` | YES | PostgreSQL Password. |
| `DB_HOST` | YES | `127.0.0.1` locally. |
| `DB_PORT` | YES | `5432` standard Postgres port. |

## Folder Structure
```text
mini-aladdin/
├── apps/
│   ├── agents/            # Analysis and scoring agents (P3/P4)
│   ├── backtester/        # Historical strategy simulations
│   ├── dashboard/         # UI templates and context views (P5)
│   ├── data_ingestion/    # Web scraping and API tasks (P1/P2)
│   ├── decision_engine/   # Strategy orchestrator
│   ├── feature_engine/    # ML data prep pipeline
│   └── portfolio/         # Central DB schema and REST APIs
├── config/                # Main Django routing and Celery beat schedules
├── logs/                  # Application runtime logs
├── templates/             # HTML files (dashboard/index.html)
├── utils/                 # Unified cache, helpers, and validators
├── manage.py
└── start_dev.bat          # 1-click bootloader
```

## Commit Message Format
All commits must follow conventional formats for clean history tracking.
- `feat:` A new feature (`feat: add VADER sentiment pipeline`)
- `fix:` Bug fixes (`fix: resolve Celery zero-division crash`)
- `docs:` Readme/docstring updates (`docs: outline branch strategy`)
- `refactor:` Changing structure (`refactor: move VaR calc to helpers`)
- `test:` Writing unit tests (`test: add DRF endpoint mocks`)

## Common Issues (Windows)

| Error | Cause | Fix |
| :--- | :--- | :--- |
| **venv activation fails** | Execution policies block scripts | Run `Set-ExecutionPolicy Unrestricted -Scope CurrentUser` in Admin PowerShell. |
| **psycopg2 fails to install** | Missing C++ Build Tools | Install PostgreSQL binaries properly or use `psycopg2-binary`. |
| **Celery crashes on boot** | Missing `--pool=solo` | Windows does not support `fork()`. Always run Celery with `--pool=solo`. |
| **Redis connection refused** | WSL/Docker not running | Run `wsl -d Ubuntu redis-server` first before starting Celery/Django. |
| **ModuleNotFoundError** | Venv not active | Ensure `(venv)` appears before your terminal prompt using `.\venv\Scripts\activate`. |
