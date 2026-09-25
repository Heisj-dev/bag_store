import uuid

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.models import User
from django.contrib.auth import login, authenticate
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.core.validators import validate_email
from django.core.mail import send_mail

from .models import Bag, Category, Order, OrderItem
from .cart import Cart
def index(request):

    bags = Bag.objects.select_related("category").prefetch_related("images")

    category_slug = request.GET.get("category")
    query = request.GET.get("q")
    sort = request.GET.get("sort")
    in_stock_only = request.GET.get("in_stock")
    min_price = request.GET.get("min_price")
    max_price = request.GET.get("max_price")

    if category_slug:
        bags = bags.filter(category__name__iexact=category_slug)

    if query:
        bags = bags.filter(
            Q(name__icontains=query) | Q(description__icontains=query)
        )

    if in_stock_only:
        bags = bags.filter(stock__gt=0)

    if min_price:
        try:
            bags = bags.filter(price__gte=float(min_price))
        except ValueError:
            min_price = ""

    if max_price:
        try:
            bags = bags.filter(price__lte=float(max_price))
        except ValueError:
            max_price = ""

    if sort == "price_asc":
        bags = bags.order_by("price")
    elif sort == "price_desc":
        bags = bags.order_by("-price")
    elif sort == "newest":
        bags = bags.order_by("-id")
    elif sort == "name_asc":
        bags = bags.order_by("name")

    categories = Category.objects.all()

    return render(
        request,
        "store/index.html",
        {
            "bags": bags,
            "categories": categories,
            "query": query or "",
            "category_slug": category_slug or "",
            "sort": sort or "",
            "in_stock_only": in_stock_only or "",
            "min_price": min_price or "",
            "max_price": max_price or "",
        }
    )


def product_detail(request, bag_id):

    bag = get_object_or_404(Bag, id=bag_id)

    return render(
        request,
        "store/product_detail.html",
        {"bag": bag}
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

        elif User.objects.filter(username=email).exists():
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

                login(request, user)

                return redirect("index")

    return render(
        request,
        "store/register.html"
    )


def cart_add(request, bag_id):

    bag = get_object_or_404(Bag, id=bag_id)

    cart = Cart(request)

    cart.add(bag)

    messages.success(request,f"{bag.name.upper()} ADDED TO BAG")

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

    cart.increase(bag)

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


def login_view(request):

    if request.user.is_authenticated:
        return redirect("index")

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

            return redirect("index")

        return render(
            request,
            "store/login.html",
            {
                "error": "Invalid email or password."
            }
        )

    return render(
        request,
        "store/login.html"
    )


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
            recipient_list=["jossenndiwalana@gmail.com"],
            fail_silently=False,
        )


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