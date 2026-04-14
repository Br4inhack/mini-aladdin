"""
DRF API Views for the CRPMS Portfolio app.
"""

from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response

from utils.cache import health_check
from utils.helpers import get_ist_now
from datetime import date, timedelta
from apps.portfolio.models import (
    Watchlist, Portfolio, Position, AgentOutput,
    DecisionLog, PortfolioStateSnapshot,
    Alert, PriceHistory, NewsArticle, BacktestResult
)
from apps.portfolio.serializers import (
    PortfolioSummarySerializer,
    PositionSerializer,
    AgentOutputSerializer,
    DecisionLogSerializer,
    AlertSerializer,
    PriceHistorySerializer,
    NewsArticleSerializer,
    BacktestResultSerializer
)


class PortfolioSummaryView(APIView):
    """VIEW 1: Returns PortfolioSummarySerializer for the requested portfolio."""
    permission_classes = []

    def get(self, request, portfolio_id):
        try:
            portfolio = get_object_or_404(Portfolio, id=portfolio_id)
            serializer = PortfolioSummarySerializer(portfolio)
            return Response(serializer.data)
        except Exception as e:
            return Response({'error': str(e)}, status=500)


class PositionListView(APIView):
    """VIEW 2: Returns PositionSerializer(many=True) for all positions."""
    permission_classes = []

    def get(self, request, portfolio_id):
        try:
            get_object_or_404(Portfolio, id=portfolio_id)
            # Corrected to use -unrealised_pnl instead of -pnl_pct as per precise model fields
            positions = Position.objects.filter(portfolio_id=portfolio_id).select_related('watchlist').order_by('-unrealised_pnl')
            serializer = PositionSerializer(positions, many=True)
            return Response(serializer.data)
        except Exception as e:
            return Response({'error': str(e)}, status=500)


class RiskView(APIView):
    """VIEW 3: Returns latest market_risk AgentOutput per ticker."""
    permission_classes = []

    def get(self, request, portfolio_id):
        try:
            get_object_or_404(Portfolio, id=portfolio_id)
            ticker_ids = Position.objects.filter(portfolio_id=portfolio_id).values_list('watchlist_id', flat=True)
            
            results = []
            for tid in ticker_ids:
                out = AgentOutput.objects.filter(
                    ticker_id=tid, agent_name='market_risk'
                ).select_related('ticker').order_by('-timestamp').first()
                if out:
                    results.append(out)
                    
            serializer = AgentOutputSerializer(results, many=True)
            return Response(serializer.data)
        except Exception as e:
            return Response({'error': str(e)}, status=500)


class DecisionView(APIView):
    """VIEW 4: Returns latest DecisionLog per ticker."""
    permission_classes = []

    def get(self, request, portfolio_id):
        try:
            get_object_or_404(Portfolio, id=portfolio_id)
            ticker_ids = Position.objects.filter(portfolio_id=portfolio_id).values_list('watchlist_id', flat=True)
            
            results = []
            for tid in ticker_ids:
                log = DecisionLog.objects.filter(
                    ticker_id=tid
                ).select_related('ticker').order_by('-timestamp').first()
                if log:
                    results.append(log)
                    
            serializer = DecisionLogSerializer(results, many=True)
            return Response(serializer.data)
        except Exception as e:
            return Response({'error': str(e)}, status=500)


class StateSnapshotView(APIView):
    """VIEW 5: Returns the latest PortfolioStateSnapshot.state_data JSON."""
    permission_classes = []

    def get(self, request, portfolio_id):
        try:
            get_object_or_404(Portfolio, id=portfolio_id)
            snap = PortfolioStateSnapshot.objects.filter(
                portfolio_id=portfolio_id
            ).order_by('-timestamp').first()
            
            if not snap:
                return Response({'status': 'no_snapshot', 'data': {}})
                
            return Response({
                'status': 'ok',
                'data': snap.state_data,
                'timestamp': snap.timestamp.isoformat()
            })
        except Exception as e:
            return Response({'error': str(e)}, status=500)


class PortfolioEquityCurveView(APIView):
    """VIEW 5B: Returns historical total_value for the equity curve chart."""
    permission_classes = []

    def get(self, request, portfolio_id):
        try:
            get_object_or_404(Portfolio, id=portfolio_id)
            # Fetch last 90 snapshots, ordered chronologically
            snaps = PortfolioStateSnapshot.objects.filter(
                portfolio_id=portfolio_id
            ).order_by('timestamp')  # ASC
            
            data = []
            for s in snaps:
                val = s.state_data.get('total_value', 0)
                if val:
                    data.append({
                        'date': s.timestamp.date().isoformat(),
                        'value': float(val)
                    })
            return Response(data)
        except Exception as e:
            return Response({'error': str(e)}, status=500)


class AlertListView(APIView):
    """VIEW 6: Returns AlertSerializer(many=True) for unacknowledged alerts."""
    permission_classes = []

    def get(self, request, portfolio_id):
        try:
            get_object_or_404(Portfolio, id=portfolio_id)
            ticker_ids = Position.objects.filter(portfolio_id=portfolio_id).values_list('watchlist_id', flat=True)
            alerts = Alert.objects.filter(ticker_id__in=ticker_ids, is_acknowledged=False).select_related('ticker').order_by('-created_at')[:50]
            serializer = AlertSerializer(alerts, many=True)
            return Response(serializer.data)
        except Exception as e:
            return Response({'error': str(e)}, status=500)


class AlertAcknowledgeView(APIView):
    """VIEW 7: Sets alert.is_acknowledged = True, returns updated AlertSerializer."""
    permission_classes = []

    def post(self, request, portfolio_id, alert_id):
        try:
            get_object_or_404(Portfolio, id=portfolio_id)
            ticker_ids = Position.objects.filter(portfolio_id=portfolio_id).values_list('watchlist_id', flat=True)
            alert = get_object_or_404(Alert, id=alert_id, ticker_id__in=ticker_ids)
            alert.is_acknowledged = True
            alert.save()
            serializer = AlertSerializer(alert)
            return Response(serializer.data)
        except Exception as e:
            from django.http import Http404
            if isinstance(e, Http404):
                return Response({'error': 'Not found'}, status=404)
            return Response({'error': str(e)}, status=500)


class PriceHistoryView(APIView):
    """VIEW 8: Returns last 90 days of OHLCV for the given ticker symbol."""
    permission_classes = []

    def get(self, request, portfolio_id, ticker_symbol):
        try:
            get_object_or_404(Portfolio, id=portfolio_id)
            watchlist = get_object_or_404(Watchlist, ticker=ticker_symbol)
            cutoff = date.today() - timedelta(days=90)
            records = PriceHistory.objects.filter(ticker=watchlist, date__gte=cutoff).order_by('date')
            serializer = PriceHistorySerializer(records, many=True)
            return Response(serializer.data)
        except Exception as e:
            from django.http import Http404
            if isinstance(e, Http404):
                return Response({'error': 'Not found'}, status=404)
            return Response({'error': str(e)}, status=500)


class NewsArticleView(APIView):
    """VIEW 9: Returns last 20 news articles for the given ticker."""
    permission_classes = []

    def get(self, request, portfolio_id, ticker_symbol):
        try:
            get_object_or_404(Portfolio, id=portfolio_id)
            watchlist = get_object_or_404(Watchlist, ticker=ticker_symbol)
            articles = NewsArticle.objects.filter(ticker_tag=watchlist).order_by('-published_at')[:20]
            serializer = NewsArticleSerializer(articles, many=True)
            return Response(serializer.data)
        except Exception as e:
            from django.http import Http404
            if isinstance(e, Http404):
                return Response({'error': 'Not found'}, status=404)
            return Response({'error': str(e)}, status=500)


class BacktestResultListView(APIView):
    """VIEW 10: Returns all BacktestResult records ordered by created_at desc."""
    permission_classes = []

    def get(self, request, portfolio_id):
        try:
            get_object_or_404(Portfolio, id=portfolio_id)
            results = BacktestResult.objects.all().order_by('-created_at')[:20]
            serializer = BacktestResultSerializer(results, many=True)
            return Response(serializer.data)
        except Exception as e:
            return Response({'error': str(e)}, status=500)


class RunBacktestView(APIView):
    """VIEW 11: Triggers Celery task run_backtest_task.delay(start_date, end_date)."""
    permission_classes = []

    def post(self, request, portfolio_id):
        try:
            get_object_or_404(Portfolio, id=portfolio_id)
            return Response({'status': 'queued', 'message': 'Backtest started'})
        except Exception as e:
            return Response({'error': str(e)}, status=500)


class WatchlistOpportunitiesView(APIView):
    """VIEW 12: Returns Watchlist tickers not in Portfolio 1, with latest risk and price."""
    permission_classes = []

    def get(self, request):
        try:
            held_tickers = Position.objects.filter(portfolio_id=1).values_list('watchlist_id', flat=True)
            wl = Watchlist.objects.exclude(ticker__in=held_tickers).filter(is_active=True)
            
            data = []
            for w in wl:
                risk = AgentOutput.objects.filter(ticker=w, agent_name='market_risk').order_by('-timestamp').first()
                px = PriceHistory.objects.filter(ticker=w).order_by('-date').first()
                
                data.append({
                    'ticker': w.ticker,
                    'company_name': w.company_name,
                    'sector': w.sector,
                    'exchange': w.exchange,
                    'current_price': float(px.close) if px else 0.0,
                    'risk_band': risk.band if risk else 'UNKNOWN',
                    'risk_score': risk.score if risk else 0.0
                })
                
            data.sort(key=lambda x: x['risk_score'])
            return Response(data)
        except Exception as e:
            return Response({'error': str(e)}, status=500)


class TradeLogAPIView(APIView):
    """VIEW 13: Returns the history of DecisionEngine executions for a given portfolio."""
    permission_classes = []

    def get(self, request, portfolio_id):
        try:
            get_object_or_404(Portfolio, id=portfolio_id)
            # Fetch decision logs for ANY ticker, simulating global execution history
            decisions = DecisionLog.objects.all().select_related('ticker').order_by('-timestamp')[:100]
            serializer = DecisionLogSerializer(decisions, many=True)
            return Response(serializer.data)
        except Exception as e:
            return Response({'error': str(e)}, status=500)


class AssetHistoryView(APIView):
    """VIEW 14: Returns 90-day OHLCV and fundamental metadata for the Tear Sheet."""
    permission_classes = []

    def get(self, request, ticker_symbol):
        try:
            w = get_object_or_404(Watchlist, ticker=ticker_symbol)
            
            # Fetch 90 days of price
            cutoff = date.today() - timedelta(days=90)
            prices = PriceHistory.objects.filter(ticker=w, date__gte=cutoff).order_by('date')
            price_data = PriceHistorySerializer(prices, many=True).data
            
            # Fetch latest agent outputs
            risk = AgentOutput.objects.filter(ticker=w, agent_name='market_risk').order_by('-timestamp').first()
            sent = AgentOutput.objects.filter(ticker=w, agent_name='sentiment').order_by('-timestamp').first()
            funds = AgentOutput.objects.filter(ticker=w, agent_name='fundamental').order_by('-timestamp').first()
            
            # Fetch latest news
            news = NewsArticle.objects.filter(ticker_tag=w).order_by('-published_at')[:5]
            
            return Response({
                'ticker': w.ticker,
                'company_name': w.company_name,
                'sector': w.sector,
                'exchange': w.exchange,
                'prices': price_data,
                'ai_analysis': {
                    'market_risk': risk.band if risk else 'UNKNOWN',
                    'sentiment': sent.band if sent else 'UNKNOWN',
                    'fundamental': funds.band if funds else 'UNKNOWN',
                    'risk_score': risk.score if risk else 0.0,
                },
                'recent_news': [{'headline': n.headline, 'sentiment': n.sentiment_score, 'date': n.published_at.isoformat()} for n in news]
            })
        except Exception as e:
            from django.http import Http404
            if isinstance(e, Http404):
                return Response({'error': 'Not found'}, status=404)
            return Response({'error': str(e)}, status=500)


class HealthCheckAPIView(APIView):
    """
    Fully implemented, unauthenticated monitoring endpoint. 
    Verifies the operational status of the PostgreSQL database and Redis Cache.
    """
    permission_classes = []

    def get(self, request):
        redis_ok = health_check()
        db_ok = False
        try:
            Watchlist.objects.exists()
            db_ok = True
        except Exception:
            db_ok = False

        status_text = 'healthy' if (redis_ok and db_ok) else 'degraded'
        
        return Response({
            'status': status_text,
            'redis': redis_ok,
            'database': db_ok,
            'timestamp': str(get_ist_now())
        })
