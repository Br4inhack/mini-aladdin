"""
apps/portfolio/management/commands/seed_demo_data.py

Seeds realistic demo data for presentations. IDEMPOTENT — safe to re-run.
"""

import random
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.portfolio.models import (
    AgentOutput, Alert, BacktestResult, DecisionLog,
    Portfolio, Position, PriceHistory, Watchlist
)


class Command(BaseCommand):
    help = 'Seeds realistic demo data into the CRPMS database.'

    def handle(self, *args, **options):
        self.stdout.write('Starting demo data seed...\n')
        
        counts = {
            'Portfolio': 0, 'Watchlist': 0, 'Position': 0,
            'PriceHistory': 0, 'AgentOutput': 0, 'DecisionLog': 0,
            'Alert': 0, 'BacktestResult': 0
        }

        try:
            with transaction.atomic():
                # ── SEED STEP 1 — Portfolio ──
                portfolio, created = Portfolio.objects.get_or_create(
                    name='CRPMS Demo Portfolio',
                    defaults={
                        'total_capital': 1000000.00,
                        'available_capital': 150000.00
                    }
                )
                counts['Portfolio'] += 1 if created else 0

                # ── SEED STEP 2 — Watchlist ──
                tickers = [
                    'RELIANCE.NS', 'TCS.NS', 'INFY.NS', 'HDFCBANK.NS', 'ICICIBANK.NS',
                    'SUNPHARMA.NS', 'DRREDDY.NS', 'MARUTI.NS', 'ASIANPAINT.NS', 'TATAMOTORS.NS'
                ]
                
                watchlist_objs = {}
                for t in tickers:
                    obj, created = Watchlist.objects.get_or_create(
                        ticker=t,
                        defaults={'is_active': True, 'company_name': t.replace('.NS', '')}
                    )
                    watchlist_objs[t] = obj
                    if created:
                        counts['Watchlist'] += 1

                # ── SEED STEP 3 — Positions ──
                pos_data = [
                    ('TCS.NS', 22, 3638.00, 3710.00, 8.16),
                    ('RELIANCE.NS', 18, 2890.00, 2810.00, 5.06),
                    ('HDFCBANK.NS', 35, 1680.00, 1720.00, 6.02),
                    ('SUNPHARMA.NS', 30, 1580.00, 1490.00, 4.47),
                    ('TATAMOTORS.NS', 45, 960.00, 890.00, 4.00),
                    ('INFY.NS', 28, 1480.00, 1510.00, 4.23),
                ]
                
                for t, qty, avg_cost, curr_price, alloc in pos_data:
                    unrealised = (curr_price - avg_cost) * qty
                    _, created = Position.objects.get_or_create(
                        portfolio=portfolio,
                        watchlist=watchlist_objs[t],
                        defaults={
                            'quantity': qty,
                            'avg_buy_price': avg_cost,
                            'current_price': curr_price,
                            'allocation_pct': alloc,
                            'unrealised_pnl': unrealised
                        }
                    )
                    if created:
                        counts['Position'] += 1

                # ── SEED STEP 4 — PriceHistory ──
                base_prices = {
                    'TCS.NS': 3638, 'RELIANCE.NS': 2890, 'INFY.NS': 1480, 
                    'HDFCBANK.NS': 1680, 'ICICIBANK.NS': 1100, 'SUNPHARMA.NS': 1580, 
                    'DRREDDY.NS': 1380, 'MARUTI.NS': 10500, 'ASIANPAINT.NS': 2800, 
                    'TATAMOTORS.NS': 960
                }
                
                today = date.today()
                dates_90 = [today - timedelta(days=i) for i in range(120)]
                dates_90 = [d for d in dates_90 if d.weekday() < 5][:90]
                dates_90.reverse()  # oldest to newest
                
                for t in tickers:
                    prev_close = base_prices[t]
                    for d in dates_90:
                        daily_ret = random.gauss(0, 0.012)
                        close_price = prev_close * (1 + daily_ret)
                        high_price = close_price * random.uniform(1.001, 1.015)
                        low_price = close_price * random.uniform(0.985, 0.999)
                        vol = random.randint(500000, 3000000)
                        
                        _, created = PriceHistory.objects.get_or_create(
                            ticker=watchlist_objs[t],
                            date=d,
                            defaults={
                                'open': round(prev_close, 2),
                                'high': round(high_price, 2),
                                'low': round(low_price, 2),
                                'close': round(close_price, 2),
                                'volume': vol
                            }
                        )
                        if created:
                            counts['PriceHistory'] += 1
                        prev_close = close_price

                # ── SEED STEP 5 — AgentOutput (market_risk) ──
                agent_data = [
                    ('TCS.NS', 'LOW', 82.0, {'LOW':0.82,'MEDIUM':0.12,'HIGH':0.05,'CRITICAL':0.01}),
                    ('RELIANCE.NS', 'MEDIUM', 61.0, {'LOW':0.25,'MEDIUM':0.61,'HIGH':0.11,'CRITICAL':0.03}),
                    ('HDFCBANK.NS', 'LOW', 78.0, {'LOW':0.78,'MEDIUM':0.16,'HIGH':0.05,'CRITICAL':0.01}),
                    ('SUNPHARMA.NS', 'HIGH', 35.0, {'LOW':0.10,'MEDIUM':0.25,'HIGH':0.55,'CRITICAL':0.10}),
                    ('TATAMOTORS.NS', 'HIGH', 28.0, {'LOW':0.08,'MEDIUM':0.20,'HIGH':0.58,'CRITICAL':0.14}),
                    ('INFY.NS', 'LOW', 80.0, {'LOW':0.80,'MEDIUM':0.14,'HIGH':0.05,'CRITICAL':0.01}),
                    ('MARUTI.NS', 'MEDIUM', 55.0, {'LOW':0.30,'MEDIUM':0.55,'HIGH':0.12,'CRITICAL':0.03}),
                    ('ICICIBANK.NS', 'LOW', 75.0, {'LOW':0.75,'MEDIUM':0.18,'HIGH':0.06,'CRITICAL':0.01}),
                    ('DRREDDY.NS', 'MEDIUM', 58.0, {'LOW':0.28,'MEDIUM':0.58,'HIGH':0.11,'CRITICAL':0.03}),
                    ('ASIANPAINT.NS', 'LOW', 77.0, {'LOW':0.77,'MEDIUM':0.16,'HIGH':0.06,'CRITICAL':0.01}),
                ]
                
                for t, band, score, probs in agent_data:
                    # using get_or_create on ticker+agent_name for idempotency 
                    # (only one market_risk row needed per ticker for demo)
                    obj, created = AgentOutput.objects.get_or_create(
                        ticker=watchlist_objs[t],
                        agent_name='market_risk',
                        defaults={
                            'band': band,
                            'score': score,
                            'raw_data': probs
                        }
                    )
                    if created:
                        counts['AgentOutput'] += 1
                    else:
                        obj.band = band
                        obj.score = score
                        obj.raw_data = probs
                        obj.save()

                # ── SEED STEP 6 — DecisionLog ──
                decision_data = [
                    ('TCS.NS', 'HOLD', 0.87, 'Solid fundamentals and low market risk.'),
                    ('RELIANCE.NS', 'REDUCE', 0.72, 'Medium risk score; partial profit booking advised.'),
                    ('HDFCBANK.NS', 'HOLD', 0.83, 'Stable banking sector exposure with low risk.'),
                    ('SUNPHARMA.NS', 'EXIT', 0.81, 'High risk of further drawdown in pharma exposure.'),
                    ('TATAMOTORS.NS', 'EXIT', 0.85, 'Critical high-risk signals flash on recent breakdown.'),
                    ('INFY.NS', 'INCREASE', 0.79, 'Low risk with favorable upward sentiment momentum.'),
                ]
                
                for t, action, conf, reason in decision_data:
                    _, created = DecisionLog.objects.get_or_create(
                        ticker=watchlist_objs[t],
                        action=action,
                        confidence_score=conf,
                        reasoning_text=reason
                    )
                    if created:
                        counts['DecisionLog'] += 1

                # ── SEED STEP 7 — Alerts ──
                alerts_data = [
                    ('SUNPHARMA.NS', 'RISK_HIGH', 'Market Risk Agent classified SUNPHARMA.NS as HIGH risk. Current score: 35.0. Decision Agent recommends reviewing position.'),
                    ('TATAMOTORS.NS', 'RISK_HIGH', 'Two consecutive HIGH risk signals on TATAMOTORS.NS. Decision Agent confidence 85% for EXIT action.')
                ]
                
                for t, a_type, msg in alerts_data:
                    _, created = Alert.objects.get_or_create(
                        ticker=watchlist_objs[t],
                        alert_type=a_type,
                        message=msg,
                        defaults={'is_acknowledged': False}
                    )
                    if created:
                        counts['Alert'] += 1

                # ── SEED STEP 8 — BacktestResult ──
                _, created = BacktestResult.objects.get_or_create(
                    run_name='CRPMS Risk-Aware Strategy',
                    start_date=dates_90[0],
                    end_date=today,
                    defaults={
                        'starting_capital': 1000000.00,
                        'cagr': 14.3,
                        'sharpe_ratio': 1.42,
                        'max_drawdown': 6.8,
                        'benchmark_results': {'notes': 'Outperformed Nifty 50 benchmark (9.1%) by 5.2%'}
                    }
                )
                if created:
                    counts['BacktestResult'] += 1

            self.stdout.write(self.style.SUCCESS('\nDemo data seeded successfully!'))
            self.stdout.write('Records created in this run:')
            for model_name, count in counts.items():
                self.stdout.write(f'  - {model_name}: {count}')

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\nError seeding data: {str(e)}'))

