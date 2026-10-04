import uuid
from decimal import Decimal, InvalidOperation

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
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from allauth.socialaccount.adapter import get_adapter as get_social_adapter

from .models import HOMEPAGE_BAG_LIMIT, Bag, Category, Order, OrderItem
from .cart import Cart
from .emails import send_order_received_email

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


def index(request):
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

    page_number = request.GET.get("page")

    if _filters_in_use(filters):
        shown = _results_page(page_number, filters)
    else:
        shown = _catalogue_page(page_number)

    # The address-bar options without "page", so every page link keeps the
    # search, category, stock, price and sort the customer chose.
    params = request.GET.copy()
    params.pop("page", None)

    return render(
        request,
        "store/index.html",
        {
            **shown,
            "querystring": params.urlencode(),
            "categories": Category.objects.all(),
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


def product_detail(request, bag_id):

    bag = get_object_or_404(Bag, id=bag_id)

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

    if cart.add(bag):

        messages.success(request, f"{bag.name.upper()} ADDED TO BAG")

    elif bag.stock < 1:

        messages.error(request, f"{bag.name.upper()} IS OUT OF STOCK.")

    else:

        messages.warning(
            request,
            f"ONLY {bag.stock} {bag.name.upper()} IN STOCK, "
            f"AND YOU ALREADY HAVE THEM IN YOUR BAG."
        )

    return redirect(
        "product_detail",
        bag_id=bag.id
    )

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
                {
                    "cart": cart,
                    "total": cart.get_total_price(),
                }
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
            
            total = 0
            
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
                
                total += bag.price * quantity
                bag.stock -= quantity
                bag.save(update_fields=["stock"])
                
            order.total = total
            order.save(update_fields=["total"])

        request.session["cart"] = {}
        request.session.modified = True

        send_mail(
            subject=f"NEW BAG STORE ORDER — #{order.order_number}",
            message=(
                f"NEW ORDER RECEIVED\n\n"
                f"Order number: {order.order_number}\n"
                f"Date: {order.created_at.strftime('%d %B %Y, %H:%M')}\n\n"
                f"CUSTOMER\n"
                f"Name: {order.full_name}\n"
                f"Email: {order.email}\n"
                f"Phone: {order.phone}\n\n"
                f"DELIVERY\n"
                f"Address: {order.address}\n"
                f"City / Area: {order.city}\n"
                f"Notes: {order.notes or 'None'}\n\n"
                f"ITEMS\n"
                + "\n".join(
                    f"- {item.product_name} × {item.quantity} — "
                    f"UGX {item.get_total_price():,.0f}"
                    for item in order.items.all()
                )
                + "\n\n"
                f"TOTAL: UGX {order.total:,.0f}\n"
                f"Payment method: {order.payment_method}\n"
                f"Payment status: {order.payment_status}\n"
            ),
            from_email=None,
            recipient_list=["jossenndiwalana@gmail.com",
                            "ssemanyijoel22@gmail.com"],
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
        {
            "cart": cart,
            "total": cart.get_total_price(),
        }
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