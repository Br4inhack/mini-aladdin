import os
import django
from datetime import timedelta
import random

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.portfolio.models import Portfolio, PortfolioStateSnapshot
from django.utils import timezone

def seed_curve():
    p = Portfolio.objects.first()
    if not p:
        print("No portfolio found")
        return
        
    start_val = 900000.0
    current_val = start_val
    today = timezone.now()
    
    # Delete old fake snapshots
    PortfolioStateSnapshot.objects.all().delete()
    
    bulk = []
    print("Generating 60 days of equity curve data...")
    for i in range(60, -1, -1):
        # random daily move between -1.5% and +2.0%
        move_pct = random.uniform(-0.015, 0.02)
        current_val = current_val * (1 + move_pct)
        
        snap = PortfolioStateSnapshot(
            portfolio=p,
            state_data={'total_value': round(current_val, 2)}
        )
        snap.timestamp = today - timedelta(days=i)
        
        # Override auto_now_add logic which ignores explicit assignment on creation usually,
        # but in Django 4+ save() requires mock or using update. We can cheat by saving, then updating.
        snap.save()
        PortfolioStateSnapshot.objects.filter(id=snap.id).update(timestamp=today - timedelta(days=i))
    
    # Ensure latest matches exactly the real portfolio value
    real_val = float(p.total_capital)
    latest = PortfolioStateSnapshot.objects.filter(portfolio=p).order_by('-timestamp').first()
    if latest:
        latest.state_data['total_value'] = real_val
        latest.save()
    
    print("Done generating snapshots.")

if __name__ == '__main__':
    seed_curve()
