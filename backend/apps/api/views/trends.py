"""Long-term trend analysis and capacity planning (weakness 3 in section 3.1.1; evaluation E9).

Every query aggregates in PostgreSQL and is cached for 10 minutes (D28).
"""
import csv
import io
import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
from django.db import connection
from django.http import HttpResponse
from rest_framework.response import Response
from rest_framework.views import APIView

from ..services import cache, hours_param, latest_cycle, thresholds
from .alerts import link_labels

RANGES = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "14d": timedelta(days=14)}
TREND_TTL = 600.0
WAT = ZoneInfo("Africa/Lagos")      # network times are shown in West Africa Time (D18)
FULL_DAY_HOURS = 20                 # a day with a shorter span of readings is left out of capacity planning
MAX_PROJECTION_DAYS = 3650          # ten years: further out, a straight line through two weeks means nothing


def _range(request) -> tuple[str, timedelta]:
    key = request.query_params.get("range", "24h")
    return (key, RANGES[key]) if key in RANGES else ("24h", RANGES["24h"])


def _link_param(request) -> int | None:
    value = request.query_params.get("link")
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        from rest_framework.exceptions import ValidationError
        raise ValidationError({"link": "must be a link id"}) from None


def _query(sql: str, params: list) -> list[tuple]:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


class LinkTrendsView(APIView):
    """Without `link`: one summary row per link. With `link`: that link's bucketed series."""

    def get(self, request):
        key, span = _range(request)
        link = _link_param(request)
        end = latest_cycle()
        if end is None:
            return Response({"range": key, "links": [], "points": []})
        cache_key = ("trends", key, link, end.replace(minute=0, second=0, microsecond=0))
        cached = cache.get(cache_key, TREND_TTL)
        if cached is not None:
            return Response(cached)
        start = end - span
        bucket = "1 hour" if key != "24h" else "10 minutes"
        if link is not None:
            rows = _query(
                "SELECT date_bin(%s::interval, timestamp, TIMESTAMPTZ '2000-01-01') AS t, avg(utilisation_pct), "
                "percentile_cont(0.95) WITHIN GROUP (ORDER BY utilisation_pct), max(utilisation_pct) "
                "FROM monitoring_record WHERE link_id = %s AND timestamp > %s AND timestamp <= %s "
                "GROUP BY t ORDER BY t", [bucket, link, start, end])
            payload = {"range": key, "bucket": bucket, "link_id": link, "thresholds": thresholds(),
                       "points": [{"t": r[0].isoformat(), "avg_pct": _r(r[1]), "p95_pct": _r(r[2]),
                                   "max_pct": _r(r[3])} for r in rows]}
        else:
            rows = _query(
                "SELECT link_id, avg(utilisation_pct), percentile_cont(0.95) WITHIN GROUP (ORDER BY utilisation_pct), "
                "max(utilisation_pct), count(*) FILTER (WHERE utilisation_pct >= %s), count(*) "
                "FROM monitoring_record WHERE link_id IS NOT NULL AND timestamp > %s AND timestamp <= %s "
                "GROUP BY link_id", [thresholds()["warning_pct"], start, end])
            labels = link_labels()
            links = [{"link_id": r[0], "label": labels.get(r[0], str(r[0])), "avg_pct": _r(r[1]), "p95_pct": _r(r[2]),
                      "max_pct": _r(r[3]), "share_elevated_pct": _r(100 * r[4] / r[5]) if r[5] else None}
                     for r in rows]
            links.sort(key=lambda lk: -(lk["p95_pct"] or 0))
            payload = {"range": key, "thresholds": thresholds(), "links": links}
        cache.set(cache_key, payload)
        return Response(payload)


class NetworkTrendView(APIView):
    """Average and peak utilisation across all links: per cycle up to 6 h, in 10-minute buckets up
    to 24 h (the overview's network trend), and hourly up to 14 days (the Trends page's period)."""

    def get(self, request):
        hours = hours_param(request, 1, 14 * 24)
        end = latest_cycle()
        if end is None:
            return Response({"hours": hours, "points": []})
        long = hours > 24
        # Up to 24 h the trend follows every cycle. A longer one is a heavy query that changes
        # slowly, so, like the link trends, it is cached by the hour for 10 minutes.
        cache_key = ("network-trend", hours, end.replace(minute=0, second=0, microsecond=0) if long else end)
        cached = cache.get(cache_key, TREND_TTL if long else 60.0)
        if cached is not None:
            return Response(cached)
        bucket = "1 hour" if long else (None if hours <= 6 else "10 minutes")
        if bucket is None:
            rows = _query("SELECT timestamp, avg(utilisation_pct), max(utilisation_pct) FROM monitoring_record "
                          "WHERE link_id IS NOT NULL AND timestamp > %s AND timestamp <= %s "
                          "GROUP BY timestamp ORDER BY timestamp", [end - timedelta(hours=hours), end])
        else:
            rows = _query("SELECT date_bin(%s::interval, timestamp, TIMESTAMPTZ '2000-01-01') AS t, "
                          "avg(utilisation_pct), max(utilisation_pct) FROM monitoring_record "
                          "WHERE link_id IS NOT NULL AND timestamp > %s AND timestamp <= %s GROUP BY t ORDER BY t",
                          [bucket, end - timedelta(hours=hours), end])
        payload = {"hours": hours, "bucket": bucket, "thresholds": thresholds(),
                   "points": [{"t": r[0].isoformat(), "avg_pct": _r(r[1]), "max_pct": _r(r[2])} for r in rows]}
        cache.set(cache_key, payload)
        return Response(payload)


class HeatmapView(APIView):
    """Average utilisation by weekday and hour (West Africa Time): quiet windows for maintenance."""

    def get(self, request):
        link = _link_param(request)
        end = latest_cycle()
        if end is None:
            return Response({"cells": []})
        cache_key = ("heatmap", link, end.date())
        cached = cache.get(cache_key, TREND_TTL)
        if cached is not None:
            return Response(cached)
        where, params = ("link_id = %s", [link]) if link is not None else ("link_id IS NOT NULL", [])
        rows = _query(
            "SELECT extract(isodow FROM timestamp AT TIME ZONE 'Africa/Lagos')::int, "
            "extract(hour FROM timestamp AT TIME ZONE 'Africa/Lagos')::int, avg(utilisation_pct) "
            f"FROM monitoring_record WHERE {where} AND timestamp > %s AND timestamp <= %s GROUP BY 1, 2",
            params + [end - RANGES["14d"], end])
        payload = {"link_id": link, "thresholds": thresholds(),
                   "cells": [{"weekday": r[0], "hour": r[1], "avg_pct": _r(r[2])} for r in rows]}
        cache.set(cache_key, payload)
        return Response(payload)


def trend_design(days: list) -> np.ndarray:
    """Columns of the capacity fit (`days` are WAT dates): 1 and the day number, then levels for the
    weekly pattern.
    - 9 days or more: one level per day of the week, so the growth compares each weekday with the
      same weekday a week earlier.
    - 5 to 8 days: one level for Saturdays and Sundays together.
    - Fewer days: a plain line."""
    x = np.array([(d - days[0]).days for d in days], dtype=float)
    columns = [np.ones_like(x), x]
    weekday = np.array([d.weekday() for d in days])
    if len(days) >= 9:
        columns += [(weekday == k).astype(float) for k in sorted(set(weekday.tolist()))[1:]]
    elif len(days) >= 5 and 0 < (weekday >= 5).sum() < len(days):
        columns.append((weekday >= 5).astype(float))
    return np.column_stack(columns)


def project(days: list, p95: list, critical: float, today: date | None = None) -> dict:
    """Growth of the daily 95th percentile, and when it would reach the critical threshold.

    A least-squares line with levels for the weekly pattern (trend_design): p95 = a + b * day + the
    level of that day of the week. The days of the week carry different loads (a quiet Sunday, a
    busy hostel Saturday), and a plain line over two weeks is pulled by where they fall in the
    window: one that ends on a Sunday shows falling traffic, one that starts on a Saturday rising
    traffic (found by evaluation E9). The growth is b. The projection starts from the busiest
    level today, because that is the day the link reaches the threshold first.

    `days_until_critical` is counted from `today` (by default the last day fitted), so the
    projected date is today plus that many days. A crossing more than MAX_PROJECTION_DAYS
    ahead is left out (None), as for a flat or falling line."""
    if len(days) < 3:
        return {"growth_pts_per_week": None, "growth_pct_per_week": None, "days_until_critical": None}
    design = trend_design(days)
    y = np.array(p95, dtype=float)
    coef = np.linalg.lstsq(design, y, rcond=None)[0]
    intercept, slope = float(coef[0]), float(coef[1])
    busier = max([0.0, *(float(c) for c in coef[2:])])               # the busiest day-of-week level
    x_now = (today - days[0]).days if today is not None else float(design[-1, 1])
    fitted_now = intercept + slope * x_now + busier
    until = None
    if slope > 1e-6 and fitted_now < critical:
        until = float((critical - fitted_now) / slope)
        if until > MAX_PROJECTION_DAYS:   # a near-flat line: decades away (and past the last date Python can hold)
            until = None
    elif fitted_now >= critical:
        until = 0.0
    return {"growth_pts_per_week": round(float(slope * 7), 3),
            "growth_pct_per_week": round(float(slope * 7 / max(y.mean(), 1e-6) * 100), 2),
            "days_until_critical": None if until is None else round(until, 1),
            "fitted_p95_now": round(float(fitted_now), 2)}


def daily_p95_by_link(today: datetime) -> dict[int, tuple[list, list]]:
    """{link_id: (days, daily 95th percentiles)} over the 14 complete WAT days before `today`
    (days with less than FULL_DAY_HOURS of readings are left out). Also used by evaluation E9."""
    rows = _query(
        "SELECT link_id, (timestamp AT TIME ZONE 'Africa/Lagos')::date AS d, "
        "percentile_cont(0.95) WITHIN GROUP (ORDER BY utilisation_pct) FROM monitoring_record "
        "WHERE link_id IS NOT NULL AND timestamp >= %s AND timestamp < %s GROUP BY 1, 2 "
        "HAVING max(timestamp) - min(timestamp) >= %s ORDER BY 1, 2",
        [today - RANGES["14d"], today, timedelta(hours=FULL_DAY_HOURS)])
    by_link: dict[int, tuple[list, list]] = {}
    for link_id, day, value in rows:
        if value is not None:
            by_link.setdefault(link_id, ([], []))[0].append(day)
            by_link[link_id][1].append(float(value))
    return by_link


class CapacityView(APIView):
    """Growth and projected date of reaching the critical threshold, per link (capacity planning).

    Only complete days (West Africa Time) are fitted. Today is left out until it is over, and so
    is any day with less than 20 hours of readings (the oldest day kept, or a day the engine was
    off), because a part-day 95th percentile covers only the quiet hours, or only the busy ones."""

    def get(self, request):
        end = latest_cycle()
        if end is None:
            return Response({"links": []})
        now = end.astimezone(WAT)
        cache_key = ("capacity", now.date())
        cached = cache.get(cache_key, TREND_TTL)
        if cached is not None:
            return Response(cached)
        today = datetime(now.year, now.month, now.day, tzinfo=WAT)
        by_link = daily_p95_by_link(today)
        critical = thresholds()["critical_pct"]
        labels = link_labels()
        links = []
        for link_id, (days, p95) in by_link.items():
            projection = project(days, p95, critical, today=now.date())
            projected = None
            if projection["days_until_critical"] is not None:
                # whole days from today, rounded as the dashboard rounds "in N days", so the two agree
                ahead = math.floor(projection["days_until_critical"] + 0.5)
                projected = (now.date() + timedelta(days=ahead)).isoformat()
            links.append({"link_id": link_id, "label": labels.get(link_id, str(link_id)), "days_of_data": len(days),
                          "latest_day": days[-1].isoformat(), "latest_daily_p95_pct": round(p95[-1], 2),
                          **projection, "projected_date": projected})
        links.sort(key=lambda lk: (lk["days_until_critical"] is None, lk["days_until_critical"] or 0))
        # the period (the last 14 days) is named by the page, which always shows the same two weeks
        payload = {"thresholds": thresholds(),
                   "method": "Linear fit of the daily 95th-percentile utilisation, allowing each day of the week its "
                             "own level (complete WAT days only)",
                   "links": links}
        cache.set(cache_key, payload)
        return Response(payload)


class TrendsExportView(APIView):
    """Hourly statistics per link as CSV, for reports and capacity-planning spreadsheets."""

    def get(self, request):
        key, span = _range(request)
        end = latest_cycle()
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["hour_utc", "link_id", "link", "avg_utilisation_pct", "max_utilisation_pct"])
        if end is not None:
            labels = link_labels()
            for t, link_id, avg, peak in _query(
                    "SELECT date_trunc('hour', timestamp) AS t, link_id, avg(utilisation_pct), max(utilisation_pct) "
                    "FROM monitoring_record WHERE link_id IS NOT NULL AND timestamp > %s AND timestamp <= %s "
                    "GROUP BY 1, 2 ORDER BY 1, 2", [end - span, end]):
                writer.writerow([t.isoformat(), link_id, labels.get(link_id, ""), _r(avg), _r(peak)])
        response = HttpResponse(out.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="link-trends-{key}.csv"'
        return response


def _r(value, digits: int = 2):
    return None if value is None else round(float(value), digits)
