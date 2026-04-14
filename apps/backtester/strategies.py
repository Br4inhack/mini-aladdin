"""
apps/backtester/strategies.py

Phase 1 baseline risk-aware strategy for Backtrader.
Buys LOW risk ticker symbols, and exits on HIGH or CRITICAL signal shifts.
"""

import backtrader as bt


class RiskAwareStrategy(bt.Strategy):
    """
    This is the Phase 1 baseline strategy.
    It buys tickers classified LOW risk and exits on HIGH or CRITICAL.
    """
    params = (
        ('risk_signals', {}),
        ('max_positions', 10),
    )
    # risk_signals is a dict: {ticker_symbol: band_string}
    # passed in when cerebro.addstrategy() is called

    def __init__(self):
        self.order_dict = {}  # ticker -> open order

    def next(self):
        for data in self.datas:
            ticker = data._name
            band = self.params.risk_signals.get(ticker, 'MEDIUM')
            position = self.getposition(data)

            # Entry logic
            if not position.size and band == 'LOW':
                active_positions = sum(1 for d in self.datas if self.getposition(d).size > 0)
                if active_positions < self.params.max_positions:
                    # Allocate equal weight of maximum available capital based on max_positions
                    target_cash = self.broker.getcash() / self.params.max_positions
                    size = int(target_cash / data.close[0])
                    if size > 0:
                        self.buy(data=data, size=size)

            # Exit logic
            elif position.size and band in ('HIGH', 'CRITICAL'):
                self.sell(data=data, size=position.size)

    def stop(self):
        self.final_value = self.broker.getvalue()
