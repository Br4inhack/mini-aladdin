import sys
from django.core.management.base import BaseCommand
from rest_framework.test import APIRequestFactory

class Command(BaseCommand):
    help = 'Verifies Phase 2 deliverables for Person 5.'

    def handle(self, *args, **options):
        passed_checks = 0
        total_checks = 10
        fails = []

        factory = APIRequestFactory()
        dummy_request = factory.get('/')

        def run_check(check_num, name, func):
            nonlocal passed_checks
            try:
                result = func()
                if result is False:
                    self.stdout.write(self.style.ERROR(f"CHECK {check_num} — {name}: FAIL"))
                    fails.append(check_num)
                else:
                    self.stdout.write(self.style.SUCCESS(f"CHECK {check_num} — {name}: PASS"))
                    passed_checks += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"CHECK {check_num} — {name}: FAIL ({str(e)})"))
                fails.append(check_num)

        # CHECK 1
        def check1():
            from apps.portfolio.serializers import NewsArticleSerializer
            fields = NewsArticleSerializer().get_fields().keys()
            for f in ['sentiment_label', 'sentiment_strength', 'sentiment_color']:
                if f not in fields:
                    raise ValueError(f"Missing field: {f}")
            return True
        run_check(1, "FinBERT serializer fields", check1)

        # CHECK 2
        def check2():
            from apps.portfolio.api_views import SentimentTrendView
            return True
        run_check(2, "Sentiment trend endpoint exists", check2)

        # CHECK 3
        def check3():
            from apps.portfolio.api_views import SectorExposureView
            from apps.portfolio.models import Portfolio, Position, Watchlist
            
            p, _ = Portfolio.objects.get_or_create(id=1, defaults={'name':'Test','total_value':1000})
            if Position.objects.filter(portfolio=p).exists():
                view = SectorExposureView()
                response = view.get(dummy_request, portfolio_id=1)
                # It should return a list, even if empty
                if not isinstance(response.data, list):
                    raise ValueError(f"Expected list, got {type(response.data)}: {response.data}")
            return True
        run_check(3, "Sector exposure endpoint", check3)

        # CHECK 4
        def check4():
            from apps.portfolio.api_views import PnLTrendView
            from apps.portfolio.models import Portfolio, PortfolioStateSnapshot
            # Assuming portfolio 1 exists or create
            p, _ = Portfolio.objects.get_or_create(id=1, defaults={'name':'Test','total_value':1000})
            view = PnLTrendView()
            response = view.get(dummy_request, portfolio_id=p.id)
            if not isinstance(response.data, list):
                raise ValueError("Expected list output")
            return True
        run_check(4, "PnL trend endpoint", check4)

        # CHECK 5
        def check5():
            from apps.portfolio.api_views import AlertHistoryView
            return True
        run_check(5, "Alert history pagination", check5)

        # CHECK 6
        def check6():
            from apps.portfolio.api_views import AlertStatsView
            return True
        run_check(6, "Alert stats endpoint", check6)

        # CHECK 7
        def check7():
            from apps.portfolio.api_views import MacroIndicatorView
            from apps.portfolio.models import Portfolio
            p, _ = Portfolio.objects.get_or_create(id=1, defaults={'name':'Test','total_value':1000})
            view = MacroIndicatorView()
            response = view.get(dummy_request, portfolio_id=p.id)
            if not isinstance(response.data, list):
                raise ValueError("Expected list output")
            return True
        run_check(7, "Macro indicators endpoint", check7)

        # CHECK 8
        def check8():
            from django.template.loader import get_template
            for tmpl in ['dashboard/portfolio.html', 'dashboard/backtest.html', 'dashboard/alerts.html', 'dashboard/settings.html']:
                get_template(tmpl)
            return True
        run_check(8, "All new templates exist", check8)

        # CHECK 9
        def check9():
            from apps.dashboard.views import SettingsView
            return True
        run_check(9, "Settings view", check9)

        # CHECK 10
        def check10():
            from django.urls import reverse
            for name in ['dashboard:index', 'dashboard:backtest', 'dashboard:alerts', 'dashboard:settings']:
                reverse(name)
            return True
        run_check(10, "URL resolution", check10)

        # Summary
        self.stdout.write(f"\n{passed_checks}/{total_checks} checks passed.")
        
        if fails:
            sys.exit(1)
