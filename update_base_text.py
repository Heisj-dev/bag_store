"""
Updates the delivery wording in store/templates/store/base.html so it matches
the real delivery prices. Run it once, from the project folder:

    python update_base_text.py

It changes exactly two passages and nothing else:
  1. the "Delivery" text in the page footer;
  2. the "Pricing zones" list in the Shipping & Returns popup.

If either passage is not found exactly once, it changes NOTHING and says why.
Running it a second time does nothing (it detects the new wording).
To change a price later, edit the PRICES lines below and the DELIVERY_TIERS
list in store/delivery.py together.
"""

import re
import sys
from pathlib import Path

PATH = Path("store/templates/store/base.html")

# ---- the wording (edit here if prices change) ------------------------------
FOOTER_TEXT = (
    "12–48 hour Kampala delivery. Free within 5 km of Kampala CBD, "
    "UGX 3,000 up to 10 km and UGX 5,000 up to 18 km by road. "
    "Further away, we quote you by phone."
)

PRICING_INTRO = (
    "Fees depend on the road distance from our pickup point in Kampala CBD. "
    "You see your fee at checkout before you place your order."
)

PRICES = [
    ("0 – 5 km", "Free delivery."),
    ("5 – 10 km", "UGX 3,000."),
    ("10 – 18 km", "UGX 5,000."),
    ("Over 18 km", "We call you to agree a fee after you place your order."),
]
# ----------------------------------------------------------------------------

FOOTER = re.compile(
    r"12–48 hour Kampala delivery\.(\s+)Free in Kampala Central,\s+"
    r"subsidized for Kampala Metropolitan areas\."
)

PRICING = re.compile(
    r"(?P<indent>[ \t]*)<h3>\s*Pricing zones\s*</h3>\s*<ul>.*?</ul>",
    re.DOTALL,
)

ALREADY_DONE = "Over 18 km"


def new_pricing_block(indent):
    pad = indent

    items = "\n".join(
        f"{pad}    <li>\n"
        f"{pad}        <strong>{label}</strong>\n"
        f"{pad}        — {text}\n"
        f"{pad}    </li>\n"
        for label, text in PRICES
    )

    return (
        f"{pad}<h3>\n"
        f"{pad}    Delivery fees\n"
        f"{pad}</h3>\n\n"
        f"{pad}<p>\n"
        f"{pad}    {PRICING_INTRO}\n"
        f"{pad}</p>\n\n"
        f"{pad}<ul>\n\n"
        f"{items}\n"
        f"{pad}</ul>"
    )


def update(text):
    """Returns (new_text, message). new_text is None when nothing should change."""

    if ALREADY_DONE in text and "Free in Kampala Central" not in text:
        return None, "Already up to date. Nothing changed."

    footer_hits = len(FOOTER.findall(text))
    pricing_hits = len(PRICING.findall(text))

    if footer_hits != 1 or pricing_hits != 1:
        return None, (
            "Not changed: expected to find each old passage exactly once, but "
            f"found the footer text {footer_hits} time(s) and the pricing "
            f"list {pricing_hits} time(s). The file may already have been edited."
        )

    text = FOOTER.sub(
        lambda m: FOOTER_TEXT,
        text,
    )

    text = PRICING.sub(lambda m: new_pricing_block(m.group("indent")), text)

    return text, "Updated the footer and the Shipping & Returns popup."


def main():
    if not PATH.exists():
        sys.exit(f"Cannot find {PATH}. Run this from the project folder (where manage.py is).")

    raw = PATH.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")

    new_text, message = update(text)

    print(message)

    if new_text is None:
        return

    if crlf:
        new_text = new_text.replace("\n", "\r\n")

    PATH.write_bytes(new_text.encode("utf-8"))


if __name__ == "__main__":
    main()
