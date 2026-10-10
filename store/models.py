from django.core.exceptions import ValidationError
from django.db import models
from django.core.validators import MinValueValidator
from django.urls import reverse
from django.utils.text import slugify

# How many bags the homepage shows. The view and the admin both use this.
HOMEPAGE_BAG_LIMIT = 12


class Category(models.Model):

    name = models.CharField(max_length=100)

    description = models.TextField(
        blank=True
    )

    class Meta:
        # Always A to Z: the menu, the filter buttons and the admin.
        ordering = ["name"]
        verbose_name_plural = "categories"

    @property
    def slug(self):
        # "Gym Bags" -> "gym-bags": the category's address is /category/gym-bags/
        return slugify(self.name) or "category"

    def get_absolute_url(self):
        return reverse("category_page", args=[self.slug])

    def __str__(self):
        return self.name


class Bag(models.Model):

    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="bags"
    )

    name = models.CharField(
        max_length=200
    )

    description = models.TextField(
        blank=True
    )

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[
            MinValueValidator(0)
        ]
    )

    stock = models.PositiveIntegerField(
        default=0
    )

    show_on_homepage = models.BooleanField(
        default=False,
        verbose_name="show on homepage",
        help_text=(
            "Tick to feature this bag on the homepage. A new bag is never "
            "featured automatically."
        ),
    )

    homepage_order = models.PositiveIntegerField(
        default=0,
        verbose_name="homepage position",
        help_text=(
            "Where this bag appears on the homepage: 1 is first, 2 is second, "
            "and so on. The homepage shows at most 12 bags, in this order."
        ),
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    @property
    def slug(self):
        # "Zara Tote" -> "zara-tote": the bag's address is /bag/12/zara-tote/
        return slugify(self.name) or "bag"

    def get_absolute_url(self):
        return reverse("product_detail_slug", args=[self.id, self.slug])

    def __str__(self):
        return self.name

    @property
    def is_in_stock(self):
        return self.stock > 0

    def clean(self):
        super().clean()

        if self.show_on_homepage and self.homepage_order < 1:
            raise ValidationError({
                "homepage_order": (
                    "Give this bag a homepage position of 1 or more "
                    "(1 is shown first)."
                )
            })


class BagImage(models.Model):

    bag = models.ForeignKey(
        Bag,
        on_delete=models.CASCADE,
        related_name="images"
    )

    image = models.ImageField(
        upload_to="bags/"
    )

    order = models.PositiveIntegerField(
        default=0
    )

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.bag.name} image {self.order}"


class Order(models.Model):

    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("CONFIRMED", "Confirmed"),
        ("PROCESSING", "Processing"),
        ("SHIPPED", "Shipped"),
        ("DELIVERED", "Delivered"),
        ("CANCELLED", "Cancelled"),
    ]

    PAYMENT_METHOD_CHOICES = [
        ("COD", "Pay on Delivery"),
    ]

    PAYMENT_STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("PAID", "Paid"),
    ]

    user = models.ForeignKey(
        "auth.User",
        on_delete=models.CASCADE,
        related_name="orders"
    )

    order_number = models.CharField(
        max_length=20,
        unique=True
    )

    email = models.EmailField()

    full_name = models.CharField(
        max_length=200
    )

    phone = models.CharField(
        max_length=20
    )

    address = models.TextField()

    city = models.CharField(
        max_length=100
    )

    notes = models.TextField(
        blank=True
    )

    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        default="COD"
    )

    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default="PENDING"
    )
    

    # The FINAL total: subtotal + delivery fee. Orders placed before delivery
    # fees existed keep exactly the total they always had.
    total = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    # Delivery. Every field below is optional or has a default, so orders
    # placed before delivery fees existed stay valid and unchanged.
    DELIVERY_STATUS_CHOICES = [
        ("NOT_CALCULATED", "Not calculated (earlier order)"),
        ("CALCULATED", "Calculated"),
        ("QUOTE_REQUIRED", "Too far for a set fee: quote needed"),
        ("UNVERIFIED", "Address not verified: confirm fee"),
        ("AGREED", "Fee agreed by phone"),
    ]
    # The products only. Empty on orders placed before delivery fees existed:
    # for those, `total` already is the products total.
    subtotal = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )

    # What the customer pays for delivery. 0 means free OR "not agreed yet":
    # check delivery_status to tell them apart.
    # db_default (not just default) so the database itself fills these in.
    # That keeps the live site working if this migration runs on the shared
    # database a few minutes before the new code is deployed.
    delivery_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        db_default=0,
    )

    # Driving distance from the pickup point, in metres.
    delivery_distance_m = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    delivery_status = models.CharField(
        max_length=20,
        choices=DELIVERY_STATUS_CHOICES,
        default="NOT_CALCULATED",
        db_default="NOT_CALCULATED",
    )

    # For staff: what the map service matched the address to, or why the
    # fee could not be worked out.
    delivery_note = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_default="",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="PENDING"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    # Set when a cancelled order's bags have been put back in stock, so a
    # cancellation can never put them back twice. Not editable by hand.
    stock_restored = models.BooleanField(
        default=False,
        editable=False,
    )

    def clean(self):

        # A cancelled order is final: its bags are already back in stock.
        if self.pk:

            previous = (
                Order.objects.filter(pk=self.pk)
                .values_list("status", flat=True)
                .first()
            )

            if previous == "CANCELLED" and self.status != "CANCELLED":
                raise ValidationError(
                    "A cancelled order cannot be reopened: its bags are "
                    "already back in stock. Create a new order instead."
                )
    @property
    def products_total(self):
        """
        The products only. Orders placed before delivery fees existed have
        no subtotal saved, and their total is the products total.
        """
        return self.subtotal if self.subtotal is not None else self.total

    @property
    def delivery_distance_km(self):
        if self.delivery_distance_m is None:
            return None
        return round(self.delivery_distance_m / 1000, 1)

    @property
    def delivery_fee_pending(self):
        """True while the delivery fee still has to be agreed by phone."""
        return self.delivery_status in ("QUOTE_REQUIRED", "UNVERIFIED")
    def __str__(self):
        return self.order_number


class OrderItem(models.Model):

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items"
    )

    bag = models.ForeignKey(
        Bag,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    product_name = models.CharField(
        max_length=200
    )

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    quantity = models.PositiveIntegerField(
        validators=[MinValueValidator(1)]
    )

    def get_total_price(self):

        if self.price is None or self.quantity is None:
            return 0

        return self.price * self.quantity

    def __str__(self):
        return f"{self.product_name} x {self.quantity}"

class VisitEvent(models.Model):
    """
    One anonymous thing a visitor did: looked at a page, or added a bag to
    the cart. There is no name, no cookie and no IP address here: `visitor`
    is a scrambled code that changes every day, so the same person on two
    different days looks like two visitors.
    """

    PAGE = "page"
    CART = "cart"

    KIND_CHOICES = [
        (PAGE, "Page view"),
        (CART, "Added to cart"),
    ]

    created_at = models.DateTimeField(auto_now_add=True)

    day = models.DateField(db_index=True)          # Kampala time

    hour = models.PositiveSmallIntegerField()      # 0 to 23, Kampala time

    visitor = models.CharField(max_length=16)

    kind = models.CharField(max_length=8, choices=KIND_CHOICES)

    path = models.CharField(max_length=200, blank=True)

    bag_id = models.PositiveIntegerField(null=True, blank=True)

    category = models.CharField(max_length=100, blank=True)

    term = models.CharField(max_length=80, blank=True)

    results = models.PositiveIntegerField(null=True, blank=True)

    source = models.CharField(max_length=60, blank=True)

    device = models.CharField(max_length=10, blank=True)

    os = models.CharField(max_length=12, blank=True)

    browser = models.CharField(max_length=16, blank=True)

    class Meta:
        verbose_name = "visitor event"
        verbose_name_plural = "visitor analytics"
        indexes = [
            models.Index(fields=["kind", "day"]),
            models.Index(fields=["bag_id", "kind"]),
        ]

    def __str__(self):
        return f"{self.day} {self.kind} {self.path}"
