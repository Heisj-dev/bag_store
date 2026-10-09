"""
Visitor statistics, kept by the shop itself.

Nothing here identifies a person. There is no cookie, no name and no IP
address in the database: a visitor is a scrambled code made from the day, the
IP address and the browser, and it changes every day. So the same person on
two days looks like two visitors, and nobody can be followed from day to day.
"""

import hashlib
import hmac
import random
import re
from datetime import datetime, time, timedelta
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache
from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from .models import Bag, Order, OrderItem, VisitEvent


# Paths that are never counted: the admin, the health check, files and the like.
NOT_COUNTED = (
    "/admin", "/healthz", "/v/", "/static/", "/media/", "/favicon",
    "/apple-touch-icon", "/robots.txt", "/sitemap", "/social-card", "/logo",
)

# Browsers that are really programs: search engines, link previews, monitors.
BOT_WORDS = (
    "bot", "crawl", "spider", "slurp", "facebookexternalhit", "whatsapp",
    "preview", "lighthouse", "pingdom", "uptime", "monitor", "headless",
    "curl", "wget", "python-requests", "httpclient", "go-http", "scrapy",
)

HITS_PER_MINUTE = 60            # more than this from one visitor is not a person
KEEP_DAYS = 400                 # older events are deleted


# ---------------------------------------------------------------- who is this?

def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")

    if forwarded:
        return forwarded.split(",")[0].strip()

    return request.META.get("REMOTE_ADDR", "")


def visitor_code(request, when=None):
    """A scrambled code for this visitor on this day. Not the IP address."""

    when = timezone.localtime(when or timezone.now())

    seed = "|".join((
        when.date().isoformat(),
        client_ip(request),
        request.META.get("HTTP_USER_AGENT", ""),
    ))

    return hmac.new(
        settings.SECRET_KEY.encode(), seed.encode(), hashlib.sha256
    ).hexdigest()[:16]


def describe_agent(agent):
    """
    (device, system, browser) for a visitor's browser, or None when it is a
    program (a search engine, a link preview, a monitor) and not a person.
    """

    agent = (agent or "").strip()

    if not agent:
        return None

    lower = agent.lower()

    if any(word in lower for word in BOT_WORDS):
        return None

    if "ipad" in lower or ("android" in lower and "mobile" not in lower):
        device = "tablet"
    elif "mobi" in lower or "iphone" in lower or "android" in lower:
        device = "mobile"
    else:
        device = "desktop"

    if "iphone" in lower or "ipad" in lower or "ipod" in lower:
        system = "iOS"
    elif "android" in lower:
        system = "Android"
    elif "windows" in lower:
        system = "Windows"
    elif "macintosh" in lower or "mac os x" in lower:
        system = "macOS"
    elif "cros" in lower:
        system = "ChromeOS"
    elif "linux" in lower:
        system = "Linux"
    else:
        system = "Other"

    # In-app browsers first: a link opened inside TikTok or Instagram.
    if "tiktok" in lower or "musical_ly" in lower or "bytedance" in lower:
        browser = "TikTok app"
    elif "instagram" in lower:
        browser = "Instagram app"
    elif "fban" in lower or "fbav" in lower:
        browser = "Facebook app"
    elif "ucbrowser" in lower or "ucweb" in lower:
        browser = "UC Browser"
    elif "opera mini" in lower or "opr/" in lower or "opera" in lower:
        browser = "Opera"
    elif "samsungbrowser" in lower:
        browser = "Samsung Internet"
    elif "edg/" in lower or "edga/" in lower or "edgios" in lower:
        browser = "Edge"
    elif "firefox" in lower or "fxios" in lower:
        browser = "Firefox"
    elif "chrome" in lower or "crios" in lower:
        browser = "Chrome"
    elif "safari" in lower:
        browser = "Safari"
    else:
        browser = "Other"

    return device, system, browser


SOURCES = (
    ("google.", "Google"),
    ("bing.", "Bing"),
    ("duckduckgo.", "DuckDuckGo"),
    ("yahoo.", "Yahoo"),
    ("facebook.", "Facebook"),
    ("fb.com", "Facebook"),
    ("instagram.", "Instagram"),
    ("tiktok.", "TikTok"),
    ("t.co", "X (Twitter)"),
    ("twitter.", "X (Twitter)"),
    ("x.com", "X (Twitter)"),
    ("whatsapp.", "WhatsApp"),
    ("wa.me", "WhatsApp"),
    ("youtube.", "YouTube"),
    ("pinterest.", "Pinterest"),
    ("linkedin.", "LinkedIn"),
    ("t.me", "Telegram"),
)


def traffic_source(referrer, tag, own_host):
    """
    Where a visit came from: a tagged link (?utm_source=whatsapp), the website
    the visitor was on, "Direct" (typed in, or a link from an app that does not
    say where it was), or "" when they are just moving around this shop.
    """

    tag = (tag or "").strip().lower()[:40]

    if tag:
        for needle, name in SOURCES:
            if needle.strip(".") in tag:
                return name

        return tag.title()

    host = (urlparse(referrer or "").hostname or "").lower()

    if host.startswith("www."):
        host = host[4:]

    if not host:
        return "Direct"

    own = (own_host or "").split(":")[0].lower()

    if own.startswith("www."):
        own = own[4:]

    if host == own or host.endswith("." + own):
        return ""

    for needle, name in SOURCES:
        if needle in host:
            return name

    return host[:60]


def tidy_path(path):
    """
    The page, without anything private: no order numbers, no password-reset
    keys, no search text. Only the shop's own pages keep their full address.
    """

    path = (path or "")[:200]

    if not path.startswith("/"):
        return ""

    if path == "/" or re.match(r"^/(category|bag)/[\w\-/]*$", path):
        return path

    if path in ("/cart/", "/checkout/", "/privacy/"):
        return path

    return "/" + path.strip("/").split("/")[0] + "/"


# ---------------------------------------------------------------- recording

def _allowed(request):
    """Is this request from a real visitor we should count?"""

    user = getattr(request, "user", None)

    if user is not None and user.is_authenticated and user.is_staff:
        return False                         # the owner looking at their own shop

    return describe_agent(request.META.get("HTTP_USER_AGENT")) is not None


def _too_fast(code):
    key = f"visits:{code}:{timezone.now():%Y%m%d%H%M}"

    seen = cache.get(key, 0)

    if seen >= HITS_PER_MINUTE:
        return True

    cache.set(key, seen + 1, 120)

    return False


def _prune_sometimes():
    """No scheduled job on a free host: once in a while, clear out old events."""

    if random.random() < 0.001:
        old = timezone.localdate() - timedelta(days=KEEP_DAYS)
        VisitEvent.objects.filter(day__lt=old).delete()


def _save(request, kind, **fields):

    now = timezone.localtime(timezone.now())

    code = visitor_code(request, now)

    if _too_fast(code):
        return False

    device, system, browser = describe_agent(request.META.get("HTTP_USER_AGENT"))

    VisitEvent.objects.create(
        day=now.date(),
        hour=now.hour,
        visitor=code,
        kind=kind,
        device=device,
        os=system,
        browser=browser,
        **fields,
    )

    _prune_sometimes()

    return True


def _number(value, high):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None

    return value if 0 <= value <= high else None


def record_page_view(request, data):
    """One page view, reported by the small script every page carries."""

    if not isinstance(data, dict) or not _allowed(request):
        return False

    path = str(data.get("path", ""))[:200]

    if not path.startswith("/") or path.startswith(NOT_COUNTED):
        return False

    return _save(
        request,
        VisitEvent.PAGE,
        path=tidy_path(path),
        bag_id=_number(data.get("bag"), 2_000_000_000),
        category=str(data.get("category", ""))[:100],
        term=str(data.get("term", "")).strip().lower()[:80],
        results=_number(data.get("results"), 100_000),
        source=traffic_source(
            str(data.get("ref", ""))[:300],
            str(data.get("src", "")),
            request.get_host(),
        ),
    )


def record_cart_add(request, bag):
    """A bag was added to the cart."""

    if not _allowed(request):
        return False

    return _save(request, VisitEvent.CART, bag_id=bag.id, path="/cart/")


# ---------------------------------------------------------------- the dashboard

RANGES = ((1, "Today"), (7, "7 days"), (30, "30 days"), (90, "90 days"), (0, "All time"))

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _percent(part, whole):
    return round(100 * part / whole) if whole else 0


def _bars(rows, value):
    """Give each row a bar width in percent of the biggest value."""

    top = max((value(row) for row in rows), default=0)

    for row in rows:
        row["bar"] = _percent(value(row), top)

    return rows


def build_dashboard(days):
    """Everything the admin's Visitor analytics page shows, for `days` days (0 = all)."""

    today = timezone.localdate()

    start = today - timedelta(days=days - 1) if days else None

    events = VisitEvent.objects.all()

    orders = Order.objects.exclude(status="CANCELLED")

    sold_items = OrderItem.objects.exclude(order__status="CANCELLED")

    if start:
        start_time = timezone.make_aware(datetime.combine(start, time.min))
        events = events.filter(day__gte=start)
        orders = orders.filter(created_at__gte=start_time)
        sold_items = sold_items.filter(order__created_at__gte=start_time)

    pages = events.filter(kind=VisitEvent.PAGE)
    carts = events.filter(kind=VisitEvent.CART)

    def people(queryset):
        return queryset.values("visitor").distinct().count()

    visitors = people(pages)

    page_views = pages.count()

    bag_viewers = people(pages.filter(bag_id__isnull=False))

    cart_adders = people(carts)

    checkout_visitors = people(pages.filter(path="/checkout/"))

    order_totals = orders.aggregate(count=Count("id"), money=Sum("total"))

    ordered = order_totals["count"] or 0

    # ---- one bar per day
    first_day = start or (
        pages.order_by("day").values_list("day", flat=True).first() or today
    )

    first_day = max(first_day, today - timedelta(days=59))        # chart: last 60 days at most

    per_day = {
        row["day"]: row
        for row in pages.filter(day__gte=first_day).values("day").annotate(
            views=Count("id"), visitors=Count("visitor", distinct=True)
        )
    }

    daily = []

    day = first_day

    while day <= today:
        row = per_day.get(day, {})
        daily.append({
            "day": day,
            "label": day.strftime("%a %d %b"),
            "visitors": row.get("visitors", 0),
            "views": row.get("views", 0),
        })
        day += timedelta(days=1)

    _bars(daily, lambda row: row["visitors"])

    weekday_totals = [0] * 7

    for row in daily:
        weekday_totals[row["day"].weekday()] += row["visitors"]

    weekdays = _bars(
        [{"label": WEEKDAYS[i], "visitors": weekday_totals[i]} for i in range(7)],
        lambda row: row["visitors"],
    )

    # ---- busiest hours (Kampala time)
    per_hour = {
        row["hour"]: row["views"]
        for row in pages.values("hour").annotate(views=Count("id"))
    }

    hours = _bars(
        [{"label": f"{hour:02d}", "views": per_hour.get(hour, 0)} for hour in range(24)],
        lambda row: row["views"],
    )

    # ---- the bags: looked at, added to cart, bought
    looked_at = {
        row["bag_id"]: row
        for row in pages.filter(bag_id__isnull=False).values("bag_id").annotate(
            views=Count("id"), people=Count("visitor", distinct=True)
        )
    }

    added = {
        row["bag_id"]: row["adds"]
        for row in carts.filter(bag_id__isnull=False).values("bag_id").annotate(
            adds=Count("id")
        )
    }

    bought = {
        row["bag_id"]: row["units"]
        for row in sold_items.filter(bag_id__isnull=False).values("bag_id").annotate(
            units=Sum("quantity")
        )
    }

    known = Bag.objects.select_related("category").in_bulk(
        set(looked_at) | set(added) | set(bought)
    )

    bags = []

    for bag_id in set(looked_at) | set(added) | set(bought):
        views = looked_at.get(bag_id, {}).get("views", 0)
        bag = known.get(bag_id)
        bags.append({
            "name": bag.name if bag else f"(deleted bag #{bag_id})",
            "category": bag.category.name if bag else "",
            "views": views,
            "people": looked_at.get(bag_id, {}).get("people", 0),
            "adds": added.get(bag_id, 0),
            "bought": bought.get(bag_id, 0),
            "rate": _percent(added.get(bag_id, 0), views),
        })

    bags.sort(key=lambda row: (-row["views"], -row["adds"], row["name"]))

    top_bags = _bars(bags[:15], lambda row: row["views"])

    # ---- categories people open, what they search for, where they come from
    categories = _bars(
        list(
            pages.exclude(category="").values("category")
            .annotate(views=Count("id")).order_by("-views")[:10]
        ),
        lambda row: row["views"],
    )

    searches = list(
        pages.exclude(term="").values("term")
        .annotate(times=Count("id"), found=Avg("results"), nothing=Count("id", filter=Q(results=0)))
        .order_by("-times", "term")[:10]
    )

    for row in searches:
        row["found"] = round(row["found"]) if row["found"] is not None else None

    _bars(searches, lambda row: row["times"])

    def split(field):
        return _bars(
            list(
                pages.exclude(**{field: ""}).values(field)
                .annotate(people=Count("visitor", distinct=True)).order_by("-people")[:10]
            ),
            lambda row: row["people"],
        )

    sources = split("source")
    devices = split("device")
    systems = split("os")
    browsers = split("browser")

    for group in (sources, devices, systems, browsers):
        for row in group:
            row["percent"] = _percent(row["people"], visitors)

    top_pages = _bars(
        list(
            pages.filter(bag_id__isnull=True).exclude(path="").values("path")
            .annotate(views=Count("id"), people=Count("visitor", distinct=True))
            .order_by("-views")[:8]
        ),
        lambda row: row["views"],
    )

    funnel = [
        {"label": "Visited the shop", "people": visitors},
        {"label": "Looked at a bag", "people": bag_viewers},
        {"label": "Added a bag to the cart", "people": cart_adders},
        {"label": "Reached the checkout", "people": checkout_visitors},
        {"label": "Placed an order", "people": ordered},
    ]

    for row in funnel:
        row["percent"] = _percent(row["people"], visitors)

    return {
        "days": days,
        "ranges": [{"days": d, "label": label, "current": d == days} for d, label in RANGES],
        "visitors": visitors,
        "page_views": page_views,
        "bag_views": pages.filter(bag_id__isnull=False).count(),
        "cart_adds": carts.count(),
        "orders": ordered,
        "revenue": order_totals["money"] or 0,
        "conversion": round(100 * ordered / visitors, 1) if visitors else 0,
        "has_data": bool(page_views or carts.exists()),
        "daily": daily,
        "weekdays": weekdays,
        "hours": hours,
        "top_bags": top_bags,
        "categories": categories,
        "searches": searches,
        "sources": sources,
        "devices": devices,
        "systems": systems,
        "browsers": browsers,
        "top_pages": top_pages,
        "funnel": funnel,
    }
