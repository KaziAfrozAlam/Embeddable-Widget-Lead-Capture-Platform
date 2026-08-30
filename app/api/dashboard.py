"""Owner dashboard API: submissions list + aggregate stats.

Backend capstone, so simple JSON aggregates suffice: totals, a daily series,
per-widget counts, and a geo (country) breakdown.
"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_owner
from ..models import Owner, Submission, Widget
from ..schemas import StatsOut, SubmissionList, SubmissionOut

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _local_buckets(now_local: datetime) -> tuple[datetime, list[str]]:
    """Resolve a day boundary + 30-day skeleton in the given timezone.

    Submissions are stored in naive UTC; "today" and the daily series must be
    bucketed by the dashboard reader's *local* day, or the counts drift for
    every timezone that isn't UTC (e.g. a 05:30 UTC+5:30 lead is still "today").

    Returns (start-of-local-day-as-naive-UTC, [30 ascending YYYY-MM-DD keys]).
    """
    tz = now_local.tzinfo or timezone.utc
    midnight_local = datetime(now_local.year, now_local.month, now_local.day, tzinfo=tz)
    today_start_utc = midnight_local.astimezone(timezone.utc).replace(tzinfo=None)
    skeleton = [
        (midnight_local - timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(29, -1, -1)
    ]
    return today_start_utc, skeleton


def _local_date(created_utc: datetime, now_local: datetime) -> str:
    tz = now_local.tzinfo or timezone.utc
    return created_utc.replace(tzinfo=timezone.utc).astimezone(tz).strftime("%Y-%m-%d")


@router.get("/submissions", response_model=SubmissionList)
def list_submissions(
    widget_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    owner: Owner = Depends(get_current_owner),
    db: Session = Depends(get_db),
) -> SubmissionList:
    stmt = select(Submission).where(Submission.owner_id == owner.id)
    if widget_id:
        widget = db.scalar(
            select(Widget).where(Widget.id == widget_id, Widget.owner_id == owner.id)
        )
        if widget is None:
            raise HTTPException(status_code=404, detail="widget not found")
        stmt = stmt.where(Submission.widget_id == widget_id)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Submission.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return SubmissionList(
        total=total,
        page=page,
        page_size=page_size,
        items=[SubmissionOut.model_validate(r) for r in rows],
    )


@router.get("/stats", response_model=StatsOut)
def stats(
    owner: Owner = Depends(get_current_owner),
    db: Session = Depends(get_db),
) -> StatsOut:
    rows = db.scalars(
        select(Submission).where(Submission.owner_id == owner.id)
    ).all()

    now_local = datetime.now().astimezone()
    today_start_utc, daily_keys = _local_buckets(now_local)
    daily = defaultdict(int, {k: 0 for k in daily_keys})
    week_ago = today_start_utc - timedelta(days=7)

    by_widget = Counter()
    by_country = Counter()
    today = 0
    last_7 = 0
    for r in rows:
        by_widget[r.widget_id] += 1
        if r.geo_country:
            by_country[r.geo_country] += 1
        if r.created_at >= today_start_utc:
            today += 1
        if r.created_at >= week_ago:
            last_7 += 1
        day_key = _local_date(r.created_at, now_local)
        if day_key in daily:
            daily[day_key] += 1

    widget_ids = list(by_widget)
    titles = {}
    if widget_ids:
        for w in db.scalars(select(Widget).where(Widget.id.in_(widget_ids))):
            titles[w.id] = w.title

    return StatsOut(
        total=len(rows),
        today=today,
        last_7_days=last_7,
        daily=[{"date": d, "count": c} for d, c in sorted(daily.items())],
        by_widget=[
            {"widget_id": wid, "title": titles.get(wid, "?"), "count": c}
            for wid, c in by_widget.most_common()
        ],
        by_country=[
            {"country": country, "count": c}
            for country, c in by_country.most_common()
        ],
    )