"""
Management command: backfill_prices

Seeds the database with historical price, fundamental, and macro data
for all active watchlist tickers. Run once after initial deployment.

Usage:
    python manage.py backfill_prices
    python manage.py backfill_prices --days 365
    python manage.py backfill_prices --days 365 --ticker RELIANCE
    python manage.py backfill_prices --skip-macro
    python manage.py backfill_prices --skip-fundamentals
    python manage.py backfill_prices --dry-run
"""
from __future__ import annotations

import datetime as dt
import logging

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Backfill historical price, fundamental, and macro data for all '
        'active watchlist tickers. Run once after initial deployment.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=365 * 3,
            help='Number of days to look back (default: 1095 = 3 years).',
        )
        parser.add_argument(
            '--ticker',
            type=str,
            default=None,
            help='Restrict price + fundamentals backfill to a single ticker.',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=10,
            dest='batch_size',
            help='Number of tickers to download in one yfinance batch call (default: 10).',
        )
        parser.add_argument(
            '--skip-prices',
            action='store_true',
            default=False,
            help='Skip OHLCV price history ingestion.',
        )
        parser.add_argument(
            '--skip-fundamentals',
            action='store_true',
            default=False,
            help='Skip fundamental data ingestion.',
        )
        parser.add_argument(
            '--skip-macro',
            action='store_true',
            default=False,
            help='Skip macro indicator ingestion (RBI + FRED).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Print what would be done without writing to the database.',
        )

    def handle(self, *args, **options):
        from apps.portfolio.models import Watchlist
        from apps.data_ingestion.services import (
            MarketDataIngester,
            MacroIngester,
            RBIDataIngester,
        )

        days: int = options['days']
        ticker: str | None = options['ticker']
        batch_size: int = options['batch_size']
        dry_run: bool = options['dry_run']

        end_date = timezone.now().date()
        start_date = end_date - dt.timedelta(days=days)

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN — no data will be written.'))

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f'\n=== CRPMS Data Backfill ===\n'
                f'  Range  : {start_date} → {end_date} ({days} days)\n'
                f'  Ticker : {ticker or "ALL active"}\n'
                f'  Batch  : {batch_size}\n'
            )
        )

        # ── 1. Price History ─────────────────────────────────────────────────
        if not options['skip_prices']:
            self.stdout.write('\n[1/3] Ingesting OHLCV price history ...')
            if dry_run:
                tickers = (
                    [ticker.upper()]
                    if ticker
                    else list(
                        Watchlist.objects.filter(is_active=True).values_list('ticker', flat=True)
                    )
                )
                self.stdout.write(
                    self.style.NOTICE(
                        f'  Would download {len(tickers)} tickers in batches of {batch_size}.'
                    )
                )
            else:
                ingester = MarketDataIngester()
                if ticker:
                    try:
                        written = ingester.ingest_ticker_history(
                            ticker=ticker.upper(),
                            start_date=start_date,
                            end_date=end_date,
                        )
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'  ✓ {ticker.upper()}: {written} new rows written.'
                            )
                        )
                    except Exception as exc:
                        raise CommandError(f'Price ingestion failed for {ticker}: {exc}') from exc
                else:
                    results = ingester.ingest_watchlist_history_batch(
                        start_date=start_date,
                        end_date=end_date,
                        batch_size=batch_size,
                    )
                    total = sum(results.values())
                    failed = [t for t, n in results.items() if n == 0]
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'  ✓ {len(results)} tickers processed | '
                            f'{total} new rows | '
                            f'{len(failed)} with 0 rows written'
                        )
                    )
                    if failed:
                        self.stdout.write(
                            self.style.WARNING(f'  ⚠ Zero-row tickers: {", ".join(failed[:20])}')
                        )

                # Also fetch index benchmarks
                self.stdout.write('  Fetching NIFTY50 / SENSEX benchmarks ...')
                try:
                    bench = ingester.ingest_benchmark_history(
                        start_date=start_date, end_date=end_date
                    )
                    for sym, n in bench.items():
                        self.stdout.write(self.style.SUCCESS(f'  ✓ {sym}: {n} rows'))
                except Exception as exc:
                    self.stdout.write(self.style.WARNING(f'  ⚠ Benchmark ingestion error: {exc}'))
        else:
            self.stdout.write(self.style.NOTICE('[1/3] Skipping price history (--skip-prices).'))

        # ── 2. Fundamentals ──────────────────────────────────────────────────
        if not options['skip_fundamentals']:
            self.stdout.write('\n[2/3] Ingesting fundamental data ...')
            if dry_run:
                tickers = (
                    [ticker.upper()]
                    if ticker
                    else list(
                        Watchlist.objects.filter(is_active=True).values_list('ticker', flat=True)
                    )
                )
                self.stdout.write(
                    self.style.NOTICE(f'  Would fetch fundamentals for {len(tickers)} tickers.')
                )
            else:
                ingester = MarketDataIngester()
                tickers_to_process = (
                    [ticker.upper()]
                    if ticker
                    else list(
                        Watchlist.objects.filter(is_active=True).values_list('ticker', flat=True)
                    )
                )
                ok, failed = 0, 0
                for t in tickers_to_process:
                    try:
                        ingester.ingest_fundamentals(ticker=t, period='LATEST')
                        ok += 1
                    except Exception as exc:
                        logger.warning('Fundamentals failed for %s: %s', t, exc)
                        failed += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f'  ✓ {ok} tickers OK | {failed} failed'
                    )
                )
        else:
            self.stdout.write(self.style.NOTICE('[2/3] Skipping fundamentals (--skip-fundamentals).'))

        # ── 3. Macro Indicators ──────────────────────────────────────────────
        if not options['skip_macro'] and not ticker:
            self.stdout.write('\n[3/3] Ingesting macro indicators ...')

            if dry_run:
                self.stdout.write(
                    self.style.NOTICE(
                        '  Would ingest: RBI repo rate, CPI India, INR/USD, '
                        'US GDP, US CPI, US Fed Funds.'
                    )
                )
            else:
                # RBI data
                self.stdout.write('  → RBI indicators (repo rate, CPI India, INR/USD) ...')
                try:
                    rbi = RBIDataIngester()
                    rbi_results = rbi.ingest_all_indicators(
                        start_date=start_date, end_date=end_date
                    )
                    for name, n in rbi_results.items():
                        self.stdout.write(self.style.SUCCESS(f'  ✓ {name}: {n} rows'))
                except Exception as exc:
                    self.stdout.write(self.style.WARNING(f'  ⚠ RBI ingestion error: {exc}'))

                # FRED data
                fred_indicators = [
                    ('US_GDP', 'GDP'),
                    ('US_CPI', 'CPIAUCSL'),
                    ('US_FED_FUNDS', 'FEDFUNDS'),
                    ('US_UNEMPLOYMENT', 'UNRATE'),
                    ('US_10Y_YIELD', 'GS10'),
                ]
                macro = MacroIngester()
                for name, code in fred_indicators:
                    self.stdout.write(f'  → FRED {name} ({code}) ...')
                    try:
                        n = macro.ingest_fred_indicator(
                            indicator_name=name,
                            fred_code=code,
                            start_date=start_date,
                            end_date=end_date,
                        )
                        self.stdout.write(self.style.SUCCESS(f'  ✓ {name}: {n} rows'))
                    except Exception as exc:
                        self.stdout.write(
                            self.style.WARNING(f'  ⚠ FRED {code} failed: {exc}')
                        )
        elif options['skip_macro']:
            self.stdout.write(self.style.NOTICE('[3/3] Skipping macro (--skip-macro).'))
        else:
            self.stdout.write(self.style.NOTICE('[3/3] Skipping macro (single-ticker mode).'))

        self.stdout.write(
            self.style.SUCCESS(
                '\n=== Backfill complete! ===\n'
                'Run: python manage.py shell -c '
                '"from apps.data_ingestion.services import DataQualityCheck; '
                'print(DataQualityCheck().validate_expected_ticker_coverage(73))"\n'
                'to verify coverage.\n'
            )
        )
