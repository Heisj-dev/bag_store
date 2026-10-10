from collections import Counter

from django.contrib import admin, messages
from django.template.response import TemplateResponse
from django.db.models import Max

from . import analytics
from .models import (
    HOMEPAGE_BAG_LIMIT,
    Category,
    Bag,
    BagImage,
    Order,
    OrderItem,
    VisitEvent,
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


class HomepageFilter(admin.SimpleListFilter):
    """Quickly see which bags are (or are not) on the homepage."""

    title = "homepage"
    parameter_name = "homepage"

    def lookups(self, request, model_admin):
        return [
            ("yes", "On the homepage"),
            ("no", "Not on the homepage"),
        ]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(show_on_homepage=True)
        if self.value() == "no":
            return queryset.filter(show_on_homepage=False)
        return queryset


class StockFilter(admin.SimpleListFilter):
    title = "stock"
    parameter_name = "stock_level"

    def lookups(self, request, model_admin):
        return [
            ("out", "Out of stock"),
            ("low", "Low stock (1-5)"),
            ("in", "In stock"),
        ]

    def queryset(self, request, queryset):
        if self.value() == "out":
            return queryset.filter(stock=0)
        if self.value() == "low":
            return queryset.filter(stock__gte=1, stock__lte=5)
        if self.value() == "in":
            return queryset.filter(stock__gt=0)
        return queryset


@admin.register(Bag)
class BagAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "category",
        "price",
        "stock",
        "stock_status",
        "show_on_homepage",
        "homepage_order",
        "created_at",
    )

    list_filter = (
        HomepageFilter,
        StockFilter,
        "category",
    )

    search_fields = (
        "name",
        "description",
    )

    # The bags on the homepage come first, in the order customers see them.
    ordering = (
        "-show_on_homepage",
        "homepage_order",
        "-created_at",
    )

    inlines = [
        BagImageInline,
    ]

    list_editable = [
        "stock",
        "show_on_homepage",
        "homepage_order",
    ]

    actions = [
        "add_to_homepage",
        "remove_from_homepage",
    ]

    fieldsets = (
        (None, {
            "fields": (
                "name",
                "category",
                "description",
                "price",
                "stock",
            ),
        }),
        ("Homepage", {
            "fields": (
                "show_on_homepage",
                "homepage_order",
            ),
        }),
    )

    @admin.display(description="Availability", ordering="stock")
    def stock_status(self, obj):
        return "In stock" if obj.stock > 0 else "OUT OF STOCK"

    # ------------------------------------------------------------------
    # Homepage helpers
    # ------------------------------------------------------------------

    def changelist_view(self, request, extra_context=None):
        """Warn when the homepage selection needs attention."""

        if request.method == "GET":
            self._warn_about_homepage(request)

        return super().changelist_view(request, extra_context)

    def _warn_about_homepage(self, request):

        featured = list(
            Bag.objects.filter(show_on_homepage=True)
            .order_by("homepage_order", "-created_at")
        )

        count = len(featured)

        if count > HOMEPAGE_BAG_LIMIT:
            self.message_user(
                request,
                f"{count} bags are marked for the homepage, but only the "
                f"first {HOMEPAGE_BAG_LIMIT} (by position) are shown. "
                f"Untick {count - HOMEPAGE_BAG_LIMIT} to make room.",
                level=messages.WARNING,
            )

        elif 0 < count < HOMEPAGE_BAG_LIMIT:
            self.message_user(
                request,
                f"Homepage: {count} of {HOMEPAGE_BAG_LIMIT} bags selected "
                f"({HOMEPAGE_BAG_LIMIT - count} free).",
                level=messages.INFO,
            )

        elif count == 0:
            self.message_user(
                request,
                "No bags are selected for the homepage yet, so the homepage "
                "is empty. Tick \"Show on homepage\" and give each bag a "
                "position.",
                level=messages.WARNING,
            )

        positions = Counter(bag.homepage_order for bag in featured)
        repeated = sorted(p for p, n in positions.items() if n > 1)

        if repeated:
            shown = ", ".join(str(p) for p in repeated)
            self.message_user(
                request,
                f"More than one homepage bag has the same position "
                f"({shown}). Give each bag its own position so the order is "
                f"exactly what you intend.",
                level=messages.WARNING,
            )

    @admin.action(description="Add selected bags to the end of the homepage")
    def add_to_homepage(self, request, queryset):

        room = HOMEPAGE_BAG_LIMIT - Bag.objects.filter(
            show_on_homepage=True
        ).count()

        to_add = list(
            queryset.filter(show_on_homepage=False).order_by("name")
        )

        if not to_add:
            self.message_user(
                request,
                "Those bags are already on the homepage.",
                level=messages.INFO,
            )
            return

        if len(to_add) > room:
            self.message_user(
                request,
                f"The homepage has room for {max(room, 0)} more bag(s) but "
                f"you selected {len(to_add)}. Remove a bag from the homepage "
                f"first, or select fewer bags.",
                level=messages.ERROR,
            )
            return

        last = Bag.objects.filter(
            show_on_homepage=True
        ).aggregate(top=Max("homepage_order"))["top"] or 0

        for position, bag in enumerate(to_add, start=last + 1):
            bag.show_on_homepage = True
            bag.homepage_order = position
            bag.save(update_fields=["show_on_homepage", "homepage_order"])

        self.message_user(
            request,
            f"Added {len(to_add)} bag(s) to the end of the homepage. "
            f"Change their positions below if you want them elsewhere.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Remove selected bags from the homepage")
    def remove_from_homepage(self, request, queryset):

        removed = queryset.filter(show_on_homepage=True).update(
            show_on_homepage=False,
            homepage_order=0,
        )

        self.message_user(
            request,
            f"Removed {removed} bag(s) from the homepage.",
            level=messages.SUCCESS,
        )


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
        "delivery_fee",
        "total",
        "delivery_status",
        "payment_method",
        "payment_status",
        "status",
        "created_at",
    )
        
    list_editable = [
        "status",
        "payment_status",
    ]

    actions = [
        "mark_as_processing",
        "mark_as_shipped",
        "mark_as_delivered",
        "mark_as_cancelled",
        "delivery_fee_agreed",
    ]

    def get_readonly_fields(self, request, obj=None):
        """
        The money fields are locked, with ONE exception: while an order's
        delivery fee is still to be agreed by phone, staff may type it in.
        """

        readonly = list(super().get_readonly_fields(request, obj))

        if obj is not None and obj.delivery_fee_pending:
            readonly.remove("delivery_fee")

        return readonly

    def save_model(self, request, obj, form, change):
        """
        When staff enter the agreed delivery fee, the final total follows it
        (subtotal + fee) and the order stops being "fee to be agreed".
        """

        if (
            change
            and obj.delivery_fee_pending
            and "delivery_fee" in form.changed_data
        ):
            self._record_agreed_fee(request, obj)

        super().save_model(request, obj, form, change)

    @staticmethod
    def _record_agreed_fee(request, order):
        order.total = order.products_total + order.delivery_fee
        order.delivery_status = "AGREED"
        order.delivery_note = (
            f"Fee agreed by phone, recorded by {request.user.get_username()}. "
            f"{order.delivery_note}"
        )[:255]

    @admin.action(description="Delivery fee agreed (keep the fee shown)")
    def delivery_fee_agreed(self, request, queryset):
        """For a quote order where the agreed fee is the one already on it,
        for example 0 because the customer is close enough to be free."""

        done = 0

        for order in queryset.filter(
            delivery_status__in=["QUOTE_REQUIRED", "UNVERIFIED"]
        ):
            self._record_agreed_fee(request, order)
            order.save()
            done += 1

        self.message_user(
            request,
            f"{done} order(s) marked as delivery fee agreed.",
        )

    def open_orders(self, request, queryset):
        """The orders an action may move on. A cancelled order is final."""

        cancelled = queryset.filter(status="CANCELLED").count()

        if cancelled:
            self.message_user(
                request,
                f"{cancelled} cancelled order(s) were left as they are: "
                "a cancelled order cannot be reopened.",
                level=messages.WARNING,
            )

        return queryset.exclude(status="CANCELLED")

    @admin.action(description="Confirm selected orders")
    def mark_as_confirmed(self, request, queryset):

        for order in self.open_orders(request, queryset):
            order.status = "CONFIRMED"
            order.save()

        self.message_user(
            request,
            "Selected orders have been confirmed."
        )

    @admin.action(description="Mark selected orders as Processing")
    def mark_as_processing(self, request, queryset):

        for order in self.open_orders(request, queryset):
            order.status = "PROCESSING"
            order.save()

        self.message_user(
            request,
            "Selected orders are now processing."
        )

    @admin.action(description="Mark selected orders as Shipped")
    def mark_as_shipped(self, request, queryset):

        for order in self.open_orders(request, queryset):
            order.status = "SHIPPED"
            order.save()

        self.message_user(
            request,
            "Selected orders have been marked as shipped."
        )

    @admin.action(description="Mark selected orders as Delivered")
    def mark_as_delivered(self, request, queryset):

        for order in self.open_orders(request, queryset):
            order.status = "DELIVERED"
            order.save()

        self.message_user(
            request,
            "Selected orders have been marked as delivered."
        )

    @admin.action(description="Cancel selected orders")
    def mark_as_cancelled(self, request, queryset):

        for order in queryset:
            order.status = "CANCELLED"
            order.save()

        self.message_user(
            request,
            "Selected orders have been cancelled."
        )

    list_filter = (
        "status",
        "delivery_status",
        "payment_method",
        "payment_status",
        "created_at",
        "updated_at",
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
        "subtotal",
        "delivery_fee",
        "total",
        "delivery_distance_m",
        "delivery_status",
        "delivery_note",
        "payment_method",
        "stock_restored",
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


@admin.register(VisitEvent)
class VisitEventAdmin(admin.ModelAdmin):
    """
    "Visitor analytics": the whole page is a dashboard, not a list.

    ?days=1, 7, 30, 90 picks the period, and ?days=0 means all time.
    """

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):

        try:
            days = int(request.GET.get("days", 30))
        except ValueError:
            days = 30

        if days not in (0, 1, 7, 30, 90):
            days = 30

        context = {
            **self.admin_site.each_context(request),
            "title": "Visitor analytics",
            "opts": self.model._meta,
            "stats": analytics.build_dashboard(days),
        }

        return TemplateResponse(
            request, "admin/store/visitevent/change_list.html", context
        )

