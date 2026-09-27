from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter(name="ugx_format")
def ugx_format(value):
    """
    Format a price as a whole number with thousands separators,
    e.g. Decimal("80000.00") -> "80,000".

    Falls back to returning the value unchanged if it isn't something
    that can be read as a number, rather than raising an error.
    """

    try:
        number = int(round(Decimal(value)))
    except (InvalidOperation, TypeError, ValueError):
        return value

    return "{:,}".format(number)