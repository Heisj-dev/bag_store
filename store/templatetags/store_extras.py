from decimal import Decimal, InvalidOperation

from django import template
from django.utils.safestring import mark_safe

register = template.Library()

CLOUDINARY_UPLOAD = "/image/upload/"


def cld_url(url, transformation):
    """
    The same Cloudinary picture with a transformation added to its address.
    Anything that is not a Cloudinary address is returned unchanged.
    """

    url = str(url or "")

    if CLOUDINARY_UPLOAD not in url:
        return url

    head, tail = url.split(CLOUDINARY_UPLOAD, 1)

    return f"{head}{CLOUDINARY_UPLOAD}{transformation}/{tail}"


@register.filter(name="cld")
def cld(url, width):
    """
    A smaller copy of a Cloudinary picture, at most `width` pixels wide, in the
    best format and quality the visitor's browser can show (WebP, AVIF, ...).
    Phones on mobile data download a fraction of the original.
    """

    try:
        width = int(width)
    except (TypeError, ValueError):
        return url

    return cld_url(url, f"f_auto,q_auto,w_{width},c_limit")


@register.simple_tag
def cld_srcset(url, widths="320,480,640,960"):
    """
    The srcset="..." attribute that lets the browser pick the right size of a
    Cloudinary picture. Nothing for any other kind of address.
    """

    if CLOUDINARY_UPLOAD not in str(url or ""):
        return ""

    sizes = [int(width) for width in str(widths).split(",") if width.strip()]

    candidates = ", ".join(f"{cld(url, size)} {size}w" for size in sizes)

    return mark_safe(f'srcset="{candidates}"')


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