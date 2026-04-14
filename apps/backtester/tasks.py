"""
Celery tasks for the CRPMS Backtester phase.
"""

from datetime import datetime
from celery import shared_task
from celery.utils.log import get_task_logger
import traceback


@shared_task(bind=True, max_retries=1, default_retry_delay=60)
def run_backtest_task(self, start_date_str: str, end_date_str: str) -> dict:
    logger = get_task_logger(__name__)
    logger.info("Starting run_backtest_task: %s to %s", start_date_str, end_date_str)
    
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        from apps.backtester.backtest_engine import CRPMSBacktester
        result = CRPMSBacktester().run(start_date, end_date)
        
        # Mapped to exact BacktestResult fields
        return {
            'status': 'complete',
            'backtest_id': result.id,
            'strategy': result.run_name,
            'total_return': result.cagr,
            'sharpe_ratio': result.sharpe_ratio,
            'max_drawdown': result.max_drawdown,
            'benchmark_return': result.benchmark_results.get('benchmark_return', 0.0) if result.benchmark_results else 0.0,
        }
    except Exception as exc:
        logger.error(f"run_backtest_task failed: {exc}")
        logger.error(traceback.format_exc())
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return {'status': 'failed', 'error': str(exc)}
