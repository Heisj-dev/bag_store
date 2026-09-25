from django.contrib import admin

from .models import (
    Category,
    Bag,
    BagImage,
    Order,
    OrderItem,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "description",
    )

    search_fields = (
        "name",
    )


class BagImageInline(admin.TabularInline):

    model = BagImage

    extra = 1

    fields = (
        "image",
        "order",
    )


@admin.register(Bag)
class BagAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "category",
        "price",
        "stock",
        "created_at",
    )

    list_filter = (
        "category",
    )

    search_fields = (
        "name",
        "description",
    )

    ordering = (
        "-created_at",
    )

    inlines = [
        BagImageInline,
    ]
    list_editable=[
        "stock"
    ]


@admin.register(BagImage)
class BagImageAdmin(admin.ModelAdmin):

    list_display = (
        "bag",
        "order",
        "image",
    )

    list_filter = (
        "bag",
    )

    search_fields = (
        "bag__name",
    )

    ordering = (
        "bag",
        "order",
    )


class OrderItemInline(admin.TabularInline):

    model = OrderItem

    extra = 0

    fields = (
        "product_name",
        "price",
        "quantity",
        "item_total",
    )

    readonly_fields = (
        "product_name",
        "price",
        "quantity",
        "item_total",
    )

    def item_total(self, obj):

        return obj.get_total_price()

    item_total.short_description = "ITEM TOTAL"


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):

    list_display = (
        "order_number",
        "full_name",
        "phone",
        "city",
        "user",
        "email",
        "total",
        "payment_method",
        "payment_status",
        "status",
        "created_at",
    )

    list_editable = [
        "status",
        "payment_status",]

    actions = ["mark_as_shipped", "mark_as_delivered"]

    @admin.action(description="Mark selected orders as Shipped")
    def mark_as_shipped(self, request, queryset):
        queryset.update(status="SHIPPED")

    @admin.action(description="Mark selected orders as Delivered")
    def mark_as_delivered(self, request, queryset):
        queryset.update(status="DELIVERED")

    list_filter = (
        "status",
        "payment_method",
        "payment_status",
        "created_at",
    )

    search_fields = (
        "order_number",
        "user__username",
        "user__email",
        "email",
    )

    ordering = (
        "-created_at",
    )

    readonly_fields = (
        "order_number",
        "user",
        "email",
        "total",
        "payment_method",
        "created_at",
        "updated_at",
    )

    inlines = [
        OrderItemInline,
    ]


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):

    list_display = (
        "order",
        "product_name",
        "price",
        "quantity",
        "get_total_price",
    )

    search_fields = (
        "order__order_number",
        "product_name",
    )

    readonly_fields = (
        "product_name",
        "price",
        "quantity",
    )