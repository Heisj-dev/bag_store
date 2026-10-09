import json

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def ldjson(data):
    """
    Structured data (JSON-LD) for a <script> tag. The characters that could end
    the script early are written as \\u escapes, so nothing a bag is called can
    break the page.
    """

    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    return mark_safe(
        text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    )
