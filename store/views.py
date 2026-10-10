import functools
import io
import json
import logging
import uuid
import hashlib
from django.core.cache import cache
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.models import User
from django.contrib.auth import login, authenticate
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import PasswordResetForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, prefetch_related_objects
from django.core.paginator import Paginator
from django.core.validators import validate_email
from django.core.mail import send_mail
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import cache_control, never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_safe

from allauth.socialaccount.adapter import get_adapter as get_social_adapter

from .models import HOMEPAGE_BAG_LIMIT, Bag, Category, Order, OrderItem
from .templatetags.store_extras import cld, ugx_format
from . import analytics, seo
from .cart import Cart
from .categories import all_categories
from .delivery import (
    SUGGEST_MIN_CHARS,
    calculate_delivery,
    calculate_delivery_for_place,
    clear_quote,
    customer_message,
    load_quote,
    save_quote,
    suggest_places,
    verify_place_token,
)
from .emails import order_totals_text, send_order_received_email

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Browsing the catalog: the homepage is Page 1 of the catalogue
# ---------------------------------------------------------------------------

# Bags per page on Page 2, 3, ... of the plain homepage and on every page of
# search / filter / sort results. Page 1 of the plain homepage is the picked
# bags instead: at most HOMEPAGE_BAG_LIMIT (12, set in models.py).
CATALOGUE_PAGE_SIZE = 16

# ?sort=... -> database ordering. Every ordering ends with a unique column, so
# a bag can never repeat or go missing between two pages.
SORT_ORDERINGS = {
    "price_asc": ("price", "id"),
    "price_desc": ("-price", "id"),
    "newest": ("-id",),
    "name_asc": ("name", "id"),
}

DEFAULT_ORDERING = ("-created_at", "-id")


def _clean_price(raw):
    """The price text if it is a valid, non-negative number, otherwise ""."""

    raw = (raw or "").strip()

    if not raw:
        return ""

    try:
        value = Decimal(raw)
    except InvalidOperation:
        return ""

    if not value.is_finite() or value < 0:
        return ""

    return raw


def _read_filters(request):
    """
    The browsing options in the address bar (search, category, stock, price,
    sort), cleaned up. An empty or invalid option counts as "not used".
    """

    get = request.GET

    sort = get.get("sort", "").strip()

    return {
        "query": get.get("q", "").strip(),
        "category": get.get("category", "").strip(),
        "in_stock": get.get("in_stock", "").strip(),
        "min_price": _clean_price(get.get("min_price")),
        "max_price": _clean_price(get.get("max_price")),
        "sort": sort if sort in SORT_ORDERINGS else "",
    }


def _filters_in_use(filters):
    """True as soon as the customer has used any search / filter / sort."""
    return any(filters.values())


def _all_bags():
    return Bag.objects.select_related("category").prefetch_related("images")


def _filter_and_sort(bags, filters):
    """Apply the customer's filters and sort to a set of bags."""

    if filters["category"]:
        bags = bags.filter(category__name__iexact=filters["category"])

    if filters["query"]:
        bags = bags.filter(
            Q(name__icontains=filters["query"]) |
            Q(description__icontains=filters["query"])
        )

    if filters["in_stock"]:
        bags = bags.filter(stock__gt=0)

    if filters["min_price"]:
        bags = bags.filter(price__gte=Decimal(filters["min_price"]))

    if filters["max_price"]:
        bags = bags.filter(price__lte=Decimal(filters["max_price"]))

    return bags.order_by(
        *SORT_ORDERINGS.get(filters["sort"], DEFAULT_ORDERING)
    )


def _filter_context(filters):
    """The filter values the templates show back to the customer."""

    return {
        "query": filters["query"],
        "category_slug": filters["category"],
        "sort": filters["sort"],
        "in_stock_only": filters["in_stock"],
        "min_price": filters["min_price"],
        "max_price": filters["max_price"],
    }


def _picked_bags():
    """
    Page 1 of the catalogue: the bags picked in the admin (show_on_homepage),
    in homepage_order, at most HOMEPAGE_BAG_LIMIT. If fewer are picked, it is
    just those: Page 1 is never topped up with other bags.
    """

    return list(
        Bag.objects
        .filter(show_on_homepage=True)
        .select_related("category")
        .order_by("homepage_order", "-created_at", "id")
        [:HOMEPAGE_BAG_LIMIT]
    )


def _page_numbers(paginator, page):
    """The numbers for the page bar: 1 ... 15 16 17 ... 32."""

    return paginator.get_elided_page_range(
        page.number, on_each_side=1, on_ends=1
    )


def _results_page(page_number, filters):
    """
    Search / filter / sort: EVERY matching bag (featured ones too, so a search
    can always find a bag), CATALOGUE_PAGE_SIZE per page.
    """

    paginator = Paginator(
        _filter_and_sort(_all_bags(), filters),
        CATALOGUE_PAGE_SIZE,
    )

    page = paginator.get_page(page_number)

    return {
        "bags": page,
        "page_obj": page,
        "result_count": paginator.count,
        "page_numbers": _page_numbers(paginator, page),
        "is_curated": False,
    }


def _catalogue_page(page_number):
    """
    The plain homepage: Page 1 of the whole catalogue.

    Page 1      the picked bags (see _picked_bags).
    Page 2, 3.. every bag that is NOT on Page 1, newest first,
                CATALOGUE_PAGE_SIZE per page.

    Only the ids really shown on Page 1 are left out of the later pages, so a
    bag picked beyond the 12 limit still turns up on a later page, and no bag
    is skipped or repeated. Nothing loads the whole catalogue: a later page
    costs one COUNT(*) plus one LIMIT/OFFSET query.
    """

    picked = _picked_bags()

    later = Paginator(
        _all_bags()
        .exclude(id__in=[bag.id for bag in picked])
        .order_by(*DEFAULT_ORDERING),
        CATALOGUE_PAGE_SIZE,
        allow_empty_first_page=False,
    )

    # The page links: one for Page 1, then one for every page of `later`.
    links = Paginator(range(1 + later.num_pages), 1)

    page = links.get_page(page_number)

    if page.number == 1:
        prefetch_related_objects(picked, "images")    # the photos, one query
        bags = picked
    else:
        bags = later.page(page.number - 1)

    return {
        "bags": bags,
        "page_obj": page,
        "result_count": len(picked) + later.count,
        "page_numbers": _page_numbers(links, page),
        "is_curated": page.number == 1,
    }


def _category_for_slug(slug):

    for category in all_categories():
        if category.slug == slug:
            return category

    raise Http404("No such category.")


def category_page(request, slug):
    """/category/gym-bags/ : the shop page of one category."""

    return index(request, category=_category_for_slug(slug))


def index(request, category=None):
    """
    The homepage, which is Page 1 of a paginated catalogue.

    Plain homepage: Page 1 shows the bags picked in the admin, and /?page=2,
    /?page=3, ... list every other bag (see _catalogue_page).

    Browsing: as soon as the customer uses search, a category, the stock or
    price filters or a sort, every matching bag is listed, CATALOGUE_PAGE_SIZE
    per page (see _results_page).

    The page bar (Prev | 1 | 2 | 3 | ... | Next) shows when there is more than
    one page.
    """

    filters = _read_filters(request)

    if category is not None:
        filters["category"] = category.name

    page_number = request.GET.get("page")

    if _filters_in_use(filters):
        shown = _results_page(page_number, filters)
    else:
        shown = _catalogue_page(page_number)

    # What the small script reports about this page (see base.html): a search,
    # and how many bags it found; or a category.
    visit = {}

    if filters["query"]:
        visit["term"] = filters["query"]
        visit["results"] = shown["result_count"]

    if filters["category"]:
        visit["category"] = filters["category"]

    # The address-bar options without "page", so every page link keeps the
    # search, category, stock, price and sort the customer chose.
    params = request.GET.copy()
    params.pop("page", None)

    seo_data = seo.listing_seo(
        request,
        filters=filters,
        page=shown["page_obj"],
        category=category,
        landing=category is not None,
        is_curated=shown["is_curated"],
        result_count=shown["result_count"],
    )

    return render(
        request,
        "store/index.html",
        {
            **shown,
            "seo": seo_data,
            "querystring": params.urlencode(),
            "categories": all_categories(),
            "landing_category": category,
            "visit": visit,
            **_filter_context(filters),
        }
    )


def collection(request):
    """
    The old /collection/ address. The whole catalogue now lives on the
    homepage, so send customers (and old bookmarks) there, keeping whatever
    search, category, stock, price, sort or page is in the address.
    """

    target = reverse("index")

    query = request.META.get("QUERY_STRING", "")

    return redirect(f"{target}?{query}" if query else target)


ORDER_STATUS_SEQUENCE = ["PENDING", "CONFIRMED", "PROCESSING", "SHIPPED", "DELIVERED"]

ORDER_TRACKER_STEPS = [
    ("CONFIRMED", "WE CONFIRM YOUR ORDER"),
    ("PROCESSING", "WE PREPARE YOUR BAG"),
    ("SHIPPED", "RIDER IS ON THE WAY"),
    ("DELIVERED", "ORDER DELIVERED"),
]


def build_order_tracker(status):
    if status not in ORDER_STATUS_SEQUENCE:
        return None

    current_index = ORDER_STATUS_SEQUENCE.index(status)
    last_step_index = len(ORDER_TRACKER_STEPS) - 1
    steps = []

    for i, (key, label) in enumerate(ORDER_TRACKER_STEPS):
        target_index = i + 1

        if current_index > target_index:
            state = "done"
        elif current_index == target_index:
            state = "done" if i == last_step_index else "current"
        elif current_index == 0 and i == 0:
            state = "current"
        else:
            state = "upcoming"

        steps.append({
            "key": key,
            "label": label,
            "state": state,
        })

    return steps


def product_detail(request, bag_id, slug=None):

    bag = get_object_or_404(
        Bag.objects.select_related("category").prefetch_related("images"),
        id=bag_id,
    )

    # A bag has one proper address, /bag/12/zara-tote/. The short /bag/12/ and
    # any other spelling lead there (and Google learns the proper one).
    if request.path != bag.get_absolute_url():

        query = request.META.get("QUERY_STRING", "")

        return redirect(
            f"{bag.get_absolute_url()}?{query}" if query else bag.get_absolute_url(),
            permanent=True,
        )

    related_bags = (
        Bag.objects.filter(category=bag.category)
        .exclude(id=bag.id)
        .select_related("category")
        .prefetch_related("images")
        .order_by("-created_at")[:4]
    )

    return render(
        request,
        "store/product_detail.html",
        {
            "bag": bag,
            "related_bags": related_bags,
            "seo": seo.product_seo(request, bag),
            "visit": {"bag": bag.id},
        }
    )


def register(request):

    if request.user.is_authenticated:
        return redirect("index")

    if request.method == "POST":

        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")
        password_confirm = request.POST.get("password_confirm", "")

        if not email:
            messages.error(request, "EMAIL IS REQUIRED.")

        elif not password:
            messages.error(request, "PASSWORD IS REQUIRED.")

        elif password != password_confirm:
            messages.error(request, "PASSWORDS DO NOT MATCH.")

        elif User.objects.filter(
            Q(username__iexact=email) | Q(email__iexact=email)
        ).exists():
            messages.error(
                request,
                "AN ACCOUNT WITH THIS EMAIL ALREADY EXISTS."
            )

        else:

            try:
                validate_password(password)

            except ValidationError as errors:

                for error in errors:
                    messages.error(request, error.upper())

            else:

                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=password,
                )

                login(
                    request,
                    user,
                    backend="django.contrib.auth.backends.ModelBackend",
                )

                return redirect("index")

    return render(
        request,
        "store/register.html",
        {"google_enabled": _google_login_enabled(request)}
    )


def cart_add(request, bag_id):

    if request.method !="POST":
        return redirect("product_detail", bag_id=bag_id)

    bag = get_object_or_404(Bag, id=bag_id)

    cart = Cart(request)

    # The Add to cart button on a bag's page sends this request from
    # JavaScript and shows the "Continue shopping / Go to cart" popup.
    # Without JavaScript the old way still works: a message and a redirect.
    from_popup = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    added = cart.add(bag)

    if added:
        try:
            analytics.record_cart_add(request, bag)
        except Exception:
            logger.exception("Could not record an Add to cart")

    if from_popup:
        return JsonResponse(_added_to_cart(cart, bag, added))

    if added:

        messages.success(request, f"{bag.name.upper()} ADDED TO BAG")

    elif bag.stock < 1:

        messages.error(request, f"{bag.name.upper()} IS OUT OF STOCK.")

    else:

        messages.warning(
            request,
            f"ONLY {bag.stock} {bag.name.upper()} IN STOCK, "
            f"AND YOU ALREADY HAVE THEM IN YOUR BAG."
        )

    return redirect(bag.get_absolute_url())


def _added_to_cart(cart, bag, added):
    """What the popup needs to know after an Add to cart."""

    items = list(cart)

    answer = {
        "ok": added,
        "count": sum(item["quantity"] for item in items),
        "name": bag.name,
        "price": ugx_format(bag.price),
        "quantity": next(
            (item["quantity"] for item in items if item["bag"].id == bag.id), 0
        ),
        "image": "",
    }

    first_image = bag.images.first()

    if first_image:
        answer["image"] = cld(first_image.image.url, 160)

    return answer

def cart_detail(request):

    cart = Cart(request)

    cart_bag_ids = set(cart.cart.keys())
    existing_bag_ids = set(
        str(bag_id) for bag_id in
        Bag.objects.filter(id__in=cart_bag_ids).values_list("id", flat=True)
    )
    missing_ids = cart_bag_ids - existing_bag_ids

    if missing_ids:

        for bag_id in missing_ids:
            del cart.cart[bag_id]

        cart.session.modified = True

        messages.warning(
            request,
            "AN ITEM IN YOUR BAG IS NO LONGER AVAILABLE AND HAS BEEN REMOVED."
        )

    return render(
        request,
        "store/cart.html",
        {"cart": cart}
    )


def cart_increase(request, bag_id):

    if request.method != "POST":
        return redirect("cart_detail")

    bag = get_object_or_404(Bag, id=bag_id)

    cart = Cart(request)

    if not cart.increase(bag) and str(bag.id) in cart.cart:

        messages.warning(
            request,
            f"NO MORE {bag.name.upper()} IN STOCK."
        )

    return redirect("cart_detail")


def cart_decrease(request, bag_id):

    if request.method != "POST":
        return redirect("cart_detail")

    bag = get_object_or_404(Bag, id=bag_id)

    cart = Cart(request)

    cart.decrease(bag)

    return redirect("cart_detail")


def cart_remove(request, bag_id):

    if request.method != "POST":
        return redirect("cart_detail")

    bag = get_object_or_404(Bag, id=bag_id)

    cart = Cart(request)

    cart.remove(bag)

    return redirect("cart_detail")


def _next_url(request):
    """
    The page a customer was trying to reach before being asked to log in
    (?next=/checkout/). Only same-site addresses are accepted.
    """

    candidate = request.POST.get("next") or request.GET.get("next") or ""

    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate

    return ""


def _google_login_enabled(request):
    """
    True when a Google app is configured, so the "Continue with Google" button
    is only shown when it can actually work.
    """

    try:
        return bool(get_social_adapter().list_apps(request, provider="google"))
    except Exception:
        return False


def login_view(request):

    next_url = _next_url(request)

    if request.user.is_authenticated:
        return redirect(next_url or "index")

    context = {
        "next": next_url,
        "google_enabled": _google_login_enabled(request),
    }

    if request.method == "POST":

        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")

        user = authenticate(
            request,
            username=email,
            password=password
        )

        if user is not None:

            login(request, user)

            return redirect(next_url or "index")

        context["error"] = "Invalid email or password."

    return render(
        request,
        "store/login.html",
        context
    )


class CustomerLogoutView(auth_views.LogoutView):
    """
    Logout is a POST (the Logout buttons). A plain visit to the address, for
    example from a bookmark, just goes home instead of showing an error page.
    """

    next_page = "index"
    http_method_names = ["get", "post", "options"]

    def get(self, request, *args, **kwargs):
        return redirect("index")


class CustomerPasswordResetForm(PasswordResetForm):
    """
    Also finds customers who signed up with Google and have no password yet,
    so they can set one from the "Forgot password?" link.
    """

    def get_users(self, email):
        return User.objects.filter(email__iexact=email, is_active=True)


class CustomerPasswordResetView(auth_views.PasswordResetView):
    """
    The reset link in the e-mail must point at the site the customer is
    actually using, not at the "example.com" default of the Sites framework.
    """

    template_name = "store/password_reset.html"
    form_class = CustomerPasswordResetForm

    def form_valid(self, form):
        self.extra_email_context = {
            "domain": self.request.get_host(),
            "site_name": "Bags & Beyond",
        }
        return super().form_valid(form)
# Address suggestions while typing: every NEW lookup uses Geoapify credits, so
# one customer may trigger this many per window, and a repeated search is
# answered from the cache instead.
SUGGESTION_REQUESTS_PER_WINDOW = 90
SUGGESTION_WINDOW_SECONDS = 600
SUGGESTION_CACHE_SECONDS = 600


@login_required
@require_safe
@never_cache
def address_suggestions(request):
    """
    Places matching what the customer has typed so far, as JSON:
    {"suggestions": [{"label": ..., "city": ..., "token": ...}]}.
    The browser calls this; only the server ever talks to Geoapify.
    """

    query = " ".join(request.GET.get("q", "").split())[:100]

    if len(query.replace(" ", "")) < SUGGEST_MIN_CHARS:
        return JsonResponse({"suggestions": []})

    cache_key = "address-suggest:" + hashlib.sha1(
        query.casefold().encode("utf-8")
    ).hexdigest()

    cached = cache.get(cache_key)

    if cached is not None:
        return JsonResponse({"suggestions": cached})

    counter_key = f"address-suggest-count:{request.user.pk}"
    cache.add(counter_key, 0, SUGGESTION_WINDOW_SECONDS)

    try:
        count = cache.incr(counter_key)
    except ValueError:
        cache.set(counter_key, 1, SUGGESTION_WINDOW_SECONDS)
        count = 1

    if count > SUGGESTION_REQUESTS_PER_WINDOW:
        return JsonResponse({"suggestions": []}, status=429)

    suggestions = suggest_places(query)

    # Only a real answer is remembered: a failed lookup must not stick.
    if suggestions:
        cache.set(cache_key, suggestions, SUGGESTION_CACHE_SECONDS)

    return JsonResponse({"suggestions": suggestions})


def _checkout_context(cart, quote=None):
    """
    What the checkout page shows. `quote` is the delivery result the customer
    has just been shown (None before they have asked for it). Only a
    calculated quote adds a fee to the total: a quote that needs a phone call
    adds nothing, and the page says so.
    """

    subtotal = cart.get_total_price()

    fee = quote.fee if quote is not None and quote.fee_is_final else Decimal("0")

    return {
        "cart": cart,
        "total": subtotal,
        "subtotal": subtotal,
        "quote": quote,
        "delivery_fee": fee,
        "final_total": subtotal + fee,
        "delivery_message": customer_message(quote) if quote is not None else "",
    }


@login_required
def account(request):

    return render(
        request,
        "store/account.html"
    )


@login_required
def checkout(request):
    cart = Cart(request)

    if not cart.cart:
        return redirect("cart_detail")

    if request.method == "POST":
        full_name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip().lower()
        phone = request.POST.get("phone", "").strip()
        address = request.POST.get("address", "").strip()
        city = request.POST.get("city", "").strip()
        notes = request.POST.get("notes", "").strip()

        errors = []

        if not full_name:
            errors.append("FULL NAME IS REQUIRED.")
        if not email:
            errors.append("EMAIL IS REQUIRED.")
        else:
            try:
                validate_email(email)
            except ValidationError:
                errors.append("PLEASE ENTER A VALID EMAIL ADDRESS")
        if not phone:
            errors.append("PHONE NUMBER IS REQUIRED.")
        if not address:
            errors.append("DELIVERY ADDRESS IS REQUIRED.")
        if not city:
            errors.append("CITY / AREA IS REQUIRED.")

        if errors:
            for error in errors:
                messages.error(request, error)

            return render(
                request,
                "store/checkout.html",
                _checkout_context(cart)
            )

        # ---- DELIVERY ----------------------------------------------------
        # The fee is never read from the form: it is worked out here, on the
        # server, from the address. Two presses of one button:
        #   1st press -> work out the fee and SHOW it (no order yet);
        #   2nd press -> place the order with exactly the fee that was shown.
        # Any change to the address or the basket means a fresh quote, so
        # nobody can place an order at a price they have not seen.
        subtotal_shown = cart.get_total_price()

        # If the customer picked their address from the suggestions, the form
        # carries a signed token for that exact map position. It is trusted
        # only if the signature is genuine and the address text still starts
        # with the place they picked; otherwise the typed text is looked up.
        place = verify_place_token(request.POST.get("place_token", ""), address)
        place_key = place.key if place else ""

        quote = load_quote(request.session, address, city, subtotal_shown, place_key)

        if quote is None:
            # The map lookup happens BEFORE the transaction below, so no
            # database rows stay locked while we wait for it.
            if place is not None:
                quote = calculate_delivery_for_place(place)
            else:
                quote = calculate_delivery(address, city)

            save_quote(
                request.session, address, city, subtotal_shown, quote, place_key
            )

            return render(
                request,
                "store/checkout.html",
                _checkout_context(cart, quote)
            )

        with transaction.atomic():
            order = Order.objects.create(
                user=request.user,
                order_number=uuid.uuid4().hex[:12].upper(),
                email=email,
                full_name=full_name,
                phone=phone,
                address=address,
                city=city,
                notes=notes,
                payment_method="COD",
                payment_status="PENDING",
                total=0,
            )

            subtotal = 0

            for bag_id, quantity in cart.cart.items():
                bag = Bag.objects.select_for_update().get(id=bag_id)

                if quantity > bag.stock:
                    transaction.set_rollback(True)
                    messages.error(
                        request,
                        f"NOT ENOUGH STOCK FOR {bag.name.upper()}."
                    )
                    return redirect("cart_detail")

                OrderItem.objects.create(
                    order=order,
                    bag=bag,
                    product_name=bag.name,
                    price=bag.price,
                    quantity=quantity,
                )

                subtotal += bag.price * quantity
                bag.stock -= quantity
                bag.save(update_fields=["stock"])

            # Only a calculated quote carries a fee. For "too far" and
            # "could not verify" the fee stays 0 and staff agree it by phone.
            delivery_fee = quote.fee if quote.fee_is_final else Decimal("0")

            order.subtotal = subtotal
            order.delivery_fee = delivery_fee
            order.total = subtotal + delivery_fee
            order.delivery_distance_m = quote.distance_m
            order.delivery_status = quote.status
            order.delivery_note = quote.note
            order.save(
                update_fields=[
                    "subtotal",
                    "delivery_fee",
                    "total",
                    "delivery_distance_m",
                    "delivery_status",
                    "delivery_note",
                ]
            )

        request.session["cart"] = {}
        request.session.modified = True
        clear_quote(request.session)

        send_mail(
            subject=(
                f"NEW BAG STORE ORDER — #{order.order_number}"
                + (
                    " — CALL CUSTOMER FOR DELIVERY FEE"
                    if order.delivery_fee_pending
                    else ""
                )
            ),
            message=(
                f"NEW ORDER RECEIVED\n\n"
                f"Order number: {order.order_number}\n"
                f"Date: {order.created_at.strftime('%Y-%m-%d %H:%M')}\n\n"
                f"CUSTOMER\n"
                f"Name: {order.full_name}\n"
                f"Phone: {order.phone}\n"
                f"Email: {order.email}\n\n"
                f"DELIVERY\n"
                f"Address: {order.address}\n"
                f"City / Area: {order.city}\n"
                f"Notes: {order.notes or 'None'}\n"
                f"Delivery check: {order.get_delivery_status_display()}"
                + (
                    f" ({order.delivery_distance_km} km by road)"
                    if order.delivery_distance_km is not None
                    else ""
                )
                + f"\nDelivery note: {order.delivery_note or 'None'}\n\n"
                f"ITEMS\n"
                + "\n".join(
                    f"- {item.product_name} × {item.quantity} — "
                    f"UGX {item.price * item.quantity:,.0f}"
                    for item in order.items.all()
                )
                + "\n\n"
                f"{order_totals_text(order)}"
                f"Payment method: {order.payment_method}\n"
                f"Payment status: {order.payment_status}\n"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[settings.ORDER_NOTIFICATION_EMAIL],
            fail_silently=True,
        )

        send_order_received_email(order)

        return redirect(
            "order_confirmation",
            order_number=order.order_number
        )

    return render(
        request,
        "store/checkout.html",
        _checkout_context(cart)
    )

@login_required
def order_confirmation(request, order_number):

    order = get_object_or_404(
        Order,
        order_number=order_number,
        user=request.user
    )

    return render(
        request,
        "store/order_confirmation.html",
        {
            "order": order,
            "tracker_steps": build_order_tracker(order.status),
        }
    )


@login_required
def order_history(request):

    orders = Order.objects.filter(
        user=request.user
    ).order_by("-created_at")

    return render(
        request,
        "store/order_history.html",
        {
            "orders": orders,
        }
    )


# ---------------------------------------------------------------------------
# Keeping the site awake, and the site icons
# ---------------------------------------------------------------------------

@require_safe
def privacy(request):
    """The privacy policy: a real page, so it can be linked and shown to Google."""

    return render(
        request,
        "store/privacy.html",
        {
            "seo": seo.simple_seo(
                request,
                title="Privacy Policy | Bags & Beyond",
                description=(
                    "How Bags & Beyond collects, uses and protects your personal "
                    "information, and your rights under Uganda's Data Protection "
                    "and Privacy Act."
                ),
                path=reverse("privacy"),
            )
        },
    )


@require_safe
def robots_txt(request):
    """/robots.txt : what search engines may visit, and where the sitemap is."""

    return HttpResponse(
        seo.robots_text(request), content_type="text/plain; charset=utf-8"
    )


@require_safe
@cache_control(public=True, max_age=3600)
def sitemap(request):
    """/sitemap.xml : every page worth listing, for search engines."""

    return HttpResponse(
        seo.sitemap_xml(request), content_type="application/xml; charset=utf-8"
    )


@require_safe
@cache_control(public=True, max_age=86400)
def social_card(request):
    """The picture shown when the shop's front page is shared (see seo.py)."""

    return HttpResponse(seo.social_card_png(), content_type="image/png")


def _same_site(request):
    """Did this request come from a page of this shop?"""

    for header in ("HTTP_ORIGIN", "HTTP_REFERER"):

        sent = request.META.get(header)

        if sent:
            return urlparse(sent).netloc == request.get_host()

    return False


@csrf_exempt
@require_POST
def record_visit(request):
    """
    The small script at the end of every page reports each page view here (see
    base.html). Only pages of this shop are believed, and nothing here can ever
    stop a page from working: the answer is always "204, nothing to say".
    """

    try:
        if _same_site(request):

            try:
                data = json.loads(request.body[:4096] or b"{}")
            except ValueError:
                data = None                       # not ours: ignore it, quietly

            analytics.record_page_view(request, data)

    except Exception:
        logger.exception("Could not record a visit")

    return HttpResponse(status=204)


@require_safe
@never_cache
def healthz(request):
    """
    A tiny page that always answers "ok" and touches nothing: no database, no
    session, no template. An uptime monitor opens it every few minutes so
    Render's free plan never sees 15 quiet minutes, and the site is never put
    to sleep (see "Keeping the site awake on Render" in README.md).
    """

    return HttpResponse("ok", content_type="text/plain")


ICON_FOLDER = Path(__file__).resolve().parent / "static" / "store" / "images"

ICON_FILES = {
    "favicon.ico": "image/x-icon",
    "apple-touch-icon.png": "image/png",
}


LOGO_WIDTHS = (320, 480, 640)


@functools.lru_cache(maxsize=len(LOGO_WIDTHS))
def _logo_webp(width):
    """The logo as a small WebP, made once from the full-size PNG."""

    from PIL import Image

    logo = Image.open(ICON_FOLDER / "bag-store-logo.png").convert("RGBA")

    logo = logo.resize(
        (width, round(logo.height * width / logo.width)), Image.Resampling.LANCZOS
    )

    out = io.BytesIO()

    logo.save(out, format="WEBP", quality=82, alpha_quality=90, method=6)

    return out.getvalue()


@require_safe
@cache_control(public=True, max_age=60 * 60 * 24 * 7)
def logo_image(request, width):
    """/logo-640.webp : the header logo, about a tenth of the size of the PNG."""

    if width not in LOGO_WIDTHS:
        raise Http404("No such logo size.")

    return HttpResponse(_logo_webp(width), content_type="image/webp")


@require_safe
@cache_control(public=True, max_age=60 * 60 * 24 * 7)
def site_icon(request, filename):
    """
    The browser tab icon (/favicon.ico) and the iPhone home-screen icon
    (/apple-touch-icon.png). They are answered at the addresses browsers ask
    for, straight from the files in store/static/store/images/, so they do not
    depend on collectstatic.
    """

    content_type = ICON_FILES.get(filename)

    path = ICON_FOLDER / filename

    if content_type is None or not path.is_file():
        raise Http404("No such icon.")

    return FileResponse(open(path, "rb"), content_type=content_type)