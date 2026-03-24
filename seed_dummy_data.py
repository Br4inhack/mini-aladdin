import os
import django
from datetime import date, timedelta
from django.utils import timezone

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.portfolio.models import (
    Watchlist, Portfolio, Position, PriceHistory, 
    FeatureSnapshot, AgentOutput, DecisionLog
)

def run():
    print("Seeding dummy data...")
    today = date.today()
    
    ticker_obj = Watchlist.objects.filter(is_active=True).first()
    if not ticker_obj:
        print("No watchlist tickers! Can't seed.")
        return

    # Check 5: PriceHistory
    PriceHistory.objects.get_or_create(
        ticker=ticker_obj, 
        date=today,
        defaults={'open': 100, 'high': 105, 'low': 95, 'close': 102, 'volume': 1000}
    )

    # Check 6: FeatureSnapshot
    FeatureSnapshot.objects.get_or_create(
        ticker=ticker_obj,
        date=today,
        defaults={
            'risk_features': {}, 'sentiment_features': {}, 
            'fundamental_features': {}, 'opportunity_features': {}
        }
    )

    # Check 7: AgentOutput (market_risk)
    AgentOutput.objects.create(
        ticker=ticker_obj,
        agent_name=AgentOutput.AgentName.MARKET_RISK,
        score=0.7,
        band=AgentOutput.Band.MEDIUM
    )

    # Check 8: AgentOutput (sentiment)
    AgentOutput.objects.create(
        ticker=ticker_obj,
        agent_name=AgentOutput.AgentName.SENTIMENT,
        score=0.8,
        band=AgentOutput.Band.HIGH
    )

    # Check 9: DecisionLog
    DecisionLog.objects.create(
        ticker=ticker_obj,
        action=DecisionLog.Action.HOLD,
        confidence_score=0.85,
        reasoning_text='Dummy reason'
    )

    # Check 10 & 11: Portfolio and Position
    portfolio, _ = Portfolio.objects.get_or_create(
        name='Test Portfolio',
        defaults={'total_capital': 1000000, 'available_capital': 500000}
    )
    Position.objects.get_or_create(
        portfolio=portfolio,
        watchlist=ticker_obj,
        defaults={
            'quantity': 100, 
            'avg_buy_price': 100, 
            'current_price': 102, 
            'allocation_pct': 10,
            'unrealised_pnl': 200
        }
    )

    print("Seeding complete.")

if __name__ == '__main__':
    run()
