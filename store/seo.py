"""
What search engines and link previews (WhatsApp, Facebook, TikTok, ...) read:
page titles, descriptions, the one proper address of a page, the picture shown
in a shared link, structured data, robots.txt and the sitemap.
"""

import functools
import io
import re
from xml.sax.saxutils import escape

from django.conf import settings
from django.db.models import Count
from django.templatetags.static import static
from django.urls import reverse

from .categories import all_categories
from .models import Bag
from .templatetags.store_extras import cld_url

BRAND = "Bags & Beyond"

PHONE = "+256789000053"

SOCIAL_LINKS = [
    "https://www.tiktok.com/@bagsnbeyond256",
    "https://x.com/heisjossen",
]

HOME_TITLE = "Bags & Beyond | Handbags, Laptop Bags & Luggage in Kampala"

HOME_DESCRIPTION = (
    "Shop handbags, laptop bags, luggage, suitcases, gym and duffle bags online "
    "in Kampala, Uganda. Pay on delivery, delivered in 12\u201348 hours."
)

HOME_INTRO = (
    "Handbags, laptop bags, luggage and more. "
    "Pay on delivery, delivered in Kampala in 12\u201348 hours."
)

# One plain sentence per category: shown on the category's page, and used in
# its search-result description. Anything written in the admin (the category's
# Description box) is used instead.
CATEGORY_BLURBS = {
    "Briefcases": "Briefcases for the office, meetings and business travel.",
    "Camera Bags": "Camera bags to carry your camera, lenses and accessories.",
    "Crossbody Bags": "Crossbody bags that keep your hands free, for everyday and travel.",
    "Duffle Bags": "Roomy duffle bags for the gym, weekends away and travel.",
    "Gym Bags": "Gym bags for training, sports and the gym.",
    "Handbags": "Handbags for everyday, work and special occasions.",
    "Kids Bags": "Kids bags for school, play and trips.",
    "Laptop Bags": "Laptop bags to carry your laptop to work, school and on the move.",
    "Luggage Bags": "Luggage bags for trips near and far.",
    "Lunchbox Bags": "Lunchbox bags for school and work lunches.",
    "Marathon Kit Bags": "Marathon kit bags for race day and training.",
    "Suit Carriers": "Suit carriers to carry suits and formal wear when you travel.",
    "Suitcase Sets": "Suitcase sets in matching sizes for family trips and travel.",
    "Suitcase Single": "Single suitcases for your next trip.",
    "Tote Bags": "Tote bags for shopping, work and every day.",
}

SHOP_LINE = "Shop online in Kampala, Uganda: pay on delivery, delivered in 12\u201348 hours."


# ---------------------------------------------------------------- addresses

def site_base(request):
    """https://bagsnbeyond.com : the address the world should use for the shop."""

    return settings.SITE_URL or f"{request.scheme}://{request.get_host()}"


def absolute(request, path):
    return site_base(request) + path


def social_image(request):
    return absolute(request, reverse("social_card"))


def full_picture(request, url):
    """A picture's address as a full https://... address."""

    return absolute(request, url) if str(url).startswith("/") else url


def clip(text, limit=155):
    """Plain text on one line, cut at a word, for a description."""

    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()

    if len(text) <= limit:
        return text

    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(".,;:- ") + "\u2026"


def category_intro(category):
    return (
        (category.description or "").strip()
        or CATEGORY_BLURBS.get(category.name)
        or f"{category.name} from {BRAND}."
    )


def _category_named(name):
    name = (name or "").strip().lower()

    for category in all_categories():
        if category.name.lower() == name:
            return category

    return None


# ---------------------------------------------------------------- structured data

def organization(request):
    base = site_base(request)

    return {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": BRAND,
        "url": base + "/",
        "logo": base + static("store/images/bag-store-logo.png"),
        "sameAs": SOCIAL_LINKS,
        "contactPoint": {
            "@type": "ContactPoint",
            "telephone": PHONE,
            "contactType": "customer service",
            "areaServed": "UG",
            "availableLanguage": "English",
        },
    }


def website(request):
    base = site_base(request)

    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": BRAND,
        "url": base + "/",
        "potentialAction": {
            "@type": "SearchAction",
            "target": {"@type": "EntryPoint", "urlTemplate": base + "/?q={search_term_string}"},
            "query-input": "required name=search_term_string",
        },
    }


def breadcrumb_list(request, trail):
    """trail: [(name, path), ...] from the front page to the page itself."""

    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": position,
                "name": name,
                "item": absolute(request, path),
            }
            for position, (name, path) in enumerate(trail, start=1)
        ],
    }


# ---------------------------------------------------------------- the pages

def _page(request, *, title, description, canonical, robots="index, follow, max-image-preview:large",
          image=None, og_type="website", extra_meta=(), jsonld=(), intro="", trail=()):
    return {
        "title": title,
        "description": description,
        "canonical": canonical,
        "robots": robots,
        "image": image or social_image(request),
        "og_type": og_type,
        "extra_meta": list(extra_meta),
        "jsonld": list(jsonld),
        "intro": intro,
        "trail": list(trail),
    }


NOINDEX = "noindex, follow"


def listing_seo(request, *, filters, page, category, landing, is_curated, result_count):
    """
    The shop page in all its forms: the front page, a category page, search
    results, and pages that are only a different view of the same bags.

    Only the front page and the category pages are for search engines. Search
    results, sorted/filtered lists and the "all bags" pages 2, 3, ... point back
    to the page they come from and ask not to be listed.
    """

    base = site_base(request)

    number = page.number

    searching = bool(filters["query"])

    changed = bool(
        searching or filters["sort"] or filters["in_stock"]
        or filters["min_price"] or filters["max_price"]
    )

    category = category or _category_named(filters["category"])

    if searching:
        return _page(
            request,
            title=f"Search results for \u201c{filters['query']}\u201d | {BRAND}",
            description=HOME_DESCRIPTION,
            canonical=base + "/",
            robots=NOINDEX,
        )

    if category is not None:

        address = base + category.get_absolute_url()

        listed = landing and not changed and result_count > 0

        title = (
            f"{category.name}, Page {number} | {BRAND}" if number > 1
            else f"{category.name} in Kampala, Uganda | {BRAND}"
        )

        described = (category.description or "").strip()

        return _page(
            request,
            title=title,
            description=clip(
                described if described
                else f"{category_intro(category)} {SHOP_LINE}"
            ),
            canonical=address + (f"?page={number}" if number > 1 and listed else ""),
            robots="index, follow, max-image-preview:large" if listed else NOINDEX,
            intro=category_intro(category) if number == 1 else "",
            jsonld=[breadcrumb_list(request, [("Home", "/"), (category.name, category.get_absolute_url())])],
            trail=[("Home", reverse("index")), (category.name, "")],
        )

    if changed or filters["category"]:
        return _page(
            request,
            title=f"All Bags | {BRAND}",
            description=HOME_DESCRIPTION,
            canonical=base + "/",
            robots=NOINDEX,
        )

    if number > 1:
        return _page(
            request,
            title=f"All Bags, Page {number} | {BRAND}",
            description=HOME_DESCRIPTION,
            canonical=f"{base}/?page={number}",
            robots=NOINDEX,
        )

    return _page(
        request,
        title=HOME_TITLE,
        description=HOME_DESCRIPTION,
        canonical=base + "/",
        intro=HOME_INTRO,
        jsonld=[organization(request), website(request)],
    )


def product_seo(request, bag):
    """A bag's page: title, description, picture, price and stock for search engines."""

    images = list(bag.images.all())

    address = absolute(request, bag.get_absolute_url())

    description = clip(bag.description) or (
        f"{bag.name} ({bag.category.name}) for UGX {bag.price:,.0f}. {SHOP_LINE}"
    )

    pictures = [
        full_picture(request, cld_url(image.image.url, "f_jpg,q_auto,w_1200,c_limit"))
        for image in images[:5]
    ]

    in_stock = bag.stock > 0

    price = f"{bag.price:.0f}" if bag.price == bag.price.to_integral_value() else f"{bag.price:.2f}"

    product = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": bag.name,
        "description": description,
        "sku": str(bag.id),
        "category": bag.category.name,
        "url": address,
        "offers": {
            "@type": "Offer",
            "url": address,
            "priceCurrency": "UGX",
            "price": price,
            "availability": "https://schema.org/InStock" if in_stock else "https://schema.org/OutOfStock",
            "itemCondition": "https://schema.org/NewCondition",
            "seller": {"@type": "Organization", "name": BRAND},
        },
    }

    if pictures:
        product["image"] = pictures

    name = bag.name if len(bag.name) <= 40 else bag.name[:39].rstrip() + "\u2026"

    return _page(
        request,
        title=f"{name} \u2013 {bag.category.name} | {BRAND}",
        description=description,
        canonical=address,
        image=full_picture(
            request,
            cld_url(images[0].image.url, "f_jpg,q_auto,w_1200,h_630,c_pad,b_rgb:f2f1ed"),
        ) if images else None,
        og_type="product",
        extra_meta=[
            ("product:price:amount", price),
            ("product:price:currency", "UGX"),
            ("product:availability", "in stock" if in_stock else "out of stock"),
        ],
        jsonld=[
            product,
            breadcrumb_list(request, [
                ("Home", "/"),
                (bag.category.name, bag.category.get_absolute_url()),
                (bag.name, bag.get_absolute_url()),
            ]),
        ],
        trail=[
            ("Home", reverse("index")),
            (bag.category.name, bag.category.get_absolute_url()),
            (bag.name, ""),
        ],
    )


def simple_seo(request, *, title, description, path):
    return _page(request, title=title, description=description, canonical=absolute(request, path))


# ---------------------------------------------------------------- robots.txt and the sitemap

PRIVATE = ("/admin/", "/cart/", "/checkout/", "/accounts/", "/login/", "/order/", "/orders/", "/v/", "/healthz/")


def robots_text(request):
    lines = ["User-agent: *", "Allow: /"]
    lines += [f"Disallow: {path}" for path in PRIVATE]
    lines += ["", f"Sitemap: {absolute(request, reverse('sitemap'))}", ""]

    return "\n".join(lines)


def sitemap_xml(request):
    """Every page worth listing: the front page, the categories that have bags, every bag."""

    used = set(Bag.objects.values_list("category_id", flat=True).distinct())

    pages = [("/", [])]
    pages += [(category.get_absolute_url(), []) for category in all_categories() if category.id in used]
    pages += [("/privacy/", [])]

    for bag in Bag.objects.select_related("category").prefetch_related("images").order_by("id"):
        pages.append((
            bag.get_absolute_url(),
            [
                full_picture(request, cld_url(i.image.url, "f_jpg,q_auto,w_1200,c_limit"))
                for i in list(bag.images.all())[:5]
            ],
        ))

    base = site_base(request)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">',
    ]

    for path, pictures in pages:
        entry = f"<url><loc>{escape(base + path)}</loc>"
        entry += "".join(
            f"<image:image><image:loc>{escape(picture)}</image:loc></image:image>"
            for picture in pictures
        )
        lines.append(entry + "</url>")

    lines.append("</urlset>")

    return "\n".join(lines)


# ---------------------------------------------------------------- the picture shown in a shared link

@functools.lru_cache(maxsize=1)
def social_card_png():
    """
    1200 x 630, the logo on the shop's cream background: the picture WhatsApp,
    Facebook and others show when the front page is shared. Made once from the
    logo, so there is no extra picture file to look after.
    """

    from PIL import Image

    from .views import ICON_FOLDER

    card = Image.new("RGBA", (1200, 630), (242, 241, 237, 255))

    logo = Image.open(ICON_FOLDER / "bag-store-logo.png").convert("RGBA")

    width = 940

    logo = logo.resize((width, round(logo.height * width / logo.width)), Image.Resampling.LANCZOS)

    card.alpha_composite(logo, ((1200 - logo.width) // 2, (630 - logo.height) // 2))

    out = io.BytesIO()

    card.convert("RGB").save(out, format="PNG", optimize=True)

    return out.getvalue()
