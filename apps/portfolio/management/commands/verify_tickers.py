"""
Management command: verify_tickers

Audits the Watchlist and SectorMapping tables and prints a formatted
summary to the console. Flags orphaned tickers (no SectorMapping) and
thin sectors (fewer than 5 tickers). Safe to run at any time — read-only.

Usage:
    python manage.py verify_tickers
"""

from django.core.management.base import BaseCommand
from django.db.models import Count, Exists, OuterRef

from apps.portfolio.models import SectorMapping, Watchlist

DIVIDER = '─' * 55


class Command(BaseCommand):
    """
    Read-only audit command for sector and ticker data integrity.

    Prints:
      - Per-sector ticker counts (with mini bar chart)
      - Orphan tickers: Watchlist rows with no SectorMapping entry
      - Thin sectors: sectors with fewer than 5 tickers
      - Overall summary line
    """

    help = 'Audits Watchlist and SectorMapping tables — lists sector coverage and data integrity issues.'

    def handle(self, *args, **options):
        """
        Run all audit checks and print results.

        Checks performed:
          1. Total Watchlist and SectorMapping counts.
          2. Tickers per sector (sorted by count descending).
          3. Watchlist rows with no SectorMapping (orphans).
          4. Sectors with fewer than 5 tickers (thin coverage).
        """
        # ── Header ────────────────────────────────────────────────────────
        self.stdout.write('\n' + '═' * 55)
        self.stdout.write('  CRPMS — Ticker & Sector Audit')
        self.stdout.write('═' * 55)

        total_watchlist = Watchlist.objects.count()
        total_mappings  = SectorMapping.objects.count()
        self.stdout.write(f'  Watchlist total    : {total_watchlist}')
        self.stdout.write(f'  SectorMapping rows : {total_mappings}')

        # ── 1. Tickers per sector ─────────────────────────────────────────
        self.stdout.write(f'\n{DIVIDER}')
        self.stdout.write('  TICKERS PER SECTOR')
        self.stdout.write(DIVIDER)

        sector_counts = (
            SectorMapping.objects
            .values('sector')
            .annotate(count=Count('id'))
            .order_by('-count')
        )

        if not sector_counts.exists():
            self.stdout.write(
                self.style.WARNING('  No SectorMapping records found. Run load_sector_data first.')
            )
        else:
            for row in sector_counts:
                bar   = '█' * row['count']
                label = f"  {row['sector']:<20} {row['count']:>3}  {bar}"
                self.stdout.write(label)

        # ── 2. Orphan tickers ─────────────────────────────────────────────
        self.stdout.write(f'\n{DIVIDER}')
        self.stdout.write('  ORPHAN TICKERS  (Watchlist → no SectorMapping)')
        self.stdout.write(DIVIDER)

        has_mapping = SectorMapping.objects.filter(ticker=OuterRef('pk'))
        orphans = (
            Watchlist.objects
            .annotate(has_mapping=Exists(has_mapping))
            .filter(has_mapping=False)
        )

        if orphans.exists():
            for w in orphans:
                self.stdout.write(
                    self.style.WARNING(
                        f'  ⚠  {w.ticker:<28} sector={w.sector or "—"}'
                    )
                )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    '  ✅ No orphans — every Watchlist ticker has a SectorMapping.'
                )
            )

        # ── 3. Thin sectors ───────────────────────────────────────────────
        self.stdout.write(f'\n{DIVIDER}')
        self.stdout.write('  THIN SECTORS  (fewer than 5 tickers)')
        self.stdout.write(DIVIDER)

        thin_sectors = [row for row in sector_counts if row['count'] < 5]

        if thin_sectors:
            for row in thin_sectors:
                self.stdout.write(
                    self.style.WARNING(
                        f"  ⚠  {row['sector']:<20} only {row['count']} ticker(s)"
                    )
                )
        else:
            self.stdout.write(
                self.style.SUCCESS('  ✅ All sectors have 5 or more tickers.')
            )

        # ── Summary ───────────────────────────────────────────────────────
        self.stdout.write(f'\n{"═" * 55}')
        self.stdout.write('  SUMMARY')
        self.stdout.write('═' * 55)

        orphan_count = orphans.count()
        thin_count   = len(thin_sectors)
        status       = '✅ CLEAN' if orphan_count == 0 and thin_count == 0 else '⚠  ISSUES FOUND'

        self.stdout.write(f'  Sectors tracked  : {sector_counts.count()}')
        self.stdout.write(f'  Total tickers    : {total_watchlist}')
        self.stdout.write(f'  Orphan tickers   : {orphan_count}')
        self.stdout.write(f'  Thin sectors     : {thin_count}')

        if orphan_count == 0 and thin_count == 0:
            self.stdout.write(self.style.SUCCESS(f'  Status           : {status}'))
        else:
            self.stdout.write(self.style.ERROR(f'  Status           : {status}'))

        self.stdout.write('═' * 55 + '\n')
