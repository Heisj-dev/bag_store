from django.core.exceptions import ValidationError
from django.db import models
from django.core.validators import MinValueValidator

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
    

    total = models.DecimalField(
        max_digits=10,
        decimal_places=2
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