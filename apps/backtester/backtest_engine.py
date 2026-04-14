"""
apps/backtester/backtest_engine.py

Core execution engine wrapping Backtrader, pulling dataset context straight from
the CRPMS Postgres models, running the vector evaluations, and persisting results.
"""

import logging
import time
from datetime import datetime
import pandas as pd
import backtrader as bt

from django.db.models import F
from apps.portfolio.models import Watchlist, PriceHistory, AgentOutput, BacktestResult
from apps.backtester.strategies import RiskAwareStrategy


class CRPMSBacktester:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def run(self, start_date, end_date) -> BacktestResult:
        try:
            start_time = time.time()
            self.logger.info("Starting Backtest run: %s -> %s", start_date, end_date)

            # 1. Fetch all active Watchlist tickers.
            tickers = list(Watchlist.objects.filter(is_active=True))
            if not tickers:
                raise ValueError("No active Watchlist tickers found.")

            risk_signals = {}
            valid_tickers = []
            
            # 4. Set up Backtrader cerebro
            cerebro = bt.Cerebro()
            initial_capital = 1000000.0
            cerebro.broker.setcash(initial_capital)
            cerebro.broker.setcommission(commission=0.001)  # 0.1% brokerage

            # 2. Fetch records and build data feeds
            for watchlist_obj in tickers:
                records = PriceHistory.objects.filter(
                    ticker=watchlist_obj,
                    date__gte=start_date,
                    date__lte=end_date
                ).order_by('date')
                
                # Skip tickers with fewer than 20 price records
                if records.count() < 20:
                    continue
                    
                valid_tickers.append(watchlist_obj)

                # 3. Fetch latest AgentOutput (agent_name='market_risk')
                agent = AgentOutput.objects.filter(
                    ticker=watchlist_obj,
                    agent_name=AgentOutput.AgentName.MARKET_RISK
                ).order_by('-timestamp').first()
                
                risk_signals[watchlist_obj.ticker] = agent.band if (agent and agent.band) else 'MEDIUM'

                # 5. Convert PriceHistory queryset to pandas DataFrame
                df = pd.DataFrame(list(records.values(
                    'date', 'open', 'high', 'low', 'close', 'volume'
                )))
                
                # DataFrame must have columns: datetime, open, high, low, close, volume
                # datetime column must be timezone-naive datetime objects.
                df.rename(columns={'date': 'datetime'}, inplace=True)
                df['datetime'] = pd.to_datetime(df['datetime']).dt.tz_localize(None)
                df.set_index('datetime', inplace=True)

                data_feed = bt.feeds.PandasData(
                    dataname=df,
                    name=watchlist_obj.ticker
                )
                cerebro.adddata(data_feed)

            if not valid_tickers:
                raise ValueError("No tickers have sufficient price history (>=20 records) for this date range.")

            # 6. Add Strategy
            cerebro.addstrategy(RiskAwareStrategy, risk_signals=risk_signals)

            # 7. Add benchmark and analyzers
            cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
            cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
            cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')

            # 8. Run Strategy
            results = cerebro.run()

            # 9. Extract metrics
            strat = results[0]
            sharpe = strat.analyzers.sharpe.get_analysis().get('sharperatio', 0.0) or 0.0
            max_dd = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0.0)
            
            final_value = cerebro.broker.getvalue()
            total_return = ((final_value - initial_capital) / initial_capital) * 100

            # 10. Compute benchmark_return (Simple equal-weight)
            benchmark_returns = []
            for t in valid_tickers:
                start_record = PriceHistory.objects.filter(ticker=t, date__gte=start_date).order_by('date').first()
                end_record = PriceHistory.objects.filter(ticker=t, date__lte=end_date).order_by('-date').first()
                
                if start_record and end_record and start_record.close > 0:
                    ret = ((float(end_record.close) - float(start_record.close)) / float(start_record.close)) * 100
                    benchmark_returns.append(ret)
                    
            benchmark_return = sum(benchmark_returns) / len(benchmark_returns) if benchmark_returns else 0.0

            # 11. Save and return BacktestResult (Mapping dynamically requested fields to exact model schema fields)
            result_obj = BacktestResult.objects.create(
                run_name='CRPMS Risk-Aware Phase 1',
                start_date=start_date,
                end_date=end_date,
                starting_capital=initial_capital,
                cagr=round(total_return, 2),  # mapped total_return to cagr
                sharpe_ratio=round(sharpe, 3),
                max_drawdown=round(max_dd, 2),
                benchmark_results={
                    'benchmark_return': round(benchmark_return, 2)
                },
                config={
                    'notes': {
                        'tickers_tested': len(valid_tickers),
                        'data_source': 'PriceHistory'
                    }
                }
            )

            end_time = time.time()
            self.logger.info("Backtest run completed in %.2f seconds", end_time - start_time)
            return result_obj

        except Exception as e:
            self.logger.error("Backtest failed: %s", str(e))
            raise
