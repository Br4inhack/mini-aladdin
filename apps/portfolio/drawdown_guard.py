"""
apps/portfolio/drawdown_guard.py

Monitors portfolio drawdown and enforces capital preservation mode.

When the portfolio falls 10% below its 90-day peak value, DrawdownGuard
activates and overrides INCREASE / REALLOCATE agent actions to HOLD until
the portfolio recovers to within 7% of peak (hysteresis band).

  compute_current_drawdown()  — calculates live drawdown from snapshot history
  check_guard_status()        — applies hysteresis logic, reads/writes cache
  apply_guard()               — overrides actions when guard is active
  create_guard_alert()        — fires a RISK_CRITICAL alert on activation
  get_guard_summary_text()    — one-line dashboard display string
"""

import logging
from typing import Optional
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.portfolio.models import (
    Alert,
    DecisionLog,
    Portfolio,
    Position,
    PriceHistory,
    PortfolioStateSnapshot,
)
from utils.helpers import get_ist_now

logger = logging.getLogger('apps.portfolio')

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PROTECTED_ACTIONS: list[str] = ['INCREASE', 'REALLOCATE']
CACHE_KEY:         str        = 'portfolio:drawdown_guard_state'
CACHE_TTL:         int        = 900   # 15 minutes

_SNAPSHOT_LOOKBACK_DAYS = 90


class DrawdownGuard:
    """
    Monitors portfolio drawdown and enforces capital preservation.

    Overrides INCREASE and REALLOCATE actions to HOLD when drawdown
    exceeds the configured threshold. Uses hysteresis to prevent
    rapid toggling:

    - **Activates** when drawdown ≥ ``CRPMS['MAX_DRAWDOWN_THRESHOLD']``    (default 10 %)
    - **Deactivates** when drawdown < ``CRPMS['DRAWDOWN_RECOVERY_THRESHOLD']`` (default 7 %)

    Guard state is cached in Redis (15-minute TTL) to avoid recomputing on
    every request. All methods are non-raising; failures are logged and a
    safe default (guard inactive) is returned.

    Example
    -------
    >>> guard = DrawdownGuard()
    >>> status = guard.check_guard_status()
    >>> final_action, reason = guard.apply_guard('INCREASE', 'TCS.NS', status)
    >>> print(final_action)   # 'HOLD' if guard is active
    'HOLD'
    """

    # ── compute_current_drawdown ────────────────────────────────────────────

    def compute_current_drawdown(self) -> dict:
        """
        Calculates the current portfolio drawdown from its 90-day peak value.

        Fetches all open ``Position`` rows to compute current portfolio value,
        then scans ``PortfolioStateSnapshot`` records from the last 90 days to
        find the peak ``total_value`` stored in each snapshot's ``state_data``
        JSON. When no snapshots exist the current value is used as the peak
        (resulting in 0 % drawdown).

        Returns:
            dict: Drawdown metrics::

                {
                    'current_value': float,   # live portfolio value in ₹
                    'peak_value': float,       # highest value in last 90 days
                    'drawdown_pct': float,     # e.g. 0.12 means 12% below peak
                    'drawdown_inr': float,     # rupee gap below peak
                    'computed_at': str,        # IST timestamp
                }

        Example
        -------
        >>> guard = DrawdownGuard()
        >>> dd = guard.compute_current_drawdown()
        >>> dd['drawdown_pct']
        0.034
        """
        try:
            # Step 1: Get active portfolio
            portfolio = Portfolio.objects.first()
            if portfolio is None:
                logger.warning('compute_current_drawdown: no Portfolio found — returning 0% drawdown')
                return self._zero_drawdown()

            # Step 2: Compute current value from open positions
            positions = Position.objects.filter(
                portfolio=portfolio,
                quantity__gt=0,
            ).select_related('watchlist')

            current_value = 0.0
            for pos in positions:
                price = float(pos.current_price or 0)
                if price <= 0:
                    # Fall back to latest PriceHistory close
                    ph = (
                        PriceHistory.objects
                        .filter(ticker__ticker=pos.watchlist.ticker)
                        .order_by('-date')
                        .first()
                    )
                    price = float(ph.close) if ph else 0.0
                current_value += price * pos.quantity
                logger.debug(
                    'compute_current_drawdown: %s qty=%d price=%.2f subtotal=%.2f',
                    pos.watchlist.ticker, pos.quantity, price, price * pos.quantity,
                )

            # Step 3: Find peak value from 90-day snapshot history
            cutoff = timezone.now() - timedelta(days=_SNAPSHOT_LOOKBACK_DAYS)
            snapshots = PortfolioStateSnapshot.objects.filter(
                portfolio=portfolio,
                timestamp__gte=cutoff,
            ).order_by('-timestamp')

            peak_value = current_value  # default: no drawdown if no history
            if snapshots.exists():
                historical_values = []
                for snap in snapshots:
                    val = snap.state_data.get('total_value')
                    if val is not None:
                        try:
                            historical_values.append(float(val))
                        except (TypeError, ValueError):
                            pass
                if historical_values:
                    peak_value = max(historical_values)
                    logger.debug(
                        'compute_current_drawdown: %d snapshots found, peak=₹%.2f',
                        len(historical_values), peak_value,
                    )

            # Step 4: Compute drawdown
            if peak_value > 0:
                drawdown_pct = (peak_value - current_value) / peak_value
            else:
                drawdown_pct = 0.0

            drawdown_pct = max(0.0, drawdown_pct)   # never negative
            drawdown_inr = round(peak_value - current_value, 2)

            result = {
                'current_value': round(current_value, 2),
                'peak_value':    round(peak_value, 2),
                'drawdown_pct':  round(drawdown_pct, 6),
                'drawdown_inr':  drawdown_inr,
                'computed_at':   get_ist_now().isoformat(),
            }
            logger.debug(
                'compute_current_drawdown: value=₹%.2f peak=₹%.2f drawdown=%.2f%%',
                current_value, peak_value, drawdown_pct * 100,
            )
            return result

        except Exception as exc:
            logger.error('compute_current_drawdown: unexpected error: %s', exc, exc_info=True)
            return self._zero_drawdown()

    # ── check_guard_status ──────────────────────────────────────────────────

    def check_guard_status(self) -> dict:
        """
        Determines whether the Drawdown Guard should be active.

        Applies hysteresis: the guard activates at the trigger threshold and
        only deactivates after the portfolio recovers past the lower recovery
        threshold — preventing flickering around the trigger boundary.

        Guard state is read from and written back to Redis cache so the
        computation only runs once per ``CACHE_TTL`` (15 minutes) cycle.

        Returns:
            dict: Guard status payload::

                {
                    'active': bool,
                    'drawdown_pct': float,
                    'drawdown_inr': float,
                    'trigger_threshold': float,
                    'recovery_threshold': float,
                    'message': str,
                    'activated_at': str | None,
                }

        Example
        -------
        >>> guard = DrawdownGuard()
        >>> status = guard.check_guard_status()
        >>> status['active']
        False
        """
        try:
            # Check master switch
            guard_enabled = settings.CRPMS.get('DRAWDOWN_GUARD_ENABLED', True)
            if not guard_enabled:
                return self._inactive_status(0.0, 0.0)

            crpms           = settings.CRPMS
            trigger         = float(crpms.get('MAX_DRAWDOWN_THRESHOLD', 0.10))
            recovery        = float(crpms.get('DRAWDOWN_RECOVERY_THRESHOLD', 0.07))

            # Read cached state (handles Redis failure gracefully)
            try:
                cached_state = cache.get(CACHE_KEY) or {'active': False}
            except Exception as cache_err:
                logger.warning('check_guard_status: Redis read failed: %s', cache_err)
                cached_state = {'active': False}

            currently_active: bool        = cached_state.get('active', False)
            activated_at:     Optional[str] = cached_state.get('activated_at')

            # Compute live drawdown
            dd = self.compute_current_drawdown()
            drawdown_pct = dd['drawdown_pct']
            drawdown_inr = dd['drawdown_inr']

            # Hysteresis state machine
            new_active = currently_active
            if not currently_active and drawdown_pct >= trigger:
                new_active   = True
                activated_at = get_ist_now().isoformat()
                logger.warning(
                    'DrawdownGuard ACTIVATED — drawdown=%.2f%% exceeds trigger=%.0f%%',
                    drawdown_pct * 100, trigger * 100,
                )
            elif currently_active and drawdown_pct < recovery:
                new_active = False
                logger.warning(
                    'DrawdownGuard DEACTIVATED — drawdown=%.2f%% recovered below %.0f%%',
                    drawdown_pct * 100, recovery * 100,
                )
                activated_at = None

            # Build and cache state dict
            if new_active:
                message = (
                    f'Drawdown Guard ACTIVE — portfolio is {drawdown_pct * 100:.1f}% below '
                    f'peak (₹{drawdown_inr:,.0f}). INCREASE and REALLOCATE suspended until '
                    f'recovery below {recovery * 100:.0f}%.'
                )
            else:
                message = (
                    f'Drawdown Guard inactive — drawdown is {drawdown_pct * 100:.2f}%, '
                    f'within the {trigger * 100:.0f}% safe threshold.'
                )

            state = {
                'active':              new_active,
                'drawdown_pct':        drawdown_pct,
                'drawdown_inr':        drawdown_inr,
                'trigger_threshold':   trigger,
                'recovery_threshold':  recovery,
                'message':             message,
                'activated_at':        activated_at,
            }

            try:
                cache.set(CACHE_KEY, state, timeout=CACHE_TTL)
            except Exception as cache_err:
                logger.warning('check_guard_status: Redis write failed: %s', cache_err)

            return state

        except Exception as exc:
            logger.error('check_guard_status: unexpected error: %s', exc, exc_info=True)
            return self._inactive_status(0.0, 0.0)

    # ── apply_guard ─────────────────────────────────────────────────────────

    def apply_guard(
        self,
        action: str,
        ticker: str,
        guard_status: dict,
    ) -> tuple[str, str]:
        """
        Applies the drawdown guard override to a recommended action.

        Only modifies actions listed in ``PROTECTED_ACTIONS``
        (``INCREASE`` and ``REALLOCATE``). All other actions pass through
        unchanged. When the guard is inactive nothing is modified.

        Args:
            action (str): Original recommended action from the decision engine.
            ticker (str): Ticker symbol this action applies to (used in log).
            guard_status (dict): Output from :meth:`check_guard_status`.

        Returns:
            tuple[str, str]: ``(final_action, override_reason)`` where
            ``override_reason`` is an empty string when no override occurred.

        Example
        -------
        >>> guard = DrawdownGuard()
        >>> status = {'active': True, 'drawdown_pct': 0.12, 'recovery_threshold': 0.07}
        >>> guard.apply_guard('INCREASE', 'TCS.NS', status)
        ('HOLD', 'Drawdown Guard active: portfolio is 12.0% below peak...')
        """
        try:
            if not guard_status.get('active', False):
                return (action, '')

            if action.upper() in PROTECTED_ACTIONS:
                drawdown_pct       = guard_status.get('drawdown_pct', 0.0)
                recovery_threshold = guard_status.get('recovery_threshold', 0.07)
                override_reason = (
                    f'Drawdown Guard active: portfolio is '
                    f'{drawdown_pct * 100:.1f}% below peak. '
                    f'{action} action converted to HOLD to preserve capital. '
                    f'Guard will deactivate when drawdown recovers below '
                    f'{recovery_threshold * 100:.0f}%.'
                )
                logger.warning(
                    'DrawdownGuard: overriding %s → HOLD for %s (drawdown=%.2f%%)',
                    action, ticker, drawdown_pct * 100,
                )
                return ('HOLD', override_reason)

            return (action, '')

        except Exception as exc:
            logger.error('apply_guard: unexpected error for %s: %s', ticker, exc)
            return (action, '')   # safe pass-through on failure

    # ── create_guard_alert ──────────────────────────────────────────────────

    def create_guard_alert(self, guard_status: dict) -> Optional[Alert]:
        """
        Creates a ``RISK_CRITICAL`` Alert when the Drawdown Guard activates.

        Only fires when the guard just became active and no existing
        unacknowledged guard alert exists, preventing duplicate alerts.

        Args:
            guard_status (dict): Output of :meth:`check_guard_status`.

        Returns:
            Optional[Alert]: The newly created ``Alert`` instance, or ``None``
            if the guard is inactive or an alert was already raised.

        Example
        -------
        >>> guard = DrawdownGuard()
        >>> alert = guard.create_guard_alert(status)
        >>> alert is not None   # True only on first activation
        True
        """
        try:
            if not guard_status.get('active', False):
                return None

            drawdown_pct       = guard_status.get('drawdown_pct', 0.0)
            recovery_threshold = guard_status.get('recovery_threshold', 0.07)

            message = (
                f'Drawdown Guard Activated: Portfolio is {drawdown_pct * 100:.1f}% below '
                f'peak value. Capital preservation mode: INCREASE and REALLOCATE actions '
                f'suspended until portfolio recovers to within {recovery_threshold * 100:.0f}% '
                f'of peak.'
            )

            # Avoid duplicate alerts — check for existing unacknowledged guard alert
            existing = Alert.objects.filter(
                alert_type=Alert.AlertType.RISK_CRITICAL,
                message__startswith='Drawdown Guard Activated',
                is_acknowledged=False,
            ).exists()

            if existing:
                logger.debug('create_guard_alert: unacknowledged guard alert already exists — skipping')
                return None

            # Guard alerts are portfolio-level, not ticker-specific.
            # Use the first Watchlist entry as a placeholder FK target.
            from apps.portfolio.models import Watchlist
            placeholder = Watchlist.objects.filter(is_active=True).first()
            if placeholder is None:
                logger.warning('create_guard_alert: no active Watchlist entry to attach alert to')
                return None

            alert = Alert.objects.create(
                ticker=placeholder,
                alert_type=Alert.AlertType.RISK_CRITICAL,
                message=message,
                threshold_breached=drawdown_pct,
                is_acknowledged=False,
            )
            logger.warning('create_guard_alert: RISK_CRITICAL alert created (id=%s)', alert.pk)
            return alert

        except Exception as exc:
            logger.error('create_guard_alert: unexpected error: %s', exc, exc_info=True)
            return None

    # ── get_guard_summary_text ──────────────────────────────────────────────

    def get_guard_summary_text(self, guard_status: dict) -> str:
        """
        Returns a one-line human-readable summary for dashboard display.

        Args:
            guard_status (dict): Output of :meth:`check_guard_status`.

        Returns:
            str: Emoji-prefixed status line suitable for a dashboard widget.

        Example
        -------
        >>> guard.get_guard_summary_text({'active': False, 'drawdown_pct': 0.03})
        '✅ Drawdown Guard inactive — Portfolio within normal range.'
        """
        try:
            if guard_status.get('active', False):
                drawdown_pct = guard_status.get('drawdown_pct', 0.0)
                return (
                    f'⚠️ Drawdown Guard ACTIVE — '
                    f'Portfolio is {drawdown_pct * 100:.1f}% below peak. '
                    f'INCREASE and REALLOCATE actions suspended.'
                )
            return '✅ Drawdown Guard inactive — Portfolio within normal range.'

        except Exception as exc:
            logger.error('get_guard_summary_text: error: %s', exc)
            return '⚠️ Drawdown Guard status unavailable.'

    # ── Private helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _zero_drawdown() -> dict:
        """Returns a safe zero-drawdown dict used on computation failure."""
        return {
            'current_value': 0.0,
            'peak_value':    0.0,
            'drawdown_pct':  0.0,
            'drawdown_inr':  0.0,
            'computed_at':   get_ist_now().isoformat(),
        }

    @staticmethod
    def _inactive_status(drawdown_pct: float, drawdown_inr: float) -> dict:
        """Returns a safe inactive guard status dict."""
        crpms = getattr(settings, 'CRPMS', {})
        return {
            'active':             False,
            'drawdown_pct':       drawdown_pct,
            'drawdown_inr':       drawdown_inr,
            'trigger_threshold':  float(crpms.get('MAX_DRAWDOWN_THRESHOLD', 0.10)),
            'recovery_threshold': float(crpms.get('DRAWDOWN_RECOVERY_THRESHOLD', 0.07)),
            'message':            'Drawdown Guard disabled or data unavailable.',
            'activated_at':       None,
        }
