"""
End-to-end tests for delivery fees at checkout.

These drive the real checkout view with Django's test client. Only the map
lookup (store.views.calculate_delivery) is replaced, so nothing here calls
Geoapify.

Run:  python manage.py test store.test_checkout_delivery --keepdb
"""

import re
import time
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.core import mail, signing
from django.core.cache import cache
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from . import delivery, emails
from .admin import OrderAdmin
from .delivery import DeliveryResult
from .models import Bag, Category, Order, OrderItem
from .test_delivery import FakeResponse, autocomplete_payload, route_payload

LOOKUP = "store.views.calculate_delivery"

PRICE = Decimal("50000")          # one bag
QUANTITY = 2                      # in the cart
SUBTOTAL = PRICE * QUANTITY       # 100,000


def button_label(response):
    """The words on the checkout button, ignoring the rest of the page."""
    html = response.content.decode()
    found = re.search(r'<button[^>]*checkout-submit[^>]*>\s*(.*?)\s*</button>', html, re.S)
    return found.group(1).strip() if found else None


def calculated(fee, metres=8851):
    return DeliveryResult(
        status=delivery.CALCULATED,
        fee=Decimal(fee),
        distance_m=metres,
        note=f"{metres / 1000:.1f} km by road. Matched to: Kosovo, Kampala",
    )


TOO_FAR = DeliveryResult(
    status=delivery.QUOTE_REQUIRED,
    distance_m=19200,
    note="19.2 km by road. Matched to: Mukono",
)

UNKNOWN_ADDRESS = DeliveryResult(
    status=delivery.UNVERIFIED,
    note="Address not found on the map.",
    problem="address",
)

MAP_DOWN = DeliveryResult(
    status=delivery.UNVERIFIED,
    note="The map service took too long to answer.",
    problem="service",
)


@override_settings(SECURE_SSL_REDIRECT=False)
class CheckoutBase(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("buyer", "buyer@example.com", "pw")
        self.client.force_login(self.user)

        category, _ = Category.objects.get_or_create(name="Backpacks")
        self.bag = Bag.objects.create(
            category=category, name="Zara Backpack", price=PRICE, stock=10
        )
        self.put_in_cart(QUANTITY)

    def put_in_cart(self, quantity):
        session = self.client.session
        session["cart"] = {str(self.bag.id): quantity}
        session.save()

    def form(self, **overrides):
        data = {
            "name": "Buyer One",
            "email": "buyer@example.com",
            "phone": "0700000000",
            "address": "Plot 4 Kosovo Road",
            "city": "Makindye",
            "notes": "",
        }
        data.update(overrides)
        return data

    def press(self, **overrides):
        return self.client.post(reverse("checkout"), self.form(**overrides))

    def stock(self):
        self.bag.refresh_from_db()
        return self.bag.stock


class FirstPressTests(CheckoutBase):
    """Pressing the button once shows the fee. It never creates an order."""

    def test_page_before_any_quote(self):
        response = self.client.get(reverse("checkout"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(button_label(response), "Check delivery fee")
        self.assertContains(response, "Calculated next")
        self.assertEqual(response.context["subtotal"], SUBTOTAL)
        self.assertEqual(response.context["final_total"], SUBTOTAL)

    def test_first_press_shows_the_fee_and_places_nothing(self):
        with mock.patch(LOOKUP, return_value=calculated("3000")) as lookup:
            response = self.press()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(lookup.call_count, 1)
        self.assertEqual(response.context["delivery_fee"], Decimal("3000"))
        self.assertEqual(response.context["final_total"], SUBTOTAL + 3000)
        self.assertEqual(button_label(response), "Place order")
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(self.stock(), 10)            # nothing reserved yet
        self.assertEqual(len(mail.outbox), 0)         # no emails yet

    def test_free_delivery_is_shown_as_free(self):
        with mock.patch(LOOKUP, return_value=calculated("0", metres=2300)):
            response = self.press()

        self.assertContains(response, "Free")
        self.assertEqual(response.context["final_total"], SUBTOTAL)

    def test_too_far_adds_no_fee_and_says_so(self):
        with mock.patch(LOOKUP, return_value=TOO_FAR):
            response = self.press()

        self.assertEqual(response.context["delivery_fee"], Decimal("0"))
        self.assertEqual(response.context["final_total"], SUBTOTAL)
        self.assertContains(response, "To be confirmed by phone")
        self.assertContains(response, "not included")
        self.assertEqual(button_label(response), "Place order")   # checkout continues

    def test_unverified_address_adds_no_fee_and_still_continues(self):
        for result in (UNKNOWN_ADDRESS, MAP_DOWN):
            with self.subTest(problem=result.problem):
                with mock.patch(LOOKUP, return_value=result):
                    response = self.press(address=f"somewhere {result.problem}")

                self.assertEqual(response.context["delivery_fee"], Decimal("0"))
                self.assertContains(response, "To be confirmed by phone")
                self.assertEqual(button_label(response), "Place order")

    def test_email_box_keeps_what_the_customer_typed(self):
        with mock.patch(LOOKUP, return_value=calculated("3000")):
            response = self.press(email="other@example.com")

        self.assertContains(response, 'value="other@example.com"')

    def test_missing_details_are_reported_without_a_map_lookup(self):
        with mock.patch(LOOKUP) as lookup:
            response = self.press(name="", address="")

        lookup.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "FULL NAME IS REQUIRED")
        self.assertContains(response, "DELIVERY ADDRESS IS REQUIRED")
        self.assertEqual(Order.objects.count(), 0)


class PlacingTheOrderTests(CheckoutBase):
    """The second press places the order with exactly the fee that was shown."""

    def place(self, result, **overrides):
        """Press twice, as a customer does. Returns the second response."""
        with mock.patch(LOOKUP, return_value=result) as lookup:
            self.press(**overrides)
            response = self.press(**overrides)

        self.lookup_calls = lookup.call_count
        return response

    def test_order_is_saved_with_every_figure(self):
        response = self.place(calculated("3000"))

        order = Order.objects.get()
        self.assertRedirects(
            response,
            reverse("order_confirmation", args=[order.order_number]),
            fetch_redirect_response=False,
        )
        self.assertEqual(order.subtotal, SUBTOTAL)
        self.assertEqual(order.delivery_fee, Decimal("3000"))
        self.assertEqual(order.total, SUBTOTAL + 3000)
        self.assertEqual(order.subtotal + order.delivery_fee, order.total)
        self.assertEqual(order.delivery_distance_m, 8851)
        self.assertEqual(order.delivery_status, "CALCULATED")
        self.assertIn("Kosovo", order.delivery_note)
        self.assertEqual(order.address, "Plot 4 Kosovo Road")
        self.assertEqual(order.city, "Makindye")

    def test_existing_behaviour_is_kept(self):
        self.place(calculated("3000"))

        self.assertEqual(self.stock(), 10 - QUANTITY)           # stock reduced
        self.assertEqual(self.client.session.get("cart"), {})   # cart emptied
        self.assertEqual(OrderItem.objects.count(), 1)
        item = OrderItem.objects.get()
        self.assertEqual((item.price, item.quantity), (PRICE, QUANTITY))
        self.assertEqual(len(mail.outbox), 2)                   # staff + customer

    def test_the_map_is_asked_only_once_for_the_same_address(self):
        self.place(calculated("3000"))
        self.assertEqual(self.lookup_calls, 1)

    def test_free_order_total_is_just_the_products(self):
        self.place(calculated("0", metres=2300))

        order = Order.objects.get()
        self.assertEqual(order.delivery_fee, Decimal("0"))
        self.assertEqual(order.total, SUBTOTAL)
        self.assertEqual(order.delivery_status, "CALCULATED")

    def test_too_far_order_is_placed_but_not_priced(self):
        self.place(TOO_FAR)

        order = Order.objects.get()
        self.assertEqual(order.delivery_status, "QUOTE_REQUIRED")
        self.assertEqual(order.delivery_fee, Decimal("0"))
        self.assertEqual(order.total, SUBTOTAL)         # products only
        self.assertEqual(order.delivery_distance_m, 19200)
        self.assertTrue(order.delivery_fee_pending)
        self.assertEqual(order.status, "PENDING")       # not "confirmed"

    def test_unverified_orders_are_flagged_for_a_call(self):
        for result in (UNKNOWN_ADDRESS, MAP_DOWN):
            with self.subTest(problem=result.problem):
                Order.objects.all().delete()
                self.put_in_cart(QUANTITY)
                self.place(result)

                order = Order.objects.get()
                self.assertEqual(order.delivery_status, "UNVERIFIED")
                self.assertEqual(order.delivery_fee, Decimal("0"))
                self.assertEqual(order.total, SUBTOTAL)
                self.assertTrue(order.delivery_note)

    def test_staff_alert_says_when_a_call_is_needed(self):
        self.place(TOO_FAR)
        staff = mail.outbox[0]
        self.assertIn("CALL CUSTOMER FOR DELIVERY FEE", staff.subject)

        mail.outbox.clear()
        Order.objects.all().delete()
        self.put_in_cart(QUANTITY)
        self.place(calculated("3000"))
        self.assertNotIn("CALL CUSTOMER", mail.outbox[0].subject)

    # ---- the customer cannot choose the price ----

    def test_fee_and_total_fields_in_the_form_are_ignored(self):
        with mock.patch(LOOKUP, return_value=calculated("5000", metres=12000)):
            self.press()
            self.press(
                delivery_fee="0",
                total="1",
                subtotal="1",
                final_total="1",
                delivery_status="CALCULATED",
                delivery_distance_m="1",
            )

        order = Order.objects.get()
        self.assertEqual(order.delivery_fee, Decimal("5000"))
        self.assertEqual(order.total, SUBTOTAL + 5000)
        self.assertEqual(order.subtotal, SUBTOTAL)
        self.assertEqual(order.delivery_distance_m, 12000)

    def test_a_far_address_cannot_be_turned_into_a_free_one(self):
        self.place(
            TOO_FAR,
            delivery_fee="0",
            delivery_status="CALCULATED",
            delivery_distance_m="100",
        )

        order = Order.objects.get()
        self.assertEqual(order.delivery_status, "QUOTE_REQUIRED")
        self.assertEqual(order.delivery_distance_m, 19200)

    def test_pressing_place_order_first_does_not_skip_the_quote(self):
        # Posting straight away (no earlier quote) only ever shows the fee.
        with mock.patch(LOOKUP, return_value=calculated("3000")) as lookup:
            self.press()

        self.assertEqual(lookup.call_count, 1)
        self.assertEqual(Order.objects.count(), 0)

    # ---- a quote only counts for what the customer was shown ----

    def test_changing_the_address_needs_a_new_quote(self):
        with mock.patch(LOOKUP, side_effect=[calculated("0", 2000), calculated("5000", 12000)]) as lookup:
            self.press(address="Plot 4 Near Giant")
            response = self.press(address="Plot 99 Far Away Road")

        self.assertEqual(lookup.call_count, 2)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(response.context["delivery_fee"], Decimal("5000"))

    def test_changing_only_the_city_needs_a_new_quote(self):
        with mock.patch(LOOKUP, return_value=calculated("3000")) as lookup:
            self.press(city="Makindye")
            self.press(city="Kira")

        self.assertEqual(lookup.call_count, 2)
        self.assertEqual(Order.objects.count(), 0)

    def test_extra_spaces_and_capitals_do_not_count_as_a_change(self):
        with mock.patch(LOOKUP, return_value=calculated("3000")) as lookup:
            self.press(address="Plot 4  Kosovo Road")
            self.press(address="  plot 4 kosovo   ROAD ")

        self.assertEqual(lookup.call_count, 1)
        self.assertEqual(Order.objects.count(), 1)

    def test_changing_the_basket_needs_a_new_quote(self):
        with mock.patch(LOOKUP, return_value=calculated("3000")) as lookup:
            self.press()
            self.put_in_cart(3)
            response = self.press()

        self.assertEqual(lookup.call_count, 2)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(response.context["subtotal"], PRICE * 3)

    def test_an_old_quote_is_not_used(self):
        with mock.patch(LOOKUP, return_value=calculated("3000")) as lookup:
            self.press()

            session = self.client.session
            session["delivery_quote"]["at"] = time.time() - 3 * 3600
            session.save()

            self.press()

        self.assertEqual(lookup.call_count, 2)
        self.assertEqual(Order.objects.count(), 0)

    def test_a_damaged_quote_is_not_used(self):
        damaged = [
            {"fee": "-5000"},
            {"fee": "banana"},
            {"status": "SOMETHING_ELSE"},
            {"at": "not a time"},
            {"subtotal": "not money"},
        ]
        for change in damaged:
            with self.subTest(change=change):
                Order.objects.all().delete()
                self.put_in_cart(QUANTITY)

                # start every case with no saved quote (a still-valid one
                # from the previous case would, correctly, place the order)
                session = self.client.session
                session.pop("delivery_quote", None)
                session.save()

                with mock.patch(LOOKUP, return_value=calculated("3000")) as lookup:
                    self.press()
                    session = self.client.session
                    session["delivery_quote"].update(change)
                    session.save()
                    self.press()

                self.assertEqual(lookup.call_count, 2)
                self.assertEqual(Order.objects.count(), 0)

    def test_a_used_quote_cannot_be_used_again(self):
        self.place(calculated("0", metres=2000))
        self.assertEqual(Order.objects.count(), 1)

        self.put_in_cart(QUANTITY)
        with mock.patch(LOOKUP, return_value=calculated("5000", 12000)) as lookup:
            self.press()

        self.assertEqual(lookup.call_count, 1)          # asked again
        self.assertEqual(Order.objects.count(), 1)      # no second order yet


class QuoteHelperTests(SimpleTestCase):

    def test_a_non_calculated_quote_never_carries_a_fee(self):
        session = {
            "delivery_quote": {
                "address": "a", "city": "b", "subtotal": "100",
                "status": delivery.QUOTE_REQUIRED, "fee": "9999",
                "distance_m": 20000, "note": "", "problem": "",
                "at": time.time(),
            }
        }
        quote = delivery.load_quote(session, "a", "b", Decimal("100"))
        self.assertEqual(quote.fee, Decimal("0"))

    def test_nothing_saved_means_no_quote(self):
        self.assertIsNone(delivery.load_quote({}, "a", "b", Decimal("1")))
        self.assertIsNone(delivery.load_quote({"delivery_quote": "x"}, "a", "b", Decimal("1")))


class MessageAndPageTests(CheckoutBase):

    def make_order(self, **fields):
        defaults = dict(
            user=self.user, order_number="ABC123ABC123", email="buyer@example.com",
            full_name="Buyer One", phone="0700", address="Kosovo", city="Makindye",
            total=Decimal("100000"),
        )
        defaults.update(fields)
        order = Order.objects.create(**defaults)
        OrderItem.objects.create(
            order=order, bag=self.bag, product_name="Zara Backpack",
            price=PRICE, quantity=QUANTITY,
        )
        return order

    def test_confirmation_page_shows_the_breakdown(self):
        order = self.make_order(
            subtotal=Decimal("100000"), delivery_fee=Decimal("3000"),
            total=Decimal("103000"), delivery_distance_m=8851,
            delivery_status="CALCULATED",
        )
        page = self.client.get(reverse("order_confirmation", args=[order.order_number]))

        self.assertContains(page, "Subtotal")
        self.assertContains(page, "UGX 100,000")
        self.assertContains(page, "UGX 3,000")
        self.assertContains(page, "8.9 km by road")
        self.assertContains(page, "UGX 103,000")

    def test_confirmation_page_for_a_free_delivery(self):
        order = self.make_order(
            subtotal=Decimal("100000"), total=Decimal("100000"),
            delivery_status="CALCULATED",
        )
        page = self.client.get(reverse("order_confirmation", args=[order.order_number]))
        self.assertContains(page, "Free")

    def test_confirmation_page_for_a_pending_fee(self):
        order = self.make_order(
            subtotal=Decimal("100000"), total=Decimal("100000"),
            delivery_status="QUOTE_REQUIRED",
        )
        page = self.client.get(reverse("order_confirmation", args=[order.order_number]))
        self.assertContains(page, "To be confirmed")
        self.assertContains(page, "+ delivery")
        self.assertContains(page, "call you to agree your delivery fee")

    def test_an_older_order_looks_exactly_as_before(self):
        order = self.make_order(total=Decimal("275000"))     # no subtotal, no fee
        page = self.client.get(reverse("order_confirmation", args=[order.order_number]))

        self.assertContains(page, "UGX 275,000")
        self.assertNotContains(page, "Subtotal")
        self.assertNotContains(page, "+ delivery")
        self.assertNotContains(page, "To be confirmed")

    def test_my_orders_marks_a_fee_still_to_be_agreed(self):
        self.make_order(
            subtotal=Decimal("100000"), total=Decimal("100000"),
            delivery_status="UNVERIFIED",
        )
        page = self.client.get(reverse("order_history"))
        self.assertContains(page, "+ delivery")

        Order.objects.all().delete()
        self.make_order(total=Decimal("275000"))
        page = self.client.get(reverse("order_history"))
        self.assertNotContains(page, "+ delivery")


class EmailTests(CheckoutBase):

    def customer_email(self):
        return [m for m in mail.outbox if m.to == ["buyer@example.com"]][0]

    def staff_email(self):
        return [m for m in mail.outbox if m.to != ["buyer@example.com"]][0]

    def place(self, result):
        with mock.patch(LOOKUP, return_value=result):
            self.press()
            self.press()

    def test_emails_show_subtotal_delivery_and_total(self):
        self.place(calculated("3000"))

        for body in (self.customer_email().body, self.staff_email().body):
            self.assertIn("Subtotal: UGX 100,000", body)
            self.assertIn("Delivery: UGX 3,000", body)
            self.assertIn("TOTAL: UGX 103,000", body)

        self.assertIn("Delivery check: Calculated (8.9 km by road)", self.staff_email().body)

    def test_free_delivery_email(self):
        self.place(calculated("0", metres=2300))
        body = self.customer_email().body
        self.assertIn("Delivery: FREE", body)
        self.assertIn("TOTAL: UGX 100,000", body)

    def test_pending_fee_email_does_not_pretend_to_be_final(self):
        self.place(TOO_FAR)
        body = self.customer_email().body

        self.assertIn("Subtotal: UGX 100,000", body)
        self.assertIn("Delivery: to be confirmed by phone", body)
        self.assertIn("TOTAL: UGX 100,000 + delivery fee", body)
        self.assertIn("agree the delivery fee", body)

    def test_every_status_email_carries_the_breakdown(self):
        self.place(calculated("3000"))
        order = Order.objects.get()

        for send in (
            emails.send_order_received_email,
            emails.send_order_confirmed_email,
            emails.send_order_shipped_email,
            emails.send_order_delivered_email,
            emails.send_order_cancelled_email,
        ):
            with self.subTest(email=send.__name__):
                mail.outbox.clear()
                send(order)
                self.assertIn("TOTAL: UGX 103,000", mail.outbox[0].body)
                self.assertIn("Delivery: UGX 3,000", mail.outbox[0].body)

    def test_older_orders_keep_their_single_total_line_in_every_email(self):
        order = Order.objects.create(
            user=self.user, order_number="OLD000000001", email="buyer@example.com",
            full_name="Old Customer", phone="0700", address="Ntinda", city="Kampala",
            total=Decimal("275000"),
        )
        for send in (
            emails.send_order_received_email,
            emails.send_order_confirmed_email,
            emails.send_order_shipped_email,
            emails.send_order_delivered_email,
            emails.send_order_cancelled_email,
        ):
            with self.subTest(email=send.__name__):
                mail.outbox.clear()
                send(order)
                body = mail.outbox[0].body
                self.assertIn("TOTAL: UGX 275,000", body)
                self.assertNotIn("Subtotal", body)
                self.assertNotIn("Delivery:", body)


class AdminFeeTests(CheckoutBase):

    def setUp(self):
        super().setUp()
        self.admin = OrderAdmin(Order, AdminSite())
        self.staff = User.objects.create_superuser("boss", "boss@example.com", "pw")
        self.request = RequestFactory().post("/")
        self.request.user = self.staff

    def make_order(self, status, number="ADM000000001"):
        return Order.objects.create(
            user=self.user, order_number=number, email="buyer@example.com",
            full_name="Buyer", phone="0700", address="Kira", city="Wakiso",
            subtotal=Decimal("100000"), total=Decimal("100000"),
            delivery_distance_m=19200, delivery_status=status,
        )

    def test_money_fields_are_locked_on_a_finished_order(self):
        order = self.make_order("CALCULATED")
        locked = self.admin.get_readonly_fields(self.request, order)

        for field in ("subtotal", "delivery_fee", "total", "delivery_status"):
            self.assertIn(field, locked)

    def test_staff_may_type_the_fee_only_while_it_is_pending(self):
        for status in ("QUOTE_REQUIRED", "UNVERIFIED"):
            order = self.make_order(status, number=f"ADM{status[:8]}")
            locked = self.admin.get_readonly_fields(self.request, order)
            self.assertNotIn("delivery_fee", locked)
            self.assertIn("total", locked)              # still never editable

    def test_entering_the_agreed_fee_updates_the_total(self):
        order = self.make_order("QUOTE_REQUIRED")
        order.delivery_fee = Decimal("7000")

        self.admin.save_model(
            self.request, order, SimpleNamespace(changed_data=["delivery_fee"]), True
        )

        order.refresh_from_db()
        self.assertEqual(order.delivery_fee, Decimal("7000"))
        self.assertEqual(order.total, Decimal("107000"))
        self.assertEqual(order.delivery_status, "AGREED")
        self.assertFalse(order.delivery_fee_pending)
        self.assertIn("agreed by phone", order.delivery_note)
        self.assertIn("boss", order.delivery_note)

    def test_other_edits_do_not_touch_the_money(self):
        order = self.make_order("QUOTE_REQUIRED")
        order.payment_status = "PAID"

        self.admin.save_model(
            self.request, order, SimpleNamespace(changed_data=["payment_status"]), True
        )

        order.refresh_from_db()
        self.assertEqual(order.total, Decimal("100000"))
        self.assertEqual(order.delivery_status, "QUOTE_REQUIRED")

    def test_a_finished_order_total_is_never_recalculated(self):
        order = self.make_order("CALCULATED")
        order.delivery_fee = Decimal("99999")

        self.admin.save_model(
            self.request, order, SimpleNamespace(changed_data=["delivery_fee"]), True
        )

        order.refresh_from_db()
        self.assertEqual(order.total, Decimal("100000"))
        self.assertEqual(order.delivery_status, "CALCULATED")

    def test_agreed_action_keeps_the_fee_shown(self):
        pending = self.make_order("QUOTE_REQUIRED", number="ADM000000002")
        finished = self.make_order("CALCULATED", number="ADM000000003")

        with mock.patch.object(self.admin, "message_user"):
            self.admin.delivery_fee_agreed(
                self.request, Order.objects.filter(pk__in=[pending.pk, finished.pk])
            )

        pending.refresh_from_db()
        finished.refresh_from_db()
        self.assertEqual(pending.delivery_status, "AGREED")
        self.assertEqual(pending.total, Decimal("100000"))
        self.assertEqual(finished.delivery_status, "CALCULATED")


# ---------------------------------------------------------------------------
# Address suggestions while typing
# ---------------------------------------------------------------------------

LOOKUP_PLACE = "store.views.calculate_delivery_for_place"
SUGGEST = "store.views.suggest_places"
PLACE_LABEL = "Ntinda Road, Kampala, Uganda"


def token_for(label=PLACE_LABEL, lat=0.35, lon=32.60, kind="street"):
    return signing.dumps(
        {"lat": lat, "lon": lon, "label": label, "type": kind},
        salt=delivery.PLACE_TOKEN_SALT,
    )


SUGGESTION = {"label": PLACE_LABEL, "city": "Kampala", "token": "tok"}


class SuggestionEndpointTests(CheckoutBase):

    def setUp(self):
        super().setUp()
        cache.clear()
        self.url = reverse("address_suggestions")

    def ask(self, query, client=None):
        return (client or self.client).get(self.url, {"q": query})

    def test_the_route_exists(self):
        self.assertEqual(self.url, "/checkout/address-suggestions/")

    def test_customers_must_be_logged_in(self):
        with mock.patch(SUGGEST) as suggest:
            response = self.ask("kyanja", client=Client())

        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])
        suggest.assert_not_called()

    def test_answers_with_json_and_is_never_cached_by_the_browser(self):
        with mock.patch(SUGGEST, return_value=[SUGGESTION]) as suggest:
            response = self.ask("kyanja")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json(), {"suggestions": [SUGGESTION]})
        self.assertIn("no-store", response["Cache-Control"])
        suggest.assert_called_once_with("kyanja")

    def test_only_get_is_accepted(self):
        response = self.client.post(self.url, {"q": "kyanja"})
        self.assertEqual(response.status_code, 405)

    def test_short_queries_cost_nothing(self):
        with mock.patch(SUGGEST) as suggest:
            for query in ("", "ky", "k y", "   "):
                response = self.ask(query)
                self.assertEqual(response.json(), {"suggestions": []})

        suggest.assert_not_called()

    def test_a_very_long_query_is_cut_down(self):
        with mock.patch(SUGGEST, return_value=[]) as suggest:
            self.ask("x" * 5000)

        self.assertLessEqual(len(suggest.call_args.args[0]), 100)

    def test_a_repeated_search_is_answered_from_the_cache(self):
        with mock.patch(SUGGEST, return_value=[SUGGESTION]) as suggest:
            first = self.ask("Kyanja")
            second = self.ask("  kyanja ")

        self.assertEqual(suggest.call_count, 1)
        self.assertEqual(first.json(), second.json())

    def test_a_failed_lookup_is_not_remembered(self):
        with mock.patch(SUGGEST, side_effect=[[], [SUGGESTION]]) as suggest:
            self.assertEqual(self.ask("kyanja").json(), {"suggestions": []})
            self.assertEqual(self.ask("kyanja").json(), {"suggestions": [SUGGESTION]})

        self.assertEqual(suggest.call_count, 2)

    def test_one_customer_cannot_run_up_the_map_bill(self):
        other = User.objects.create_user("other", "other@example.com", "pw")
        other_client = Client()
        other_client.force_login(other)

        with mock.patch("store.views.SUGGESTION_REQUESTS_PER_WINDOW", 3):
            with mock.patch(SUGGEST, return_value=[SUGGESTION]) as suggest:
                codes = [self.ask(f"place{n}").status_code for n in range(5)]

                self.assertEqual(codes, [200, 200, 200, 429, 429])
                self.assertEqual(self.ask("place9").json(), {"suggestions": []})

                # a search that is already cached costs no lookup, so it still works
                self.assertEqual(self.ask("place0").status_code, 200)

                # and another customer is not affected
                self.assertEqual(self.ask("place0", client=other_client).status_code, 200)
                self.assertEqual(self.ask("brandnew", client=other_client).status_code, 200)

        self.assertEqual(suggest.call_count, 4)     # 3 for the first customer + 1 for the other

    @override_settings(GEOAPIFY_API_KEY="the-secret-key-123")
    def test_end_to_end_the_customer_never_sees_the_key_and_the_token_is_genuine(self):
        calls = []

        def geoapify(url, params=None, timeout=None):
            calls.append((url, dict(params)))
            return FakeResponse(autocomplete_payload(
                (0.35, 32.60, PLACE_LABEL, "street", "Kampala"),
            ))

        with mock.patch("store.delivery.requests.get", side_effect=geoapify):
            response = self.ask("ntinda")

        self.assertEqual(calls[0][0], delivery.AUTOCOMPLETE_URL)
        self.assertEqual(calls[0][1]["apiKey"], "the-secret-key-123")
        self.assertNotIn("the-secret-key-123", response.content.decode())

        suggestion = response.json()["suggestions"][0]
        self.assertEqual(suggestion["label"], PLACE_LABEL)
        self.assertIsNotNone(delivery.verify_place_token(suggestion["token"], PLACE_LABEL))


class PickedPlaceCheckoutTests(CheckoutBase):

    def press_with(self, token, **overrides):
        return self.press(place_token=token, **overrides)

    def test_the_checkout_page_has_the_suggestion_box(self):
        with override_settings(GEOAPIFY_API_KEY="the-secret-key-123"):
            page = self.client.get(reverse("checkout"))

        self.assertContains(page, 'data-suggest-url="/checkout/address-suggestions/"')
        self.assertContains(page, 'id="place_token"')
        self.assertContains(page, "choose your address from the list")
        self.assertContains(page, "address-suggestions")           # the script is included
        self.assertNotContains(page, "the-secret-key-123")

    def test_a_picked_place_is_priced_from_its_position_and_the_page_keeps_the_token(self):
        token = token_for()

        with mock.patch(LOOKUP, return_value=calculated("9999")) as typed, \
             mock.patch(LOOKUP_PLACE, return_value=calculated("3000")) as picked:
            response = self.press_with(token, address=PLACE_LABEL, city="Kampala")

        typed.assert_not_called()                  # the typed text was not looked up
        self.assertEqual(picked.call_count, 1)

        place = picked.call_args.args[0]
        self.assertEqual((place.lat, place.lon), (0.35, 32.6))

        self.assertEqual(response.context["delivery_fee"], Decimal("3000"))
        self.assertContains(response, f'value="{token}"')   # still there for the 2nd press
        self.assertEqual(Order.objects.count(), 0)

    def test_the_second_press_places_the_order_with_that_quote(self):
        token = token_for()

        with mock.patch(LOOKUP, return_value=calculated("9999")) as typed, \
             mock.patch(LOOKUP_PLACE, return_value=calculated("3000")) as picked:
            self.press_with(token, address=PLACE_LABEL, city="Kampala")
            self.press_with(token, address=PLACE_LABEL, city="Kampala")

        self.assertEqual(picked.call_count, 1)
        typed.assert_not_called()

        order = Order.objects.get()
        self.assertEqual(order.delivery_fee, Decimal("3000"))
        self.assertEqual(order.total, SUBTOTAL + 3000)
        self.assertEqual(order.address, PLACE_LABEL)

    def test_house_number_added_after_the_place_keeps_it(self):
        with mock.patch(LOOKUP) as typed, mock.patch(LOOKUP_PLACE, return_value=calculated("3000")) as picked:
            self.press_with(token_for(), address=PLACE_LABEL + "\nPlot 12, Block B", city="Kampala")

        self.assertEqual(picked.call_count, 1)
        typed.assert_not_called()

    def test_a_tampered_token_is_ignored_and_the_typed_address_is_used(self):
        token = token_for()
        tampered = token[:-4] + "AAAA"

        with mock.patch(LOOKUP, return_value=calculated("5000", 12000)) as typed, \
             mock.patch(LOOKUP_PLACE) as picked:
            response = self.press_with(tampered, address=PLACE_LABEL, city="Kampala")

        picked.assert_not_called()
        self.assertEqual(typed.call_count, 1)
        self.assertEqual(response.context["delivery_fee"], Decimal("5000"))

    def test_a_nearby_token_cannot_be_used_for_a_faraway_address(self):
        # The attack: pick a real place right next to the pickup point (free),
        # then submit a faraway address with that token.
        near = token_for("Giant Shopping Centre, Kampala, Uganda", lat=0.3153, lon=32.5749)

        with mock.patch(LOOKUP, return_value=TOO_FAR) as typed, mock.patch(LOOKUP_PLACE) as picked:
            response = self.press_with(near, address="Plot 7 Mukono Town Road, Mukono", city="Mukono")

        picked.assert_not_called()
        self.assertEqual(typed.call_count, 1)
        self.assertEqual(response.context["quote"].status, delivery.QUOTE_REQUIRED)

    def test_the_form_cannot_supply_a_position_or_a_fee(self):
        # A far place is picked; the form also claims the pickup point's own
        # coordinates and a zero fee.
        far = token_for("Mukono Road, Mukono, Uganda", lat=0.45, lon=32.90)
        waypoints = []

        def geoapify(url, params=None, timeout=None):
            waypoints.append(params["waypoints"])
            return FakeResponse(route_payload(19200))

        with override_settings(GEOAPIFY_API_KEY="k"), \
             mock.patch("store.delivery.requests.get", side_effect=geoapify):
            for _ in range(2):
                self.press_with(
                    far, address="Mukono Road, Mukono, Uganda", city="Mukono",
                    lat="0.3153404", lon="32.5749709", latitude="0.3153404",
                    longitude="32.5749709", delivery_fee="0", distance="100",
                )

        self.assertEqual(waypoints, ["0.3153404,32.5749709|0.45,32.9"])
        order = Order.objects.get()
        self.assertEqual(order.delivery_status, "QUOTE_REQUIRED")
        self.assertEqual(order.delivery_distance_m, 19200)

    def test_a_typed_quote_is_not_reused_for_a_picked_place(self):
        with mock.patch(LOOKUP, return_value=calculated("5000", 12000)) as typed, \
             mock.patch(LOOKUP_PLACE, return_value=calculated("3000")) as picked:
            self.press(address=PLACE_LABEL, city="Kampala")                       # typed
            second = self.press_with(token_for(), address=PLACE_LABEL, city="Kampala")  # picked

        self.assertEqual(typed.call_count, 1)
        self.assertEqual(picked.call_count, 1)                    # a new quote was made
        self.assertEqual(Order.objects.count(), 0)                # and shown first
        self.assertEqual(second.context["delivery_fee"], Decimal("3000"))

    def test_end_to_end_with_only_the_map_service_replaced(self):
        calls = []

        def geoapify(url, params=None, timeout=None):
            calls.append(url)
            if url == delivery.AUTOCOMPLETE_URL:
                return FakeResponse(autocomplete_payload(
                    (0.35, 32.60, PLACE_LABEL, "street", "Kampala"),
                ))
            return FakeResponse(route_payload(8851))

        cache.clear()

        with override_settings(GEOAPIFY_API_KEY="k"), \
             mock.patch("store.delivery.requests.get", side_effect=geoapify):
            found = self.client.get(reverse("address_suggestions"), {"q": "ntinda"}).json()
            picked = found["suggestions"][0]

            for _ in range(2):
                self.press_with(picked["token"], address=picked["label"], city=picked["city"])

        # one suggestion lookup + one route: the typed text was never geocoded
        self.assertEqual(calls, [delivery.AUTOCOMPLETE_URL, delivery.ROUTING_URL])

        order = Order.objects.get()
        self.assertEqual(order.delivery_fee, Decimal("3000"))
        self.assertEqual(order.total, SUBTOTAL + 3000)
        self.assertEqual(order.delivery_distance_m, 8851)
        self.assertEqual(order.delivery_status, "CALCULATED")
        self.assertIn(PLACE_LABEL, order.delivery_note)
