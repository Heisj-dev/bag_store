from django.db import models
from django.core.validators import MinValueValidator


class Category(models.Model):

    name = models.CharField(max_length=100)

    description = models.TextField(
        blank=True
    )

    def __str__(self):
        return self.name


class Bag(models.Model):

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
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

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return self.name


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