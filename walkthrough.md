# CRPMS Django Project Setup — Walkthrough

## What Was Built

Full Django project foundation for the **mini-aladdin** (CRPMS Portfolio Management System) inside `d:\Projects\mini-aladdin`.

---

## Final Project Structure

```
mini-aladdin/
├── config/
│   ├── __init__.py        ← registers Celery app
│   ├── settings.py        ← full CRPMS settings
│   ├── celery.py          ← Celery with Windows fix
│   ├── urls.py
│   └── wsgi.py
├── apps/
│   ├── __init__.py
│   ├── data_ingestion/
│   ├── feature_engine/
│   ├── agents/
│   ├── portfolio/
│   │   ├── models.py      ← 16 production models
│   │   └── admin.py       ← all models registered
│   ├── decision_engine/
│   ├── backtester/
│   └── dashboard/
├── templates/
├── static/
│   ├── css/
│   └── js/
├── utils/
│   ├── __init__.py
│   ├── cache.py           ← Redis cache helpers
│   └── helpers.py         ← shared utilities
├── prompts/
├── venv/                  ← Python 3.13.1, gitignored
├── .env                   ← dev secrets, gitignored
├── .env.example           ← template, committed
├── requirements.txt
└── manage.py
```

---

## Verification

```
System check identified no issues (0 silenced).
```
✅ `python manage.py check` passed clean.

---

## Packages Installed (key ones)

| Package | Version |
|---|---|
| Django | 4.2 |
| djangorestframework | 3.16.1 |
| celery | 5.6.2 |
| django-celery-beat | 2.9.0 |
| django-celery-results | 2.6.0 |
| psycopg2-binary | 2.9.11 |
| redis | 7.3.0 |
| yfinance | 1.2.0 |
| pandas | 3.0.1 |
| scikit-learn | 1.8.0 |

---

## Next Steps (Day 4–5)

1. **Set up PostgreSQL** — create `portfolio_db` database and `portfolio_user`
2. **Start Redis in WSL** — `sudo service redis-server start`
3. **Run migrations:**
   ```powershell
   venv\Scripts\activate
   python manage.py makemigrations portfolio
   python manage.py migrate
   python manage.py createsuperuser
   ```
4. **Start the server:**
   ```powershell
   python manage.py runserver
   # → http://127.0.0.1:8000/admin
   ```
5. **Start Celery worker (separate terminal):**
   ```powershell
   celery -A config worker --loglevel=info --pool=solo
   ```
