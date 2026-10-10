from django.core.mail import send_mail


def order_totals_text(order):
    """
    The money lines for an email. Orders placed before delivery fees existed
    keep the single TOTAL line they always had.
    """

    if order.subtotal is None:
        return f"TOTAL: UGX {order.total:,.0f}\n"

    lines = [f"Subtotal: UGX {order.subtotal:,.0f}"]

    if order.delivery_fee_pending:
        lines.append("Delivery: to be confirmed by phone (not included yet)")
        lines.append(f"TOTAL: UGX {order.total:,.0f} + delivery fee")
        lines.append(
            "We will call you to agree the delivery fee before your order is dispatched."
        )
    else:
        fee = f"UGX {order.delivery_fee:,.0f}" if order.delivery_fee else "FREE"
        lines.append(f"Delivery: {fee}")
        lines.append(f"TOTAL: UGX {order.total:,.0f}")

    return "\n".join(lines) + "\n"


def _format_items(order):
    return "\n".join(
        f"- {item.product_name} x{item.quantity} — UGX {item.get_total_price():,.0f}"
        for item in order.items.all()
    )


def send_order_received_email(order):
    send_mail(
        subject=f"WE'VE GOT YOUR ORDER — #{order.order_number}",
        message=(
            f"Hi {order.full_name},\n\n"
            f"Thanks for shopping with Bags & Beyond! We've received your order "
            f"and will confirm it with you shortly.\n\n"
            f"ORDER #{order.order_number}\n"
            f"Date: {order.created_at.strftime('%d %B %Y, %H:%M')}\n\n"
            f"ITEMS\n"
            f"{_format_items(order)}\n\n"
            f"{order_totals_text(order)}"
            f"Payment: Pay on Delivery (cash or Mobile Money to the rider)\n\n"
            f"DELIVERING TO\n"
            f"{order.address}\n"
            f"{order.city}\n\n"
            f"WHAT HAPPENS NEXT\n"
            f"1. We confirm your order\n"
            f"2. We prepare your bag\n"
            f"3. A rider is dispatched and will contact you on {order.phone}\n"
            f"4. Your order is delivered — inspect it before paying\n\n"
            f"You can check your order status anytime under MY ORDERS on the site.\n\n"
            f"— Bags & Beyond"
        ),
        from_email=None,
        recipient_list=[order.email],
        fail_silently=True,
    )


def send_order_confirmed_email(order):
    send_mail(
        subject=f"ORDER CONFIRMED — #{order.order_number}",
        message=(
            f"Hi {order.full_name},\n\n"
            f"Your Bags & Beyond order has been confirmed. We're now preparing it for delivery.\n\n"
            f"ORDER #{order.order_number}\n\n"
            f"ITEMS\n"
            f"{_format_items(order)}\n\n"
            f"{order_totals_text(order)}"
            f"Payment: Pay on Delivery (cash or Mobile Money to the rider)\n\n"
            f"DELIVERING TO\n"
            f"{order.address}\n"
            f"{order.city}\n\n"
            f"WHAT HAPPENS NEXT\n"
            f"1. We prepare your bag\n"
            f"2. A rider is dispatched and will contact you on {order.phone}\n"
            f"3. Your order is delivered — inspect it before paying\n\n"
            f"— Bags & Beyond"
        ),
        from_email=None,
        recipient_list=[order.email],
        fail_silently=True,
    )


def send_order_shipped_email(order):
    send_mail(
        subject=f"YOUR ORDER IS ON THE WAY — #{order.order_number}",
        message=(
            f"Hi {order.full_name},\n\n"
            f"Your order has been handed to a rider and is on its way.\n\n"
            f"ORDER #{order.order_number}\n\n"
            f"ITEMS\n"
            f"{_format_items(order)}\n\n"
            f"{order_totals_text(order)}\n"
            f"DELIVERING TO\n"
            f"{order.address}\n"
            f"{order.city}\n\n"
            f"The rider will contact you on {order.phone} before arriving. "
            f"Have the total ready in cash or Mobile Money.\n\n"
            f"— Bags & Beyond"
        ),
        from_email=None,
        recipient_list=[order.email],
        fail_silently=True,
    )


def send_order_delivered_email(order):
    send_mail(
        subject=f"DELIVERED — ORDER #{order.order_number}",
        message=(
            f"Hi {order.full_name},\n\n"
            f"Your order has been delivered. We hope you love it!\n\n"
            f"ORDER #{order.order_number}\n\n"
            f"ITEMS\n"
            f"{_format_items(order)}\n\n"
            f"{order_totals_text(order)}\n"
            f"If anything isn't right, just reply to this email or message us on "
            f"WhatsApp and we'll sort it out.\n\n"
            f"Thanks for shopping with Bags & Beyond.\n\n"
            f"— Bags & Beyond"
        ),
        from_email=None,
        recipient_list=[order.email],
        fail_silently=True,
    )


def send_order_cancelled_email(order):
    send_mail(
        subject=f"ORDER CANCELLED — #{order.order_number}",
        message=(
            f"Hi {order.full_name},\n\n"
            f"Your order has been cancelled and will not be delivered.\n\n"
            f"ORDER #{order.order_number}\n\n"
            f"ITEMS\n"
            f"{_format_items(order)}\n\n"
            f"{order_totals_text(order)}\n"
            f"If this doesn't look right, or you'd like to reorder, reply to this "
            f"email or message us on WhatsApp.\n\n"
            f"— Bags & Beyond"
        ),
        from_email=None,
        recipient_list=[order.email],
        fail_silently=True,
    )
