"""
Management command: load_sector_data

Bulk-loads all NSE sector-ticker mappings into the Watchlist
and SectorMapping tables. Safe to run multiple times (idempotent).

Usage:
    python manage.py load_sector_data
    python manage.py load_sector_data --clear
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.portfolio.models import SectorMapping, Watchlist

# ---------------------------------------------------------------------------
# Sector → ticker master map
# Each value is a list of (ticker_symbol, company_name) tuples.
# ---------------------------------------------------------------------------
SECTOR_TICKER_MAP = {
    'IT': [
        ('TCS.NS',          'Tata Consultancy Services'),
        ('INFY.NS',         'Infosys'),
        ('WIPRO.NS',        'Wipro'),
        ('HCLTECH.NS',      'HCL Technologies'),
        ('TECHM.NS',        'Tech Mahindra'),
        ('LTIM.NS',         'LTIMindtree'),
        ('PERSISTENT.NS',   'Persistent Systems'),
        ('COFORGE.NS',      'Coforge'),
        ('MPHASIS.NS',      'Mphasis'),
        ('OFSS.NS',         'Oracle Financial Services'),
    ],
    'Banking': [
        ('HDFCBANK.NS',     'HDFC Bank'),
        ('ICICIBANK.NS',    'ICICI Bank'),
        ('KOTAKBANK.NS',    'Kotak Mahindra Bank'),
        ('SBIN.NS',         'State Bank of India'),
        ('AXISBANK.NS',     'Axis Bank'),
        ('INDUSINDBK.NS',   'IndusInd Bank'),
        ('BANDHANBNK.NS',   'Bandhan Bank'),
        ('FEDERALBNK.NS',   'Federal Bank'),
        ('IDFCFIRSTB.NS',   'IDFC First Bank'),
        ('PNB.NS',          'Punjab National Bank'),
    ],
    'Pharma': [
        ('SUNPHARMA.NS',    'Sun Pharmaceutical'),
        ('DRREDDY.NS',      'Dr Reddys Laboratories'),
        ('CIPLA.NS',        'Cipla'),
        ('DIVISLAB.NS',     'Divis Laboratories'),
        ('BIOCON.NS',       'Biocon'),
        ('AUROPHARMA.NS',   'Aurobindo Pharma'),
        ('ALKEM.NS',        'Alkem Laboratories'),
        ('TORNTPHARM.NS',   'Torrent Pharmaceuticals'),
        ('ABBOTINDIA.NS',   'Abbott India'),
        ('GLAND.NS',        'Gland Pharma'),
    ],
    'FMCG': [
        ('HINDUNILVR.NS',   'Hindustan Unilever'),
        ('NESTLEIND.NS',    'Nestle India'),
        ('BRITANNIA.NS',    'Britannia Industries'),
        ('DABUR.NS',        'Dabur India'),
        ('MARICO.NS',       'Marico'),
        ('GODREJCP.NS',     'Godrej Consumer Products'),
        ('TATACONSUM.NS',   'Tata Consumer Products'),
        ('COLPAL.NS',       'Colgate-Palmolive India'),
    ],
    'Auto': [
        ('MARUTI.NS',       'Maruti Suzuki'),
        ('TATAMOTORS.NS',   'Tata Motors'),
        ('BAJAJ-AUTO.NS',   'Bajaj Auto'),
        ('HEROMOTOCO.NS',   'Hero MotoCorp'),
        ('EICHERMOT.NS',    'Eicher Motors'),
        ('TVSMOTORS.NS',    'TVS Motor Company'),
        ('ASHOKLEY.NS',     'Ashok Leyland'),
        ('MOTHERSON.NS',    'Motherson Sumi Systems'),
    ],
    'Energy': [
        ('RELIANCE.NS',     'Reliance Industries'),
        ('ONGC.NS',         'Oil and Natural Gas Corporation'),
        ('BPCL.NS',         'Bharat Petroleum'),
        ('IOC.NS',          'Indian Oil Corporation'),
        ('GAIL.NS',         'GAIL India'),
        ('POWERGRID.NS',    'Power Grid Corporation'),
        ('NTPC.NS',         'NTPC'),
        ('TATAPOWER.NS',    'Tata Power'),
    ],
    'Metals': [
        ('TATASTEEL.NS',    'Tata Steel'),
        ('JSWSTEEL.NS',     'JSW Steel'),
        ('HINDALCO.NS',     'Hindalco Industries'),
        ('VEDL.NS',         'Vedanta'),
        ('COALINDIA.NS',    'Coal India'),
        ('NMDC.NS',         'NMDC'),
        ('SAIL.NS',         'Steel Authority of India'),
        ('HINDZINC.NS',     'Hindustan Zinc'),
    ],
    'Finance': [
        ('BAJFINANCE.NS',   'Bajaj Finance'),
        ('BAJAJFINSV.NS',   'Bajaj Finserv'),
        ('LICHSGFIN.NS',    'LIC Housing Finance'),
        ('MUTHOOTFIN.NS',   'Muthoot Finance'),
        ('CHOLAFIN.NS',     'Cholamandalam Investment'),
        ('PFC.NS',          'Power Finance Corporation'),
        ('RECLTD.NS',       'REC Limited'),
    ],
    'Infrastructure': [
        ('LARSEN.NS',        'Larsen and Toubro'),
        ('ULTRACEMCO.NS',    'UltraTech Cement'),
        ('GRASIM.NS',        'Grasim Industries'),
        ('ACC.NS',           'ACC'),
        ('AMBUJACEMENT.NS',  'Ambuja Cements'),
        ('DLF.NS',           'DLF'),
        ('GODREJPROP.NS',    'Godrej Properties'),
    ],
    'Telecom': [
        ('BHARTIARTL.NS',   'Bharti Airtel'),
        ('INDUSTOWER.NS',   'Indus Towers'),
        ('TATACOMM.NS',     'Tata Communications'),
    ],
}


class Command(BaseCommand):
    """
    Django management command that bulk-loads NSE sector-ticker mappings.

    Iterates over SECTOR_TICKER_MAP, upserts each ticker into the Watchlist
    table, and creates the corresponding SectorMapping record. The entire
    operation runs inside a single atomic transaction — all records load or
    none do. Safe to run multiple times; uses get_or_create throughout.
    """

    help = 'Loads NSE sector-ticker mappings into the database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear all existing SectorMapping records before loading.',
        )

    def handle(self, *args, **options):
        """
        Execute the sector data load.

        Steps:
          1. Optionally clear SectorMapping table (--clear flag).
          2. Iterate each sector and ticker tuple.
          3. get_or_create Watchlist entry; update sector if already present.
          4. get_or_create SectorMapping entry.
          5. Print a summary of totals.
        """
        self.stdout.write('Starting sector data load...')

        try:
            with transaction.atomic():

                # ── Optional wipe ─────────────────────────────────────────
                if options['clear']:
                    self.stdout.write(
                        self.style.WARNING(
                            '⚠  --clear flag set: deleting all SectorMapping records...'
                        )
                    )
                    deleted_count, _ = SectorMapping.objects.all().delete()
                    self.stdout.write(
                        self.style.WARNING(f'   Deleted {deleted_count} SectorMapping records.')
                    )

                # ── Load loop ─────────────────────────────────────────────
                total_tickers = 0
                total_sectors = 0

                for sector, ticker_list in SECTOR_TICKER_MAP.items():
                    total_sectors += 1
                    sector_count = 0

                    for ticker_symbol, company_name in ticker_list:

                        # Upsert Watchlist
                        watchlist_obj, created = Watchlist.objects.get_or_create(
                            ticker=ticker_symbol,
                            defaults={
                                'company_name': company_name,
                                'sector': sector,
                                'exchange': 'NSE',
                                'is_active': True,
                            },
                        )

                        if not created:
                            # Keep sector in sync if ticker already existed
                            watchlist_obj.sector = sector
                            watchlist_obj.save(update_fields=['sector'])

                        # Upsert SectorMapping
                        SectorMapping.objects.get_or_create(
                            ticker=watchlist_obj,
                            sector=sector,
                        )

                        sector_count += 1
                        total_tickers += 1

                    self.stdout.write(
                        f'  ✔  {sector:<18} — {sector_count} tickers loaded'
                    )

            # ── Summary ───────────────────────────────────────────────────
            active_count = Watchlist.objects.filter(is_active=True).count()

            self.stdout.write(self.style.SUCCESS(
                f'\nLoaded {total_tickers} tickers across {total_sectors} sectors.'
            ))
            self.stdout.write(self.style.SUCCESS(
                f'Watchlist now has {active_count} active tickers.'
            ))

        except Exception as exc:
            self.stdout.write(
                self.style.ERROR(f'❌ Error during sector load: {exc}')
            )
            self.stdout.write(
                self.style.ERROR('Transaction rolled back — no data was written.')
            )
            raise
