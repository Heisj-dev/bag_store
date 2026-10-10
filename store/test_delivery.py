"""
Tests for store/delivery.py and the new Order delivery fields.

No test here talks to Geoapify: requests.get is replaced with a fake, so the
tests are free, fast, and can reproduce failures on demand.

Run:  python manage.py test store.test_delivery
"""

import logging
import time
from decimal import Decimal
from unittest import mock

import requests
from django.contrib.auth.models import User
from django.core import signing
from django.test import SimpleTestCase, TestCase, override_settings

from . import delivery
from .delivery import DeliveryResult
from .models import Order

FAKE_KEY = "super-secret-test-key"


class FakeResponse:
    def __init__(self, payload=None, status_code=200, bad_json=False):
        self._payload = payload
        self.status_code = status_code
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


def geocode_payload(*places):
    """places: (lat, lon, formatted, confidence[, result_type])"""
    results = []
    for place in places:
        lat, lon, name, conf = place[:4]
        result = {"lat": lat, "lon": lon, "formatted": name, "rank": {"confidence": conf}}
        if len(place) > 4:
            result["result_type"] = place[4]
        results.append(result)
    return {"results": results}


def route_payload(distance_m):
    return {"features": [{"properties": {"distance": distance_m, "time": 600}}]}


def fake_get(geocode=None, route=None):
    """A stand-in for requests.get that answers by URL."""

    def _get(url, params=None, timeout=None):
        assert timeout, "every call must have a timeout"
        wanted = geocode if url == delivery.GEOCODE_URL else route
        if isinstance(wanted, Exception):
            raise wanted
        return wanted

    return _get


KOSOVO = (0.2850, 32.5900, "Kosovo, Makindye, Kampala, Uganda", 0.95)


@override_settings(GEOAPIFY_API_KEY=FAKE_KEY)
class PriceListTests(SimpleTestCase):
    """The agreed prices, including the exact edges."""

    def test_fee_for_distance(self):
        cases = [
            (0, 0),
            (4_999, 0),
            (5_000, 0),        # exactly 5 km is still free
            (5_001, 3000),
            (10_000, 3000),    # exactly 10 km is still 3,000
            (10_001, 5000),
            (15_000, 5000),
            (15_001, 5000),    # 15 to 18 km is also 5,000
            (18_000, 5000),    # exactly 18 km is still 5,000
        ]
        for metres, fee in cases:
            with self.subTest(metres=metres):
                self.assertEqual(delivery.fee_for_distance(metres), Decimal(fee))

    def test_over_18km_has_no_fee(self):
        self.assertIsNone(delivery.fee_for_distance(18_001))
        self.assertIsNone(delivery.fee_for_distance(40_000))

    def test_the_limit_comes_from_the_price_list(self):
        self.assertEqual(delivery.FIXED_FEE_LIMIT_M, 18_000)


@override_settings(GEOAPIFY_API_KEY=FAKE_KEY)
class CalculateDeliveryTests(SimpleTestCase):

    def run_calc(self, geocode, route=None, address="Plot 4 Some Road", city="Makindye"):
        with mock.patch(
            "store.delivery.requests.get", side_effect=fake_get(geocode, route)
        ):
            return delivery.calculate_delivery(address, city)

    # ---- the three outcomes that matter to the customer ----

    def test_kosovo_example_is_3000(self):
        # Your playground test: Kosovo, Makindye = 8,851 m.
        result = self.run_calc(
            FakeResponse(geocode_payload(KOSOVO)), FakeResponse(route_payload(8851))
        )
        self.assertEqual(result.status, delivery.CALCULATED)
        self.assertEqual(result.fee, Decimal("3000"))
        self.assertEqual(result.distance_m, 8851)
        self.assertEqual(result.distance_km, 8.9)
        self.assertIn("Kosovo", result.note)

    def test_close_address_is_free(self):
        result = self.run_calc(
            FakeResponse(geocode_payload(KOSOVO)), FakeResponse(route_payload(2300))
        )
        self.assertEqual(result.status, delivery.CALCULATED)
        self.assertEqual(result.fee, Decimal("0"))

    def test_kira_example_is_now_a_fixed_5000(self):
        # Your playground test: Kira = 15,644 m. With the 18 km limit this is
        # no longer a quote: it is in the UGX 5,000 band.
        result = self.run_calc(
            FakeResponse(geocode_payload(KOSOVO)), FakeResponse(route_payload(15644))
        )
        self.assertEqual(result.status, delivery.CALCULATED)
        self.assertEqual(result.fee, Decimal("5000"))
        self.assertEqual(result.distance_m, 15644)

    def test_beyond_18km_needs_a_quote_and_charges_nothing(self):
        result = self.run_calc(
            FakeResponse(geocode_payload(KOSOVO)), FakeResponse(route_payload(19200))
        )
        self.assertEqual(result.status, delivery.QUOTE_REQUIRED)
        self.assertEqual(result.fee, Decimal("0"))
        self.assertEqual(result.distance_m, 19200)
        self.assertFalse(result.fee_is_final)

    def test_exactly_18km_is_still_priced(self):
        result = self.run_calc(
            FakeResponse(geocode_payload(KOSOVO)), FakeResponse(route_payload(18000))
        )
        self.assertEqual(result.status, delivery.CALCULATED)
        self.assertEqual(result.fee, Decimal("5000"))

    def test_one_metre_past_18km_needs_a_quote(self):
        result = self.run_calc(
            FakeResponse(geocode_payload(KOSOVO)), FakeResponse(route_payload(18001))
        )
        self.assertEqual(result.status, delivery.QUOTE_REQUIRED)

    # ---- addresses we cannot trust ----

    def test_address_not_found(self):
        result = self.run_calc(FakeResponse({"results": []}))
        self.assertEqual(result.status, delivery.UNVERIFIED)
        self.assertEqual(result.problem, "address")
        self.assertEqual(result.fee, Decimal("0"))
        self.assertIsNone(result.distance_m)

    def test_low_confidence_match_is_not_trusted(self):
        weak = (0.3, 32.6, "Some Village, Uganda", 0.2)
        result = self.run_calc(FakeResponse(geocode_payload(weak)))
        self.assertEqual(result.status, delivery.UNVERIFIED)
        self.assertEqual(result.problem, "address")

    def test_same_words_two_far_apart_places_is_ambiguous(self):
        a = (0.3500, 32.6000, "Kira Road, Kampala", 0.8)
        b = (0.4500, 32.9000, "Kira Town, Wakiso", 0.78)   # ~35 km away
        result = self.run_calc(FakeResponse(geocode_payload(a, b)))
        self.assertEqual(result.status, delivery.UNVERIFIED)
        self.assertEqual(result.problem, "address")
        self.assertIn("more than one place", result.note)

    def test_two_close_matches_are_not_ambiguous(self):
        a = (0.3500, 32.6000, "Ntinda, Kampala", 0.9)
        b = (0.3510, 32.6010, "Ntinda Road, Kampala", 0.88)  # ~150 m away
        result = self.run_calc(
            FakeResponse(geocode_payload(a, b)), FakeResponse(route_payload(7000))
        )
        self.assertEqual(result.status, delivery.CALCULATED)

    def test_clear_winner_beats_a_far_runner_up(self):
        a = (0.3500, 32.6000, "Ntinda, Kampala", 0.95)
        b = (0.4500, 32.9000, "Ntinda, Elsewhere", 0.50)
        result = self.run_calc(
            FakeResponse(geocode_payload(a, b)), FakeResponse(route_payload(7000))
        )
        self.assertEqual(result.status, delivery.CALCULATED)

    # ---- matches that are too vague to price ----

    def test_nonsense_address_matched_to_the_whole_city_is_not_free(self):
        # Real case: "kizungu near latitude 0" came back as just "Kampala",
        # 1.7 km from the pickup point, and got free delivery.
        city_only = (0.3476, 32.5825, "Kampala, KM, Uganda", 0.9, "city")
        result = self.run_calc(
            FakeResponse(geocode_payload(city_only)), FakeResponse(route_payload(1724))
        )
        self.assertEqual(result.status, delivery.UNVERIFIED)
        self.assertEqual(result.problem, "address")
        self.assertEqual(result.fee, Decimal("0"))
        self.assertIsNone(result.distance_m)
        self.assertIn("general area", result.note)

    def test_every_too_general_type_is_refused(self):
        for kind in ("country", "state", "county", "city", "postcode"):
            with self.subTest(kind=kind):
                place = (0.3476, 32.5825, "Somewhere", 0.95, kind)
                result = self.run_calc(
                    FakeResponse(geocode_payload(place)),
                    FakeResponse(route_payload(1000)),
                )
                self.assertEqual(result.status, delivery.UNVERIFIED)

    def test_specific_types_are_accepted(self):
        for kind in ("street", "building", "amenity"):
            with self.subTest(kind=kind):
                place = (0.3500, 32.6000, "Ntinda Road, Kampala", 0.9, kind)
                result = self.run_calc(
                    FakeResponse(geocode_payload(place)),
                    FakeResponse(route_payload(7000)),
                )
                self.assertEqual(result.status, delivery.CALCULATED)
                self.assertNotIn("AREA ONLY", result.note)

    def test_suburb_match_is_priced_but_flagged_as_approximate(self):
        place = (0.3500, 32.6000, "Kyanja, Kampala, Uganda", 0.9, "suburb")
        result = self.run_calc(
            FakeResponse(geocode_payload(place)), FakeResponse(route_payload(11000))
        )
        self.assertEqual(result.status, delivery.CALCULATED)
        self.assertEqual(result.fee, Decimal("5000"))
        self.assertIn("AREA ONLY", result.note)
        self.assertTrue(result.approximate)

    # ---- the map service misbehaving ----

    def test_timeout_never_crashes_and_never_charges(self):
        result = self.run_calc(requests.Timeout("slow"))
        self.assertEqual(result.status, delivery.UNVERIFIED)
        self.assertEqual(result.problem, "service")
        self.assertEqual(result.fee, Decimal("0"))

    def test_routing_timeout(self):
        result = self.run_calc(
            FakeResponse(geocode_payload(KOSOVO)), requests.Timeout("slow")
        )
        self.assertEqual(result.status, delivery.UNVERIFIED)
        self.assertEqual(result.problem, "service")

    def test_network_failure(self):
        result = self.run_calc(requests.ConnectionError("down"))
        self.assertEqual(result.status, delivery.UNVERIFIED)
        self.assertEqual(result.problem, "service")

    def test_bad_key_or_server_error(self):
        for code in (401, 403, 429, 500, 503):
            with self.subTest(code=code):
                result = self.run_calc(FakeResponse({}, status_code=code))
                self.assertEqual(result.status, delivery.UNVERIFIED)
                self.assertEqual(result.problem, "service")
                self.assertIn(str(code), result.note)

    def test_unreadable_answer(self):
        result = self.run_calc(FakeResponse(bad_json=True))
        self.assertEqual(result.status, delivery.UNVERIFIED)

    def test_no_route_found(self):
        result = self.run_calc(
            FakeResponse(geocode_payload(KOSOVO)), FakeResponse({"features": []})
        )
        self.assertEqual(result.status, delivery.UNVERIFIED)
        self.assertEqual(result.problem, "service")

    def test_garbage_in_the_answer_never_crashes(self):
        for junk in ([], "text", None, {"results": "oops"}, {"results": [{"x": 1}]}):
            with self.subTest(junk=junk):
                result = self.run_calc(FakeResponse(junk))
                self.assertEqual(result.status, delivery.UNVERIFIED)

    def test_unexpected_exception_is_contained(self):
        result = self.run_calc(RuntimeError("boom"))
        self.assertEqual(result.status, delivery.UNVERIFIED)
        self.assertEqual(result.problem, "service")

    # ---- the key ----

    @override_settings(GEOAPIFY_API_KEY="")
    def test_no_key_means_phone_confirmation_not_a_crash(self):
        with mock.patch("store.delivery.requests.get") as get:
            result = delivery.calculate_delivery("Anywhere", "Kampala")
        get.assert_not_called()
        self.assertEqual(result.status, delivery.UNVERIFIED)

    def test_key_never_appears_in_logs_or_notes(self):
        # requests puts the full URL, key included, in its error messages.
        leaky = requests.ConnectionError(
            f"HTTPSConnectionPool: url: /v1/geocode/search?apiKey={FAKE_KEY}"
        )
        with self.assertLogs("store.delivery", level=logging.DEBUG) as logs:
            result = self.run_calc(leaky)

        self.assertNotIn(FAKE_KEY, "\n".join(logs.output))
        self.assertNotIn(FAKE_KEY, result.note)

        leaky_unexpected = RuntimeError(f"apiKey={FAKE_KEY}")
        with self.assertLogs("store.delivery", level=logging.DEBUG) as logs:
            result = self.run_calc(leaky_unexpected)

        self.assertNotIn(FAKE_KEY, "\n".join(logs.output))
        self.assertNotIn(FAKE_KEY, result.note)

    def test_key_is_only_sent_as_a_query_parameter_to_geoapify(self):
        calls = []

        def spy(url, params=None, timeout=None):
            calls.append((url, dict(params), timeout))
            if url == delivery.GEOCODE_URL:
                return FakeResponse(geocode_payload(KOSOVO))
            return FakeResponse(route_payload(5000))

        with mock.patch("store.delivery.requests.get", side_effect=spy):
            delivery.calculate_delivery("Plot 4", "Makindye")

        self.assertEqual(len(calls), 2)
        for url, params, timeout in calls:
            self.assertTrue(url.startswith("https://api.geoapify.com/"))
            self.assertEqual(params["apiKey"], FAKE_KEY)
            self.assertNotIn(FAKE_KEY, url)
            self.assertIsNotNone(timeout)

        # Pickup point first, customer second, latitude before longitude.
        waypoints = calls[1][1]["waypoints"]
        self.assertTrue(waypoints.startswith("0.3153404,32.5749709|"))

    def test_very_long_address_is_cut_down(self):
        seen = {}

        def spy(url, params=None, timeout=None):
            seen.setdefault("text", params.get("text"))
            return FakeResponse({"results": []})

        with mock.patch("store.delivery.requests.get", side_effect=spy):
            delivery.calculate_delivery("x" * 5000, "Kampala")

        self.assertLessEqual(len(seen["text"]), delivery.MAX_QUERY_LENGTH)


KIRA = (0.3980, 32.6411, "Kira, Wakiso, Uganda", 1.0, "city")
KAMPALA = (0.3476, 32.5825, "Kampala, KM, Uganda", 1.0, "city")
MUKONO = (0.3533, 32.7553, "Mukono, Uganda", 1.0, "city")


@override_settings(GEOAPIFY_API_KEY=FAKE_KEY)
class NamedTownTests(SimpleTestCase):
    """
    A town is trusted only when the customer's own address text IS that
    town's name. Real results: "Kira, Wakiso" comes back as a city with
    confidence 1.0, and nonsense text falls back to the city "Kampala".
    """

    def run_calc(self, places, metres, address, city, spy=None):
        def _get(url, params=None, timeout=None):
            if spy is not None:
                spy.append((url, dict(params)))
            if url == delivery.GEOCODE_URL:
                return FakeResponse(geocode_payload(*places))
            return FakeResponse(route_payload(metres))

        with mock.patch("store.delivery.requests.get", side_effect=_get):
            return delivery.calculate_delivery(address, city)

    def test_a_named_town_is_priced_from_its_centre(self):
        result = self.run_calc([KIRA], 15644, "Kira", "Wakiso")

        self.assertEqual(result.status, delivery.CALCULATED)
        self.assertEqual(result.fee, Decimal("5000"))
        self.assertEqual(result.distance_m, 15644)
        self.assertTrue(result.approximate)
        self.assertIn("TOWN CENTRE ONLY", result.note)
        self.assertIn("Kira, Wakiso", result.note)

    def test_the_town_beats_a_feature_that_ranks_higher(self):
        hospital = (0.3000, 32.5000, "Kira Hospital, Elsewhere, Uganda", 0.95, "amenity")
        calls = []

        result = self.run_calc([hospital, KIRA], 15644, "Kira", "Wakiso", spy=calls)

        self.assertEqual(result.status, delivery.CALCULATED)
        self.assertIn("TOWN CENTRE ONLY", result.note)

        # the route went to the TOWN, not to the hospital
        route_call = [params for url, params in calls if url == delivery.ROUTING_URL][0]
        self.assertTrue(route_call["waypoints"].endswith("|0.398,32.6411"))

    def test_typing_more_than_the_town_name_allows_a_specific_place(self):
        hospital = (0.4000, 32.6200, "Kira Hospital, Kira, Wakiso, Uganda", 0.9, "amenity")
        calls = []

        result = self.run_calc([hospital, KIRA], 14000, "Kira Hospital", "Wakiso", spy=calls)

        self.assertEqual(result.status, delivery.CALCULATED)
        self.assertNotIn("TOWN", result.note)
        self.assertFalse(result.approximate)
        route_call = [params for url, params in calls if url == delivery.ROUTING_URL][0]
        self.assertTrue(route_call["waypoints"].endswith("|0.4,32.62"))

    def test_kampala_on_its_own_is_never_free(self):
        # The middle of Kampala is next to our pickup point.
        result = self.run_calc([KAMPALA], 1724, "Kampala", "Kampala")

        self.assertEqual(result.status, delivery.UNVERIFIED)
        self.assertEqual(result.problem, "address")
        self.assertEqual(result.fee, Decimal("0"))
        self.assertIsNone(result.distance_m)
        self.assertIn("too close", result.note)

    def test_a_town_that_is_only_in_the_city_field_is_not_the_address(self):
        # Real case: "kizungu near latitude 0" + city "Kampala" fell back to
        # the city "Kampala" and used to get free delivery.
        for address in ("kizungu near latitude 0", "", "   ", "town", "!!!"):
            with self.subTest(address=address):
                result = self.run_calc([KAMPALA], 1724, address, "Kampala")
                self.assertEqual(result.status, delivery.UNVERIFIED)
                self.assertEqual(result.problem, "address")
                self.assertEqual(result.fee, Decimal("0"))

    def test_a_town_needs_the_map_to_be_sure(self):
        unsure = (0.3980, 32.6411, "Kira, Wakiso, Uganda", 0.6, "city")
        result = self.run_calc([unsure], 15644, "Kira", "Wakiso")
        self.assertEqual(result.status, delivery.UNVERIFIED)
        self.assertIn("general area", result.note)

    def test_only_a_city_type_match_counts_as_a_town(self):
        # A district/county with the same name is far too big to price from.
        county = (0.4044, 32.4594, "Wakiso, Uganda", 1.0, "county")
        result = self.run_calc([county], 15000, "Wakiso", "Wakiso")
        self.assertEqual(result.status, delivery.UNVERIFIED)

    def test_a_town_beyond_the_fixed_price_limit_is_a_quote(self):
        result = self.run_calc([MUKONO], 23400, "Mukono", "Mukono")

        self.assertEqual(result.status, delivery.QUOTE_REQUIRED)
        self.assertEqual(result.fee, Decimal("0"))
        self.assertEqual(result.distance_m, 23400)
        self.assertTrue(result.approximate)

    def test_extra_words_capitals_and_punctuation_do_not_matter(self):
        for address, city in (
            ("Kira Town, Wakiso", "Wakiso"),   # "town" and the city field are ignored
            ("  KIRA, ", "Wakiso"),
            ("kira", "Kampala"),
            ("Kira", "Kira"),                  # same word in both boxes
        ):
            with self.subTest(address=address, city=city):
                result = self.run_calc([KIRA], 15644, address, city)
                self.assertEqual(result.status, delivery.CALCULATED)
                self.assertIn("TOWN CENTRE ONLY", result.note)

    def test_a_different_place_is_not_mistaken_for_the_town(self):
        # Customer typed Mbarara; the map offered only Kira.
        result = self.run_calc([KIRA], 15644, "Mbarara", "Wakiso")
        self.assertEqual(result.status, delivery.UNVERIFIED)

    def test_a_named_suburb_is_still_an_area_match(self):
        suburb = (0.3900, 32.6100, "Kyanja, Kampala, Uganda", 0.9, "suburb")
        result = self.run_calc([suburb], 11000, "Kyanja", "Kampala")

        self.assertEqual(result.status, delivery.CALCULATED)
        self.assertEqual(result.fee, Decimal("5000"))
        self.assertIn("AREA ONLY", result.note)
        self.assertTrue(result.approximate)


class CustomerMessageTests(SimpleTestCase):

    def test_an_area_based_fee_says_the_location_will_be_confirmed(self):
        approx = DeliveryResult(
            status=delivery.CALCULATED, fee=Decimal("5000"), distance_m=15644,
            approximate=True,
        )
        exact = DeliveryResult(
            status=delivery.CALCULATED, fee=Decimal("5000"), distance_m=15644,
        )
        self.assertIn("confirm your exact location", delivery.customer_message(approx))
        self.assertNotIn("confirm your exact location", delivery.customer_message(exact))

    def test_the_approximate_flag_survives_the_saved_quote(self):
        class Session(dict):
            modified = False

        session = Session()
        result = DeliveryResult(
            status=delivery.CALCULATED, fee=Decimal("5000"), distance_m=15644,
            note="n", approximate=True,
        )
        delivery.save_quote(session, "Kira", "Wakiso", Decimal("100"), result)
        loaded = delivery.load_quote(session, "kira", "wakiso", Decimal("100"))

        self.assertTrue(loaded.approximate)

        # a quote saved before this flag existed still loads, as not approximate
        del session["delivery_quote"]["approximate"]
        self.assertFalse(delivery.load_quote(session, "kira", "wakiso", Decimal("100")).approximate)


class OrderFieldsTests(TestCase):
    """Orders placed before delivery fees existed must not change."""

    def make_order(self, **extra):
        user, _ = User.objects.get_or_create(
            username="buyer", defaults={"email": "b@example.com"}
        )
        return Order.objects.create(
            user=user,
            order_number="TEST00000001",
            email="b@example.com",
            full_name="Buyer",
            phone="0700000000",
            address="Somewhere",
            city="Kampala",
            **extra,
        )

    def test_an_old_style_order_keeps_its_total(self):
        order = self.make_order(total=Decimal("150000"))
        order.refresh_from_db()

        self.assertEqual(order.total, Decimal("150000"))
        self.assertIsNone(order.subtotal)
        self.assertEqual(order.delivery_fee, Decimal("0"))
        self.assertEqual(order.delivery_status, "NOT_CALCULATED")
        self.assertIsNone(order.delivery_distance_km)
        self.assertFalse(order.delivery_fee_pending)
        # Templates and emails can use products_total for old AND new orders.
        self.assertEqual(order.products_total, Decimal("150000"))

    def test_a_new_style_order(self):
        order = self.make_order(
            subtotal=Decimal("150000"),
            delivery_fee=Decimal("3000"),
            total=Decimal("153000"),
            delivery_distance_m=8851,
            delivery_status="CALCULATED",
        )
        self.assertEqual(order.products_total, Decimal("150000"))
        self.assertEqual(order.delivery_distance_km, 8.9)
        self.assertEqual(order.subtotal + order.delivery_fee, order.total)

    def test_quote_orders_are_flagged_as_pending(self):
        for status in ("QUOTE_REQUIRED", "UNVERIFIED"):
            with self.subTest(status=status):
                order = self.make_order(
                    total=Decimal("150000"), delivery_status=status
                )
                self.assertTrue(order.delivery_fee_pending)
                order.delete()


def autocomplete_payload(*places):
    """places: (lat, lon, formatted, result_type[, city])"""
    results = []
    for place in places:
        lat, lon, name, kind = place[:4]
        result = {"lat": lat, "lon": lon, "formatted": name, "result_type": kind}
        if len(place) > 4:
            result["city"] = place[4]
        results.append(result)
    return {"results": results}


STREET = (0.3500, 32.6000, "Ntinda Road, Kampala, Uganda", "street", "Kampala")
KYANJA_SUBURB = (0.3900, 32.6100, "Kyanja, Kampala, Uganda", "suburb", "Kampala")
KIRA_TOWN = (0.3980, 32.6411, "Kira, Wakiso, Uganda", "city", "Wakiso")


@override_settings(GEOAPIFY_API_KEY=FAKE_KEY)
class SuggestionTests(SimpleTestCase):

    def suggest(self, payload, text="kyanja", status=200):
        with mock.patch(
            "store.delivery.requests.get",
            return_value=FakeResponse(payload, status_code=status),
        ):
            return delivery.suggest_places(text)

    def test_returns_label_token_and_city(self):
        found = self.suggest(autocomplete_payload(STREET, KYANJA_SUBURB))

        self.assertEqual([s["label"] for s in found],
                         ["Ntinda Road, Kampala, Uganda", "Kyanja, Kampala, Uganda"])
        self.assertEqual(found[0]["city"], "Kampala")
        self.assertTrue(all(s["token"] for s in found))

    def test_only_our_own_server_side_call_carries_the_key_and_it_is_aimed_at_uganda(self):
        calls = []

        def spy(url, params=None, timeout=None):
            calls.append((url, dict(params), timeout))
            return FakeResponse(autocomplete_payload(STREET))

        with mock.patch("store.delivery.requests.get", side_effect=spy):
            found = delivery.suggest_places("  Ntinda   Road ")

        url, params, timeout = calls[0]
        self.assertEqual(url, delivery.AUTOCOMPLETE_URL)
        self.assertEqual(params["text"], "Ntinda Road")
        self.assertEqual(params["filter"], "countrycode:ug")
        self.assertEqual(params["bias"], "proximity:32.5749709,0.3153404")
        self.assertEqual(params["limit"], delivery.SUGGEST_FETCH)   # ask for more than is shown
        self.assertEqual(params["apiKey"], FAKE_KEY)
        self.assertIsNotNone(timeout)

        # the key never reaches the customer's browser
        self.assertNotIn(FAKE_KEY, repr(found))

    def test_short_text_makes_no_request(self):
        with mock.patch("store.delivery.requests.get") as get:
            for text in ("", "  ", "ky", "k y"):
                self.assertEqual(delivery.suggest_places(text), [])
            self.assertEqual(delivery.suggest_places(None), [])
        get.assert_not_called()

    @override_settings(GEOAPIFY_API_KEY="")
    def test_no_key_means_no_suggestions_and_no_request(self):
        with mock.patch("store.delivery.requests.get") as get:
            self.assertEqual(delivery.suggest_places("kyanja"), [])
        get.assert_not_called()

    def test_whole_regions_are_not_offered_but_towns_are(self):
        found = self.suggest(autocomplete_payload(
            (0.1, 32.1, "Uganda", "country"),
            (0.2, 32.2, "Central Region, Uganda", "state"),
            (0.4, 32.4, "Wakiso District, Uganda", "county"),
            (0.5, 32.5, "00256, Uganda", "postcode"),
            KIRA_TOWN,
        ))
        self.assertEqual([s["label"] for s in found], ["Kira, Wakiso, Uganda"])

    def test_a_same_named_place_far_from_kampala_does_not_push_out_the_local_one(self):
        # Real case: "kyanja" also exists in Buikwe and Buvuma.
        found = self.suggest(autocomplete_payload(
            (0.0500, 32.4600, "Kyanjazi, Entebbe City, Uganda", "suburb"),       # ~35 km: kept
            (0.3300, 33.1500, "Kyanja, Buikwe, Uganda", "suburb"),               # ~64 km: dropped
            (1.2500, 33.2000, "Kyanja, Buvuma, Uganda", "suburb"),               # ~120 km: dropped
            (0.3900, 32.6100, "Kyanja, Kampala, Uganda", "suburb"),              # ~8 km: kept
        ))
        self.assertEqual(
            [s["label"] for s in found],
            ["Kyanjazi, Entebbe City, Uganda", "Kyanja, Kampala, Uganda"],
        )

    def test_at_most_five_are_shown_in_the_order_the_map_gave_them(self):
        places = [
            (0.31 + n * 0.001, 32.57, f"Place {n}, Kampala, Uganda", "street")
            for n in range(delivery.SUGGEST_FETCH)
        ]
        found = self.suggest(autocomplete_payload(*places))

        self.assertEqual(len(found), delivery.SUGGEST_LIMIT)
        self.assertEqual([s["label"] for s in found],
                         [f"Place {n}, Kampala, Uganda" for n in range(delivery.SUGGEST_LIMIT)])

    def test_duplicates_and_junk_are_dropped(self):
        payload = autocomplete_payload(STREET, STREET)
        payload["results"] += [
            None, "text", {}, {"formatted": "No position"}, {"lat": 1, "lon": 2},
            {"formatted": "Bad pos", "lat": "x", "lon": "y"},
        ]
        found = self.suggest(payload)
        self.assertEqual(len(found), 1)

    def test_any_failure_means_no_suggestions_and_never_leaks_the_key(self):
        leaky = requests.ConnectionError(f"url: /v1/geocode/autocomplete?apiKey={FAKE_KEY}")

        for failure in (
            requests.Timeout("slow"),
            FakeResponse({}, status_code=401),
            FakeResponse({}, status_code=429),
            FakeResponse(bad_json=True),
            FakeResponse(["not", "a", "dict"]),
            FakeResponse({"results": "oops"}),
        ):
            with self.subTest(failure=failure):
                with mock.patch("store.delivery.requests.get", side_effect=(
                    failure if isinstance(failure, Exception) else None
                ), return_value=(None if isinstance(failure, Exception) else failure)):
                    self.assertEqual(delivery.suggest_places("kyanja"), [])

        for exc in (leaky, RuntimeError(f"apiKey={FAKE_KEY}")):
            with self.subTest(exc=type(exc).__name__):
                with self.assertLogs("store.delivery", level=logging.DEBUG) as logs:
                    with mock.patch("store.delivery.requests.get", side_effect=exc):
                        self.assertEqual(delivery.suggest_places("kyanja"), [])
                self.assertNotIn(FAKE_KEY, "\n".join(logs.output))


@override_settings(GEOAPIFY_API_KEY=FAKE_KEY, SECRET_KEY="test-secret-key-for-tokens")
class PlaceTokenTests(SimpleTestCase):
    """The signed token is what stops a customer pairing a NEARBY position
    with a FAR AWAY address."""

    def token_for(self, place=STREET):
        with mock.patch(
            "store.delivery.requests.get",
            return_value=FakeResponse(autocomplete_payload(place)),
        ):
            return delivery.suggest_places("anything")[0]

    def test_a_genuine_token_gives_back_the_exact_position(self):
        suggestion = self.token_for()
        place = delivery.verify_place_token(suggestion["token"], suggestion["label"])

        self.assertEqual((place.lat, place.lon), (0.35, 32.6))
        self.assertEqual(place.label, "Ntinda Road, Kampala, Uganda")
        self.assertEqual(place.result_type, "street")
        self.assertEqual(place.key, "0.35000,32.60000")

    def test_details_may_follow_the_picked_place(self):
        s = self.token_for()
        for address in (
            s["label"] + "\nPlot 12, Block B",
            s["label"] + ", house 4",
            "  " + s["label"].upper() + "   ",
            s["label"].lower(),
        ):
            with self.subTest(address=address):
                self.assertIsNotNone(delivery.verify_place_token(s["token"], address))

    def test_a_different_address_text_is_refused(self):
        s = self.token_for()
        for address in (
            "Plot 99 Far Away Road, Mukono",
            "",
            "Ntinda",                            # shorter than the picked place
            "Near " + s["label"],                # the place must come FIRST
        ):
            with self.subTest(address=address):
                self.assertIsNone(delivery.verify_place_token(s["token"], address))

    def test_tampered_or_forged_tokens_are_refused(self):
        s = self.token_for()
        token = s["token"]
        flipped = token[:-3] + ("AAA" if not token.endswith("AAA") else "BBB")

        forged_same_secret_other_purpose = signing.dumps(
            {"lat": 0.31, "lon": 32.57, "label": s["label"], "type": "street"},
            salt="some-other-feature",
        )
        unsigned = signing.b64_encode(
            b'{"lat": 0.31, "lon": 32.57, "label": "' + s["label"].encode() + b'", "type": "street"}'
        ).decode()

        for bad in (flipped, forged_same_secret_other_purpose, unsigned,
                    "", "garbage", token + "x", token[: len(token) // 2], None, 12345, ["x"]):
            with self.subTest(bad=str(bad)[:30]):
                self.assertIsNone(delivery.verify_place_token(bad, s["label"]))

    def test_changing_the_coordinates_inside_a_token_breaks_it(self):
        s = self.token_for()
        value, stamp, signature = s["token"].rsplit(":", 2)
        payload = signing.b64_decode(value.encode())
        edited = payload.replace(b"0.35", b"0.31")
        self.assertNotEqual(edited, payload)
        forged = f"{signing.b64_encode(edited).decode()}:{stamp}:{signature}"

        self.assertIsNone(delivery.verify_place_token(forged, s["label"]))

    def test_an_old_token_expires(self):
        s = self.token_for()
        too_late = time.time() + delivery.PLACE_TOKEN_MAX_AGE + 60

        with mock.patch("time.time", return_value=too_late):
            self.assertIsNone(delivery.verify_place_token(s["token"], s["label"]))

        self.assertIsNotNone(delivery.verify_place_token(s["token"], s["label"]))

    def test_impossible_or_incomplete_contents_are_refused(self):
        for payload in (
            {"lat": 200, "lon": 32, "label": "x", "type": "street"},
            {"lat": 0, "lon": 500, "label": "x", "type": "street"},
            {"lat": "abc", "lon": 32, "label": "x", "type": "street"},
            {"lat": 0, "lon": 32, "label": "", "type": "street"},
            {"lat": 0, "lon": 32, "label": "x"},
            ["not", "a", "dict"],
        ):
            with self.subTest(payload=payload):
                token = signing.dumps(payload, salt=delivery.PLACE_TOKEN_SALT)
                self.assertIsNone(delivery.verify_place_token(token, "x"))


@override_settings(GEOAPIFY_API_KEY=FAKE_KEY)
class PickedPlacePricingTests(SimpleTestCase):

    def price(self, kind, metres, label="Somewhere, Kampala, Uganda", route=None):
        place = delivery.Place(lat=0.35, lon=32.6, label=label, result_type=kind)
        calls = []

        def _get(url, params=None, timeout=None):
            calls.append((url, dict(params)))
            if route is not None:
                if isinstance(route, Exception):
                    raise route
                return route
            return FakeResponse(route_payload(metres))

        with mock.patch("store.delivery.requests.get", side_effect=_get):
            result = delivery.calculate_delivery_for_place(place)

        self.calls = calls
        return result

    def test_a_specific_place_is_priced_by_road_distance(self):
        for kind in ("street", "building", "amenity"):
            with self.subTest(kind=kind):
                result = self.price(kind, 8851)
                self.assertEqual(result.status, delivery.CALCULATED)
                self.assertEqual(result.fee, Decimal("3000"))
                self.assertEqual(result.distance_m, 8851)
                self.assertFalse(result.approximate)
                self.assertIn("Somewhere", result.note)

    def test_a_specific_place_close_by_is_free(self):
        self.assertEqual(self.price("street", 2300).fee, Decimal("0"))
        self.assertEqual(self.price("street", 2300).status, delivery.CALCULATED)

    def test_the_route_goes_from_the_pickup_point_to_the_picked_position(self):
        self.price("street", 5000)
        self.assertEqual(len(self.calls), 1)                  # no extra address lookup
        url, params = self.calls[0]
        self.assertEqual(url, delivery.ROUTING_URL)
        self.assertEqual(params["waypoints"], "0.3153404,32.5749709|0.35,32.6")

    def test_a_picked_town_is_priced_from_its_centre_but_never_free(self):
        town = self.price("city", 15644, label="Kira, Wakiso, Uganda")
        self.assertEqual(town.status, delivery.CALCULATED)
        self.assertEqual(town.fee, Decimal("5000"))
        self.assertTrue(town.approximate)
        self.assertIn("TOWN CENTRE ONLY", town.note)

        kampala = self.price("city", 1724, label="Kampala, KM, Uganda")
        self.assertEqual(kampala.status, delivery.UNVERIFIED)
        self.assertEqual(kampala.fee, Decimal("0"))

    def test_a_picked_suburb_is_priced_and_flagged(self):
        result = self.price("suburb", 11000, label="Kyanja, Kampala, Uganda")
        self.assertEqual(result.fee, Decimal("5000"))
        self.assertTrue(result.approximate)
        self.assertIn("AREA ONLY", result.note)

    def test_a_whole_region_is_refused_without_calling_the_map(self):
        for kind in ("country", "state", "county", "postcode"):
            with self.subTest(kind=kind):
                result = self.price(kind, 1000)
                self.assertEqual(result.status, delivery.UNVERIFIED)
                self.assertEqual(result.problem, "address")
                self.assertEqual(self.calls, [])

    def test_beyond_the_last_price_band_is_a_quote(self):
        result = self.price("street", 19200)
        self.assertEqual(result.status, delivery.QUOTE_REQUIRED)
        self.assertEqual(result.fee, Decimal("0"))

    def test_a_routing_failure_means_a_phone_call_not_a_crash(self):
        for failure in (requests.Timeout("slow"), FakeResponse({}, status_code=500),
                        FakeResponse({"features": []})):
            with self.subTest(failure=failure):
                result = self.price("street", 0, route=failure)
                self.assertEqual(result.status, delivery.UNVERIFIED)
                self.assertEqual(result.problem, "service")
                self.assertEqual(result.fee, Decimal("0"))

    @override_settings(GEOAPIFY_API_KEY="")
    def test_no_key_means_a_phone_call(self):
        result = self.price("street", 5000)
        self.assertEqual(result.status, delivery.UNVERIFIED)
        self.assertEqual(self.calls, [])
