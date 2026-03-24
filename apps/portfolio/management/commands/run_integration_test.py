"""
apps/portfolio/management/commands/run_integration_test.py

Full-stack integration diagnostic for CRPMS.

Usage:
    python manage.py run_integration_test

Exit code 0 = all checks passed.
Exit code 1 = one or more checks failed.

Run after every teammate merge to catch regressions early.
"""

import sys
import traceback
from datetime import date, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Runs 12 end-to-end integration checks and prints PASS / FAIL for each.'

    # ── helpers ─────────────────────────────────────────────────────────────

    def _pass(self, n: int, msg: str) -> None:
        self.stdout.write(f'  [PASS] Check {n:02d}: {msg}')

    def _fail(self, n: int, msg: str) -> None:
        self.stdout.write(self.style.ERROR(f'  [FAIL] Check {n:02d}: {msg}'))

    def _skip(self, n: int, msg: str) -> None:
        self.stdout.write(self.style.WARNING(f'  [SKIP] Check {n:02d}: {msg}'))

    # ── checks ───────────────────────────────────────────────────────────────

    def _check_01_db(self) -> bool:
        from apps.portfolio.models import Portfolio
        try:
            count = Portfolio.objects.count()
            self._pass(1, f'Database connected. Portfolio rows: {count}')
            return True
        except Exception as exc:
            self._fail(1, f'Database error: {exc}')
            return False

    def _check_02_redis(self) -> bool:
        from django.core.cache import cache
        try:
            cache.set('integration_ping', 'pong', timeout=5)
            val = cache.get('integration_ping')
            if val == 'pong':
                self._pass(2, 'Redis connected (Django cache set/get OK)')
                return True
            self._fail(2, f'Redis cache get returned {val} (expected pong)')
            return False
        except Exception as exc:
            self._fail(2, f'Redis error: {exc}')
            return False

    def _check_03_watchlist(self) -> bool:
        from apps.portfolio.models import Watchlist
        try:
            count = Watchlist.objects.filter(is_active=True).count()
            if count >= 5:
                self._pass(3, f'Watchlist has {count} active tickers')
                return True
            self._fail(3, f'Only {count} active Watchlist tickers (need ≥ 5). Run: load_sector_data')
            return False
        except Exception as exc:
            self._fail(3, f'Watchlist query error: {exc}')
            return False

    def _check_04_sector_mapping(self) -> bool:
        from apps.portfolio.models import SectorMapping
        try:
            count = SectorMapping.objects.count()
            if count >= 20:
                self._pass(4, f'SectorMapping has {count} records')
                return True
            self._fail(4, f'Only {count} SectorMapping records. Run: python manage.py load_sector_data')
            return False
        except Exception as exc:
            self._fail(4, f'SectorMapping query error: {exc}')
            return False

    def _check_05_price_history(self) -> bool:
        from apps.portfolio.models import PriceHistory
        try:
            cutoff = date.today() - timedelta(days=7)
            count = PriceHistory.objects.filter(date__gte=cutoff).count()
            if count > 0:
                self._pass(5, f'PriceHistory has {count} records within last 7 days')
                return True
            self._fail(5, 'No recent PriceHistory records. Person 2 data ingestion not running.')
            return False
        except Exception as exc:
            self._fail(5, f'PriceHistory query error: {exc}')
            return False

    def _check_06_feature_snapshot(self) -> bool:
        from apps.portfolio.models import FeatureSnapshot
        try:
            count = FeatureSnapshot.objects.count()
            if count > 0:
                latest = FeatureSnapshot.objects.order_by('-created_at').first()
                ts = latest.created_at if latest else '—'
                self._pass(6, f'FeatureSnapshot has {count} records. Latest: {ts}')
                return True
            self._fail(6, 'No FeatureSnapshot records. Person 3 feature engine not running.')
            return False
        except Exception as exc:
            self._fail(6, f'FeatureSnapshot query error: {exc}')
            return False

    def _check_07_agent_risk(self) -> bool:
        from apps.portfolio.models import AgentOutput
        try:
            count = AgentOutput.objects.filter(agent_name='market_risk').count()
            if count > 0:
                dist = {}
                for band in ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']:
                    dist[band] = AgentOutput.objects.filter(
                        agent_name='market_risk', band=band
                    ).count()
                dist_str = ' | '.join(f'{b}:{n}' for b, n in dist.items())
                self._pass(7, f'market_risk AgentOutput: {count} records. Bands: {dist_str}')
                return True
            self._fail(7, 'No market_risk AgentOutput. Person 3 Market Risk Agent not writing to AgentOutput.')
            return False
        except Exception as exc:
            self._fail(7, f'AgentOutput (market_risk) query error: {exc}')
            return False

    def _check_08_agent_sentiment(self) -> bool:
        from apps.portfolio.models import AgentOutput
        try:
            count = AgentOutput.objects.filter(agent_name='sentiment').count()
            if count > 0:
                self._pass(8, f'sentiment AgentOutput: {count} records')
                return True
            self._fail(8, 'No sentiment AgentOutput. Person 4 Sentiment Agent not writing to AgentOutput.')
            return False
        except Exception as exc:
            self._fail(8, f'AgentOutput (sentiment) query error: {exc}')
            return False

    def _check_09_decision_log(self) -> bool:
        from apps.portfolio.models import DecisionLog
        try:
            today = date.today()
            # Field is 'timestamp', not 'created_at'
            count = DecisionLog.objects.filter(timestamp__date=today).count()
            if count > 0:
                dist = {}
                for action in ['HOLD', 'REDUCE', 'EXIT', 'INCREASE', 'REALLOCATE']:
                    dist[action] = DecisionLog.objects.filter(
                        timestamp__date=today, action=action
                    ).count()
                dist_str = ' | '.join(f'{a}:{n}' for a, n in dist.items() if n > 0)
                self._pass(9, f"Today's DecisionLog: {count} entries. {dist_str}")
                return True
            self._fail(9, "No DecisionLog entries for today. Person 4 Decision Agent not running.")
            return False
        except Exception as exc:
            self._fail(9, f'DecisionLog query error: {exc}')
            return False

    def _check_10_state_engine(self) -> bool:
        from apps.portfolio.models import Portfolio, PortfolioStateSnapshot
        from apps.portfolio.state_engine import PortfolioStateEngine
        try:
            portfolio = Portfolio.objects.first()
            if not portfolio:
                self._skip(10, 'No Portfolio object exists yet — skipping State Engine check')
                return True  # Not a pipeline failure
            before_count = PortfolioStateSnapshot.objects.filter(portfolio=portfolio).count()
            PortfolioStateEngine().update_state()
            after_count = PortfolioStateSnapshot.objects.filter(portfolio=portfolio).count()
            if after_count > before_count:
                snap = PortfolioStateSnapshot.objects.filter(portfolio=portfolio).order_by('-timestamp').first()
                self._pass(10, f'PortfolioStateEngine ran OK. Snapshot at: {snap.timestamp}')
                return True
            self._fail(10, 'update_state() ran but no new PortfolioStateSnapshot was created')
            return False
        except Exception as exc:
            self._fail(10, f'State Engine raised: {exc}\n{traceback.format_exc()}')
            return False

    def _check_11_portfolio_agent(self) -> bool:
        from apps.portfolio.models import Portfolio, Position
        from apps.portfolio.portfolio_agent import PortfolioAgent
        try:
            portfolio = Portfolio.objects.first()
            if not portfolio:
                self._skip(11, 'No Portfolio — skipping Portfolio Agent check')
                return True
            has_positions = Position.objects.filter(portfolio=portfolio, quantity__gt=0).exists()
            if not has_positions:
                self._skip(11, 'No open positions — skipping Portfolio Agent Mode 1 check')
                return True
            result = PortfolioAgent().generate_portfolio_suggestion()
            suggestion = result.get('portfolio_summary', '')
            if suggestion:
                self._pass(11, f'Portfolio Agent OK. Summary: "{suggestion[:120]}"')
                return True
            self._fail(11, f'generate_portfolio_suggestion returned empty. Result: {result}')
            return False
        except Exception as exc:
            self._fail(11, f'Portfolio Agent raised: {exc}')
            return False

    def _check_12_llm(self) -> bool:
        try:
            if not settings.CRPMS.get('LLM_ENABLED', False):
                self._skip(12, 'LLM_ENABLED is False in settings')
                return True
            try:
                from apps.portfolio.llm_client import LLMAPIError, llm_client
            except ImportError:
                self._skip(12, 'openai package not installed in venv — run: pip install openai')
                return True
            response = llm_client.generate(
                system_prompt='You are a test assistant. Reply with one word.',
                user_prompt='Say: OK',
            )
            if response:
                self._pass(12, f'LLM Client OK. Response: "{response[:30]}"')
                return True
            self._fail(12, 'LLM returned empty response')
            return False
        except Exception as exc:
            # Catch LLMAPIError (subclass of Exception) and anything else
            self._fail(12, f'LLM Client error: {exc}')
            return False

    # ── main ─────────────────────────────────────────────────────────────────

    def handle(self, *args, **options) -> None:
        self.stdout.write(self.style.HTTP_INFO(
            '\n═══════════════════════════════════════════════════\n'
            '  CRPMS Integration Test — 12 Checks\n'
            '═══════════════════════════════════════════════════'
        ))

        checks = [
            self._check_01_db,
            self._check_02_redis,
            self._check_03_watchlist,
            self._check_04_sector_mapping,
            self._check_05_price_history,
            self._check_06_feature_snapshot,
            self._check_07_agent_risk,
            self._check_08_agent_sentiment,
            self._check_09_decision_log,
            self._check_10_state_engine,
            self._check_11_portfolio_agent,
            self._check_12_llm,
        ]

        passed = 0
        failed = 0

        for fn in checks:
            result = fn()
            if result:
                passed += 1
            else:
                failed += 1

        total = len(checks)
        self.stdout.write(
            '\n═══════════════════════════════════════════════════'
        )
        if failed == 0:
            self.stdout.write(self.style.SUCCESS(
                f'  ✅  {passed}/{total} checks passed. All systems operational.'
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f'  ❌  {passed}/{total} checks passed. {failed} FAILED — fix before demo.'
            ))
        self.stdout.write('═══════════════════════════════════════════════════\n')

        if failed:
            sys.exit(1)
