"""Error dashboard routes for monitoring.

Admin-only routes to view error statistics and logs.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from rot.web.auth import get_current_user_optional, require_tier
from rot.core.error_tracker import get_error_tracker

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/errors/dashboard", response_class=HTMLResponse)
async def error_dashboard(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user_optional),
):
    """Error monitoring dashboard (admin only).

    Shows:
    - Error rate trends
    - Error breakdown by type
    - Recent errors with context
    - Error statistics
    """
    # Admin only
    require_tier("admin")(user)

    tracker = get_error_tracker()

    # Get error stats for different time windows
    stats_24h = tracker.get_error_stats(hours=24)
    stats_1h = tracker.get_error_stats(hours=1)
    error_rate = tracker.get_error_rate()

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Error Dashboard - ROT</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            body {{ background: #0a0a1a; color: #d4d4e8; font-family: 'Inter', sans-serif; }}
            .card {{ background: linear-gradient(135deg, rgba(15, 15, 40, 0.85), rgba(10, 10, 30, 0.95));
                     border: 1px solid rgba(100, 120, 180, 0.2); border-radius: 0.75rem; padding: 1.5rem; }}
            .stat {{ font-size: 2rem; font-weight: bold; }}
            .error-level-error {{ color: #ef4444; }}
            .error-level-warning {{ color: #f59e0b; }}
            .error-level-critical {{ color: #dc2626; }}
        </style>
    </head>
    <body class="p-8">
        <div class="max-w-7xl mx-auto">
            <div class="mb-8">
                <h1 class="text-3xl font-bold text-white mb-2">Error Dashboard</h1>
                <p class="text-gray-400">Real-time error monitoring and analytics</p>
            </div>

            <!-- Summary Cards -->
            <div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
                <div class="card">
                    <div class="text-gray-400 text-sm mb-1">Total Errors (24h)</div>
                    <div class="stat text-red-400">{stats_24h['total_errors']}</div>
                </div>
                <div class="card">
                    <div class="text-gray-400 text-sm mb-1">Errors (1h)</div>
                    <div class="stat text-orange-400">{stats_1h['total_errors']}</div>
                </div>
                <div class="card">
                    <div class="text-gray-400 text-sm mb-1">Error Types</div>
                    <div class="stat text-blue-400">{len(stats_24h['by_type'])}</div>
                </div>
                <div class="card">
                    <div class="text-gray-400 text-sm mb-1">Affected Endpoints</div>
                    <div class="stat text-purple-400">{len(stats_24h['by_endpoint'])}</div>
                </div>
            </div>

            <!-- Error Breakdown -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
                <!-- By Type -->
                <div class="card">
                    <h2 class="text-xl font-semibold text-white mb-4">Errors by Type (24h)</h2>
                    <div class="space-y-2">
                        {''.join([f'''
                        <div class="flex items-center justify-between py-2 border-b border-gray-700">
                            <span class="text-gray-300">{error_type}</span>
                            <span class="text-red-400 font-semibold">{count}</span>
                        </div>
                        ''' for error_type, count in sorted(stats_24h['by_type'].items(), key=lambda x: x[1], reverse=True)[:10]])}
                    </div>
                </div>

                <!-- By Level -->
                <div class="card">
                    <h2 class="text-xl font-semibold text-white mb-4">Errors by Level (24h)</h2>
                    <div class="space-y-2">
                        {''.join([f'''
                        <div class="flex items-center justify-between py-2 border-b border-gray-700">
                            <span class="text-gray-300">{level.title()}</span>
                            <span class="error-level-{level} font-semibold">{count}</span>
                        </div>
                        ''' for level, count in sorted(stats_24h['by_level'].items(), key=lambda x: x[1], reverse=True)])}
                    </div>
                </div>
            </div>

            <!-- Recent Errors -->
            <div class="card">
                <h2 class="text-xl font-semibold text-white mb-4">Recent Errors</h2>
                <div class="overflow-x-auto">
                    <table class="w-full text-sm">
                        <thead class="border-b border-gray-700">
                            <tr class="text-left text-gray-400">
                                <th class="pb-2">Timestamp</th>
                                <th class="pb-2">Type</th>
                                <th class="pb-2">Message</th>
                                <th class="pb-2">Request ID</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-gray-800">
                            {''.join([f'''
                            <tr class="text-gray-300">
                                <td class="py-3">{error['timestamp'][:19]}</td>
                                <td class="py-3"><span class="px-2 py-1 rounded bg-red-900/30 text-red-400 text-xs">{error['type']}</span></td>
                                <td class="py-3 max-w-md truncate">{error['message'][:100]}</td>
                                <td class="py-3"><code class="text-xs text-blue-400">{error.get('request_id', 'N/A')[:16]}</code></td>
                            </tr>
                            ''' for error in stats_24h['recent_errors'][:20]])}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Footer -->
            <div class="mt-8 text-center text-gray-500 text-sm">
                <a href="/dashboard" class="text-blue-400 hover:text-blue-300">← Back to Dashboard</a>
                <span class="mx-2">|</span>
                Error logs stored in /app/data/errors/
            </div>
        </div>
    </body>
    </html>
    """


@router.get("/api/v1/errors/stats")
async def get_error_stats(
    hours: int = 24,
    user: Dict[str, Any] = Depends(get_current_user_optional),
):
    """Get error statistics (admin only).

    Args:
        hours: Number of hours to analyze (default: 24)

    Returns:
        JSON with error statistics
    """
    # Admin only
    require_tier("admin")(user)

    tracker = get_error_tracker()
    stats = tracker.get_error_stats(hours=hours)

    return {
        "success": True,
        "data": stats,
    }


@router.get("/api/v1/errors/rate")
async def get_error_rate(
    user: Dict[str, Any] = Depends(get_current_user_optional),
):
    """Get current error rate (admin only).

    Returns:
        JSON with error counts by type (last hour)
    """
    # Admin only
    require_tier("admin")(user)

    tracker = get_error_tracker()
    rate = tracker.get_error_rate()

    return {
        "success": True,
        "data": {
            "error_counts": rate,
            "total": sum(rate.values()),
        },
    }


@router.post("/api/v1/errors/cleanup")
async def cleanup_old_errors(
    days: int = 30,
    user: Dict[str, Any] = Depends(get_current_user_optional),
):
    """Delete error logs older than N days (admin only).

    Args:
        days: Keep logs from last N days (default: 30)

    Returns:
        JSON with cleanup results
    """
    # Admin only
    require_tier("admin")(user)

    tracker = get_error_tracker()
    deleted = tracker.cleanup_old_logs(days=days)

    return {
        "success": True,
        "data": {
            "deleted_files": deleted,
            "retention_days": days,
        },
    }
