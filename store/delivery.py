"""
Delivery distance and fee for Bags & Beyond.

    result = calculate_delivery(address, city)

works out the road distance from our pickup point (Giant Shopping Centre,
Kampala CBD) to the customer's address with Geoapify, then applies our price
list. It never raises: whatever goes wrong, the caller gets a DeliveryResult
that says what happened, so checkout can carry on.

Safety rules this module keeps:

* The API key comes from settings (an environment variable) and is only ever
  sent to Geoapify. It is never logged, never stored, never put in a message.
  Geoapify takes the key in the URL, and `requests` can print that URL inside
  its error messages, so errors are logged by TYPE only, never by message.
* Anything we cannot be sure about (address not found, unclear match, service
  down, timeout, no key) never produces a made-up fee. The result is marked
  for a phone call instead.
"""

import logging
import math
import re
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.core import signing

logger = logging.getLogger(__name__)

GEOCODE_URL = "https://api.geoapify.com/v1/geocode/search"
AUTOCOMPLETE_URL = "https://api.geoapify.com/v1/geocode/autocomplete"
ROUTING_URL = "https://api.geoapify.com/v1/routing"

# (seconds to connect, seconds to wait for the answer). Checkout makes two
# calls one after the other, so the worst case is about 16 seconds.
TIMEOUT = (3, 5)

# Giant Shopping Centre, Kampala CBD (override in settings if it ever moves).
DEFAULT_PICKUP_LAT = 0.3153404
DEFAULT_PICKUP_LNG = 32.5749709

# Price list: (longest distance in metres this price covers, fee in UGX).
# Exactly 5,000 m is still free; 5,001 m costs UGX 3,000, and so on.
# Beyond the last row the customer gets a quote by phone.
DELIVERY_TIERS = [
    (5_000, Decimal("0")),
    (10_000, Decimal("3000")),
    (18_000, Decimal("5000")),
]

# The furthest distance that has a fixed price. Further than this: a quote.
FIXED_FEE_LIMIT_M = DELIVERY_TIERS[-1][0]

# How sure the map service must be about the address (0 to 1). Below this we
# do not trust the match and ask staff to confirm. Tune with real addresses.
MIN_CONFIDENCE = 0.5

# Two candidate matches this close in confidence, and further apart than this
# many metres, mean the address could be in two different places.
AMBIGUOUS_CONFIDENCE_GAP = 0.1
AMBIGUOUS_DISTANCE_M = 3_000

# The longest address text we send to the map service.
MAX_QUERY_LENGTH = 300

# How specific a match is (Geoapify's "result_type"). A match that only
# reaches a whole city, county or country says nothing about WHERE in it the
# customer lives, and the middle of Kampala is close to our pickup point: it
# would wrongly give free delivery to a nonsense address. Never trusted.
TOO_GENERAL_RESULT_TYPES = {"country", "state", "county", "city", "postcode"}

# A suburb or district is a good match, but it is the middle of an area, not
# the customer's door. Priced normally, but staff are told it is approximate.
AREA_LEVEL_RESULT_TYPES = {"suburb", "district"}

# A TOWN the customer actually named ("Kira", "Mukono", "Entebbe"). A town on
# its own is normally too general (see TOO_GENERAL_RESULT_TYPES), but when the
# address the customer typed IS the town's name, and the map service is sure
# (this confident), the middle of the town is a fair basis for the fee. A town
# is never trusted for FREE delivery: its middle is not a street, and the
# middle of Kampala itself is right next to our pickup point.
TOWN_MIN_CONFIDENCE = 0.9

# Words that say nothing about where: "Kira town" is just "Kira".
IGNORED_PLACE_WORDS = {"town", "area", "uganda"}

# Same values as Order.DELIVERY_STATUS_CHOICES.
CALCULATED = "CALCULATED"
QUOTE_REQUIRED = "QUOTE_REQUIRED"
UNVERIFIED = "UNVERIFIED"

ZERO = Decimal("0")


@dataclass
class DeliveryResult:
    status: str                  # CALCULATED, QUOTE_REQUIRED or UNVERIFIED
    fee: Decimal = ZERO          # only meaningful when status is CALCULATED
    distance_m: int | None = None
    note: str = ""               # for staff
    problem: str = ""            # "address" or "service" when UNVERIFIED
    approximate: bool = False    # priced from the middle of an area or town

    @property
    def distance_km(self):
        if self.distance_m is None:
            return None
        return round(self.distance_m / 1000, 1)

    @property
    def fee_is_final(self):
        return self.status == CALCULATED


class _AddressProblem(Exception):
    """The address could not be placed on the map reliably."""


class _ServiceProblem(Exception):
    """The map service did not give us a usable answer."""


def fee_for_distance(distance_m):
    """The delivery fee for a road distance in metres, or None for 'get a quote'."""

    for longest, fee in DELIVERY_TIERS:
        if distance_m <= longest:
            return fee

    return None


def _get_json(url, params):
    """
    One call to Geoapify. Raises _ServiceProblem with a SAFE message (never
    the key, never the URL) if anything goes wrong.
    """

    try:
        response = requests.get(url, params=params, timeout=TIMEOUT)
    except requests.Timeout:
        raise _ServiceProblem("The map service took too long to answer.") from None
    except requests.RequestException as exc:
        logger.warning("Delivery lookup network error: %s", type(exc).__name__)
        raise _ServiceProblem("Could not reach the map service.") from None

    if response.status_code != 200:
        logger.warning("Delivery lookup got HTTP %s", response.status_code)
        raise _ServiceProblem(
            f"The map service returned an error (HTTP {response.status_code})."
        )

    try:
        data = response.json()
    except ValueError:
        raise _ServiceProblem("The map service sent an unreadable answer.") from None

    if not isinstance(data, dict):
        raise _ServiceProblem("The map service sent an unexpected answer.")

    return data


def _straight_line_m(lat1, lon1, lat2, lon2):
    """Distance in metres between two points on the earth (haversine)."""

    radius = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)

    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2

    return 2 * radius * math.asin(math.sqrt(a))


def _confidence(result):
    try:
        return float((result.get("rank") or {}).get("confidence", 0))
    except (TypeError, ValueError):
        return 0.0


def _coordinates(result):
    try:
        return float(result["lat"]), float(result["lon"])
    except (KeyError, TypeError, ValueError):
        return None


def _search(address, city, api_key, pickup_lat, pickup_lng):
    """The map service's best guesses for the typed address (raw results)."""

    text = " ".join(f"{address} {city}".split())[:MAX_QUERY_LENGTH]

    data = _get_json(
        GEOCODE_URL,
        {
            "text": text,
            "filter": "countrycode:ug",
            # Prefer matches near the pickup point when a name exists twice.
            "bias": f"proximity:{pickup_lng},{pickup_lat}",
            "limit": 5,
            "format": "json",
            "apiKey": api_key,
        },
    )

    return [
        r for r in (data.get("results") or [])
        if isinstance(r, dict) and _coordinates(r)
    ]


def _words(text):
    return re.findall(r"[^\W_]+", (text or "").casefold())


def _place_name(result):
    """The place's own name: the first part of 'Kira, Wakiso, Uganda'."""
    return (result.get("formatted") or "").split(",")[0]


def _named_town(results, address, city):
    """
    The town the customer named, if the address they typed IS a town's name.

    "Kira" typed as the address means Kira. But "kizungu near latitude 0" typed
    with the city "Kampala" does NOT mean Kampala: the map service just falls
    back to the city, and that must never be mistaken for the customer's place.
    """

    in_city_field = set(_words(city))

    typed = [w for w in _words(address) if w not in IGNORED_PLACE_WORDS]
    typed = [w for w in typed if w not in in_city_field] or [
        w for w in _words(address) if w not in IGNORED_PLACE_WORDS
    ]

    if not typed:
        return None

    for result in results:
        if (
            result.get("result_type") == "city"
            and _confidence(result) >= TOWN_MIN_CONFIDENCE
            and _words(_place_name(result)) == typed
        ):
            return result

    return None


def _geocode(address, city, api_key, pickup_lat, pickup_lng):
    """
    Turn the typed address into (lat, lon, what-we-matched-it-to, kind).
    kind is "" for a normal match, "area" for a suburb or district, and
    "town" for a town the customer named.
    """

    results = _search(address, city, api_key, pickup_lat, pickup_lng)

    if not results:
        raise _AddressProblem("Address not found on the map.")

    # A town that was named outright wins over places that merely sit near it
    # or share its name (a hospital, a shop, a street).
    town = _named_town(results, address, city)

    if town is not None:
        lat, lon = _coordinates(town)
        return (
            lat,
            lon,
            f"TOWN CENTRE ONLY, confirm the exact spot. {town.get('formatted', '')}",
            "town",
        )

    best = results[0]

    if best.get("result_type") in TOO_GENERAL_RESULT_TYPES:
        raise _AddressProblem(
            "Address only matched to a general area: "
            f"{best.get('formatted', 'unknown place')}."
        )

    if _confidence(best) < MIN_CONFIDENCE:
        raise _AddressProblem(
            "Address only loosely matched: "
            f"{best.get('formatted', 'unknown place')}."
        )

    # Could the same words mean two well separated places?
    for other in results[1:]:

        if _confidence(best) - _confidence(other) > AMBIGUOUS_CONFIDENCE_GAP:
            continue

        far_apart = _straight_line_m(*_coordinates(best), *_coordinates(other))

        if far_apart > AMBIGUOUS_DISTANCE_M:
            raise _AddressProblem(
                "Address could mean more than one place: "
                f"{best.get('formatted', '?')} or {other.get('formatted', '?')}."
            )

    lat, lon = _coordinates(best)

    matched = best.get("formatted", "")
    kind = ""

    if best.get("result_type") in AREA_LEVEL_RESULT_TYPES:
        matched = f"AREA ONLY, confirm the exact spot. {matched}"
        kind = "area"

    return lat, lon, matched, kind


def _road_distance_m(lat, lon, api_key, pickup_lat, pickup_lng):
    """Driving distance in metres from the pickup point to (lat, lon)."""

    data = _get_json(
        ROUTING_URL,
        {
            # Geoapify wants latitude first here.
            "waypoints": f"{pickup_lat},{pickup_lng}|{lat},{lon}",
            "mode": "drive",
            "apiKey": api_key,
        },
    )

    try:
        distance = float(data["features"][0]["properties"]["distance"])
    except (KeyError, IndexError, TypeError, ValueError):
        raise _ServiceProblem("No driving route could be found.") from None

    if distance < 0:
        raise _ServiceProblem("The map service sent an impossible distance.")

    return int(round(distance))


def _calculate(resolve):
    """
    Shared by every way of locating a customer. `resolve` is given the key and
    the pickup point and returns (lat, lon, what-we-matched-it-to, kind), or
    raises _AddressProblem / _ServiceProblem. Never raises.
    """

    api_key = getattr(settings, "GEOAPIFY_API_KEY", "")

    if not api_key:
        logger.warning("GEOAPIFY_API_KEY is not set: delivery fees need a phone call.")
        return DeliveryResult(
            status=UNVERIFIED,
            note="Delivery lookup is not switched on (no API key).",
            problem="service",
        )

    pickup_lat = float(getattr(settings, "DELIVERY_PICKUP_LAT", DEFAULT_PICKUP_LAT))
    pickup_lng = float(getattr(settings, "DELIVERY_PICKUP_LNG", DEFAULT_PICKUP_LNG))

    try:
        lat, lon, matched, kind = resolve(api_key, pickup_lat, pickup_lng)
        distance_m = _road_distance_m(lat, lon, api_key, pickup_lat, pickup_lng)

    except _AddressProblem as exc:
        return DeliveryResult(status=UNVERIFIED, note=str(exc)[:255], problem="address")

    except _ServiceProblem as exc:
        return DeliveryResult(status=UNVERIFIED, note=str(exc)[:255], problem="service")

    except Exception as exc:  # last resort: checkout must never crash on this
        # Type only: an exception's text can contain the URL, and the URL
        # contains the key.
        logger.error("Unexpected delivery lookup error: %s", type(exc).__name__)
        return DeliveryResult(
            status=UNVERIFIED,
            note="Unexpected error while checking the address.",
            problem="service",
        )

    fee = fee_for_distance(distance_m)
    km = round(distance_m / 1000, 1)
    note = f"{km} km by road. Matched to: {matched}"[:255]

    if kind == "town" and fee == ZERO:
        # The middle of a town cannot justify free delivery. (This is also
        # what stops "Kampala" on its own from being free.)
        return DeliveryResult(
            status=UNVERIFIED,
            note=(
                "Only a town was named and its centre is too close to price "
                f"reliably: {matched}"
            )[:255],
            problem="address",
        )

    approximate = kind != ""

    if fee is None:
        return DeliveryResult(
            status=QUOTE_REQUIRED, distance_m=distance_m, note=note,
            approximate=approximate,
        )

    return DeliveryResult(
        status=CALCULATED, fee=fee, distance_m=distance_m, note=note,
        approximate=approximate,
    )


def calculate_delivery(address, city):
    """
    Work out the delivery fee for a typed address. Never raises.

    CALCULATED      -> `fee` is the price to charge.
    QUOTE_REQUIRED  -> beyond the last price band: no fee is applied, we
                       phone the customer.
    UNVERIFIED      -> could not be checked (see `problem`): no fee is
                       applied, we phone the customer.
    """

    return _calculate(
        lambda key, plat, plng: _geocode(address, city, key, plat, plng)
    )


# ---------------------------------------------------------------------------
# The quote the customer has been shown
# ---------------------------------------------------------------------------
# Checkout works in two presses of one button. The first press works out the
# fee and SHOWS it; the second places the order. The fee shown is remembered
# here, in the server-side session (the browser only holds an opaque id, so
# the customer cannot edit it), and the order is only ever placed with a quote
# that is still valid for exactly the same address and the same basket.

QUOTE_SESSION_KEY = "delivery_quote"
QUOTE_MAX_AGE_SECONDS = 30 * 60

_VALID_STATUSES = {CALCULATED, QUOTE_REQUIRED, UNVERIFIED}


def _same_text(text):
    """Ignore extra spaces, line breaks and capital letters when comparing."""
    return " ".join((text or "").split()).casefold()


def save_quote(session, address, city, subtotal, result, place_key=""):
    session[QUOTE_SESSION_KEY] = {
        "address": _same_text(address),
        "city": _same_text(city),
        "place": place_key,
        "subtotal": str(subtotal),
        "status": result.status,
        "fee": str(result.fee),
        "distance_m": result.distance_m,
        "note": result.note,
        "problem": result.problem,
        "approximate": result.approximate,
        "at": time.time(),
    }
    session.modified = True


def clear_quote(session):
    if QUOTE_SESSION_KEY in session:
        del session[QUOTE_SESSION_KEY]
        session.modified = True


def load_quote(session, address, city, subtotal, place_key=""):
    """
    The saved quote, but only if it is recent AND was made for exactly this
    address and this basket total. Anything else (a changed address, a changed
    basket, an old quote, damaged data) returns None and a fresh one is made.
    """

    data = session.get(QUOTE_SESSION_KEY)

    if not isinstance(data, dict):
        return None

    try:
        age = time.time() - float(data["at"])

        if age < 0 or age > QUOTE_MAX_AGE_SECONDS:
            return None

        if data["address"] != _same_text(address) or data["city"] != _same_text(city):
            return None

        # A quote made from a picked suggestion is not reused for typed text
        # (or for a different pick), and the other way round.
        if data.get("place", "") != place_key:
            return None

        if Decimal(data["subtotal"]) != Decimal(subtotal):
            return None

        status = data["status"]

        if status not in _VALID_STATUSES:
            return None

        fee = Decimal(data["fee"])

        # Only a calculated quote carries a fee, and never a negative one.
        if status != CALCULATED:
            fee = ZERO

        if fee < 0:
            return None

        distance = data["distance_m"]

        return DeliveryResult(
            status=status,
            fee=fee,
            distance_m=int(distance) if distance is not None else None,
            note=str(data["note"])[:255],
            problem=str(data["problem"]),
            approximate=bool(data.get("approximate", False)),
        )

    except (KeyError, TypeError, ValueError, InvalidOperation):
        return None


def customer_message(result):
    """What to tell the customer about their delivery, in plain words."""

    km = result.distance_km

    if result.status == CALCULATED:
        if result.fee == 0:
            text = f"Good news: delivery to you is free ({km} km from our pickup point)."
        else:
            text = f"Delivery to you is {km} km by road."

        if result.approximate:
            text += (
                " This is worked out from the centre of the area you entered. "
                "We will confirm your exact location by phone."
            )

        return text

    if result.status == QUOTE_REQUIRED:
        return (
            f"You are {km} km from our pickup point by road, so we will call you "
            "to agree a delivery fee once you place your order. It is not "
            "included in the total below."
        )

    if result.problem == "address":
        return (
            "We could not find that exact spot on the map. You can still place "
            "your order and we will call you to confirm delivery and its fee, "
            "or add a nearby landmark or area to your address and check again. "
            "The fee is not included in the total below."
        )

    return (
        "We could not work out your delivery fee just now. You can still place "
        "your order and we will call you to confirm it. The fee is not "
        "included in the total below."
    )


# ---------------------------------------------------------------------------
# Suggestions while the customer types
# ---------------------------------------------------------------------------
# The browser never talks to Geoapify and never sees the key: it asks OUR
# server (see views.address_suggestions), which asks Geoapify. Each suggestion
# comes back with a signed token that locks in its exact map position. At
# checkout the server trusts a position ONLY if its signature is valid, so a
# customer cannot pair a nearby position with a faraway address.

SUGGEST_MIN_CHARS = 3
SUGGEST_MAX_CHARS = 100
SUGGEST_LIMIT = 5          # how many are shown to the customer

# We ask for more than we show, then keep only the places within reach of
# Greater Kampala. A name like "Kyanja" exists in several far-off districts,
# and those must not push the Kampala one out of the list. (Orders beyond the
# fixed-price distance are a phone quote anyway.)
SUGGEST_FETCH = 10
SUGGEST_RADIUS_M = 60_000

PLACE_TOKEN_SALT = "bags-delivery-place"
PLACE_TOKEN_MAX_AGE = 6 * 60 * 60

# Not offered as a choice: a whole country, region, district or postcode area.
# (A TOWN is offered: customers do name towns, see TOWN_MIN_CONFIDENCE.)
NOT_SUGGESTED_RESULT_TYPES = TOO_GENERAL_RESULT_TYPES - {"city"}


@dataclass
class Place:
    """A position the customer picked from the suggestions."""

    lat: float
    lon: float
    label: str
    result_type: str = ""

    @property
    def key(self):
        return f"{self.lat:.5f},{self.lon:.5f}"


def suggest_places(text):
    """
    Up to five places in Uganda that match what the customer has typed so far,
    nearest to our pickup point first. Each is {"label", "token", "city"}.
    Never raises: on any problem the answer is simply "no suggestions", and
    the customer can still type a full address as before.
    """

    text = " ".join((text or "").split())[:SUGGEST_MAX_CHARS]

    # Spaces do not count: "k y" is two letters, not three.
    if len(text.replace(" ", "")) < SUGGEST_MIN_CHARS:
        return []

    api_key = getattr(settings, "GEOAPIFY_API_KEY", "")

    if not api_key:
        return []

    pickup_lat = float(getattr(settings, "DELIVERY_PICKUP_LAT", DEFAULT_PICKUP_LAT))
    pickup_lng = float(getattr(settings, "DELIVERY_PICKUP_LNG", DEFAULT_PICKUP_LNG))

    try:
        data = _get_json(
            AUTOCOMPLETE_URL,
            {
                "text": text,
                "filter": "countrycode:ug",
                "bias": f"proximity:{pickup_lng},{pickup_lat}",
                "limit": SUGGEST_FETCH,
                "format": "json",
                "lang": "en",
                "apiKey": api_key,
            },
        )
    except _ServiceProblem:
        return []
    except Exception as exc:
        logger.error("Unexpected suggestion error: %s", type(exc).__name__)
        return []

    suggestions = []
    seen = set()

    for result in data.get("results") or []:

        if not isinstance(result, dict):
            continue

        coords = _coordinates(result)
        label = str(result.get("formatted") or "").strip()[:255]
        kind = str(result.get("result_type") or "")

        if not coords or not label or kind in NOT_SUGGESTED_RESULT_TYPES:
            continue

        if label.casefold() in seen:
            continue

        seen.add(label.casefold())

        # a place with the same name, but far from Greater Kampala
        if _straight_line_m(pickup_lat, pickup_lng, coords[0], coords[1]) > SUGGEST_RADIUS_M:
            continue

        if len(suggestions) >= SUGGEST_LIMIT:
            break

        suggestions.append(
            {
                "label": label,
                "city": str(result.get("city") or result.get("county") or "")[:100],
                "token": signing.dumps(
                    {
                        "lat": round(coords[0], 6),
                        "lon": round(coords[1], 6),
                        "label": label,
                        "type": kind,
                    },
                    salt=PLACE_TOKEN_SALT,
                ),
            }
        )

    return suggestions


def verify_place_token(token, address):
    """
    The picked place, but ONLY if the token is genuine, recent, and the address
    the customer is submitting still starts with the place they picked (they
    may add a flat or building number after it). Otherwise None, and the
    typed text is looked up as usual.
    """

    if not token or not isinstance(token, str):
        return None

    try:
        data = signing.loads(token, salt=PLACE_TOKEN_SALT, max_age=PLACE_TOKEN_MAX_AGE)
        place = Place(
            lat=float(data["lat"]),
            lon=float(data["lon"]),
            label=str(data["label"]),
            result_type=str(data["type"]),
        )
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        return None   # includes tampered, expired and malformed tokens

    if not (-90 <= place.lat <= 90 and -180 <= place.lon <= 180):
        return None

    if not place.label or not _same_text(address).startswith(_same_text(place.label)):
        return None

    return place


def calculate_delivery_for_place(place):
    """The fee for a place the customer picked from the suggestions. Never raises."""

    def resolve(api_key, pickup_lat, pickup_lng):

        if place.result_type in NOT_SUGGESTED_RESULT_TYPES:
            raise _AddressProblem(
                f"Address only matched to a general area: {place.label}."
            )

        if place.result_type == "city":
            return (
                place.lat, place.lon,
                f"TOWN CENTRE ONLY, confirm the exact spot. {place.label}",
                "town",
            )

        if place.result_type in AREA_LEVEL_RESULT_TYPES:
            return (
                place.lat, place.lon,
                f"AREA ONLY, confirm the exact spot. {place.label}",
                "area",
            )

        return place.lat, place.lon, place.label, ""

    return _calculate(resolve)
