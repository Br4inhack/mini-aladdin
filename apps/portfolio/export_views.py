"""
CSV Export Views for CRPMS Portfolio data.
Serves native text/csv responses for accounting and record keeping.
"""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.views import View
import csv
from apps.portfolio.models import Portfolio, Position, DecisionLog

class ExportPositionsCSVView(View):
    """Generates a CSV of all current open positions for a portfolio."""
    
    def get(self, request, portfolio_id):
        portfolio = get_object_or_404(Portfolio, id=portfolio_id)
        positions = Position.objects.filter(portfolio=portfolio).select_related('watchlist')
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="crpms_portfolio_{portfolio_id}_positions.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Ticker', 'Company', 'Sector', 'Quantity', 'Avg Cost', 'Current Price', 'PnL', 'Allocation %'])
        
        for p in positions:
            w = p.watchlist
            cost = float(p.avg_buy_price)
            curr = float(p.current_price) if p.current_price else 0.0
            qty = p.quantity
            pnl = (qty * curr) - (qty * cost)
            
            writer.writerow([
                w.ticker,
                w.company_name,
                w.sector,
                qty,
                cost,
                curr,
                round(pnl, 2),
                round(p.allocation_pct, 2)
            ])
            
        return response


class ExportTradeLogCSVView(View):
    """Generates a CSV of all historical trade logs and decisions."""
    
    def get(self, request, portfolio_id):
        portfolio = get_object_or_404(Portfolio, id=portfolio_id)
        # Fetch global decisions simulating trade log
        logs = DecisionLog.objects.all().select_related('ticker').order_by('-timestamp')
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="crpms_portfolio_{portfolio_id}_tradelog.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Timestamp', 'Ticker', 'Action', 'Confidence Score', 'Reasoning'])
        
        for log in logs:
            writer.writerow([
                log.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                log.ticker.ticker,
                log.action,
                round(log.confidence_score, 4),
                log.reasoning_text
            ])
            
        return response
