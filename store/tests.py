from django.apps import apps as django_apps
from django.http import Http404
from django.test import TestCase, Client, RequestFactory
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from . import views
from .models import Category, Bag, Order, OrderItem
from django.core import mail
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
import importlib
import io
import json
import re
import time
from contextlib import redirect_stdout
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, unquote, urlparse

import jwt
import requests
from allauth.socialaccount.models import SocialApp
from PIL import Image


class BagModelTests(TestCase):

    def test_bag_creation(self):
        category = Category.objects.create(name="Travel")
        bag = Bag.objects.create(
            name="Weekender",
            category=category,
            price=150000,
            stock=5,
        )
        self.assertEqual(str(bag.stock), "5")
        self.assertEqual(bag.category.name, "Travel")


class StoreViewTests(TestCase):

    def setUp(self):
        self.category = Category.objects.create(name="Gym")
        self.bag = Bag.objects.create(
            name="Duffel",
            category=self.category,
            price=90000,
            stock=3,
            show_on_homepage=True,   # the default homepage shows featured bags only
            homepage_order=1,
        )
        self.client = Client()

    def test_index_loads(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Duffel")

    def test_product_detail_404_on_missing_bag(self):
        response = self.client.get("/bag/9999/")
        self.assertEqual(response.status_code, 404)

    def test_category_filter(self):
        response = self.client.get("/?category=Gym")
        self.assertContains(response, "Duffel")


class AuthTests(TestCase):

    def test_register_creates_user(self):
        client = Client()
        response = client.post("/accounts/register/", {
            "email": "test@example.com",
            "password": "a-strong-test-password-99",
            "password_confirm": "a-strong-test-password-99",
        })
        self.assertTrue(
            User.objects.filter(username="test@example.com").exists()
        )

    def test_checkout_requires_login(self):
        client = Client()
        response = client.get("/checkout/")
        self.assertEqual(response.status_code, 302)


class CheckoutTests(TestCase):

    def setUp(self):
        self.category = Category.objects.create(name="Gym")
        self.bag = Bag.objects.create(
            name="Duffel",
            category=self.category,
            price=90000,
            stock=3,
        )

        self.user = User.objects.create_user(
            username="buyer@example.com",
            email="buyer@example.com",
            password="a-strong-test-password-99",
        )

        self.client = Client()
        self.client.login(
            username="buyer@example.com",
            password="a-strong-test-password-99",
        )

    def add_to_session_cart(self, quantity):
        session = self.client.session
        session["cart"] = {str(self.bag.id): quantity}
        session.save()

    def test_successful_checkout_clears_cart_and_reduces_stock(self):

        self.add_to_session_cart(2)

        response = self.client.post("/checkout/", {
            "name": "Jane Doe",
            "email": "buyer@example.com",
            "phone": "0700000000",
            "address": "1 Market Street",
            "city": "Kampala",
            "notes": "",
        })

        self.bag.refresh_from_db()

        self.assertEqual(self.bag.stock, 1)  # 3 - 2 = 1
        self.assertEqual(self.client.session.get("cart"), {})
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(OrderItem.objects.count(), 1)

    def test_insufficient_stock_rolls_back_everything(self):

        self.add_to_session_cart(5)  # more than the 3 in stock

        response = self.client.post("/checkout/", {
            "name": "Jane Doe",
            "email": "buyer@example.com",
            "phone": "0700000000",
            "address": "1 Market Street",
            "city": "Kampala",
            "notes": "",
        })

        self.bag.refresh_from_db()

        self.assertEqual(self.bag.stock, 3)  # unchanged
        self.assertEqual(Order.objects.count(), 0)  # nothing created
        self.assertEqual(OrderItem.objects.count(), 0)
    def test_checkout_uses_pay_on_delivery(self):

        self.add_to_session_cart(1)

        response = self.client.post("/checkout/", {
            "name": "Jane Doe",
            "email": "buyer@example.com",
            "phone": "0700000000",
            "address": "1 Market Street",
            "city": "Kampala",
            "notes": "",
        })

        order = Order.objects.first()

        self.assertEqual(order.payment_method, "COD")
        self.assertEqual(order.payment_status, "PENDING")


    def test_payment_method_cannot_be_changed_by_checkout_form(self):

        self.add_to_session_cart(1)

        self.client.post("/checkout/", {
            "name": "Jane Doe",
            "email": "buyer@example.com",
            "phone": "0700000000",
            "address": "1 Market Street",
            "city": "Kampala",
            "notes": "",
            "payment_method": "MTN",
        })

        order = Order.objects.first()

        self.assertEqual(order.payment_method, "COD")    


class AuthValidationTests(TestCase):

    def test_register_rejects_weak_password(self):
        client = Client()
        client.post("/accounts/register/", {
            "email": "weak@example.com",
            "password": "12345",
            "password_confirm": "12345",
        })
        self.assertFalse(
            User.objects.filter(username="weak@example.com").exists()
        )

    def test_register_rejects_duplicate_email(self):
        User.objects.create_user(
            username="taken@example.com",
            email="taken@example.com",
            password="a-strong-test-password-99",
        )
        client = Client()
        client.post("/accounts/register/", {
            "email": "taken@example.com",
            "password": "another-strong-password-88",
            "password_confirm": "another-strong-password-88",
        })
        self.assertEqual(
            User.objects.filter(username="taken@example.com").count(), 1
        )


class CartLimitTests(TestCase):

    def setUp(self):
        self.category = Category.objects.create(name="Gym")
        self.bag = Bag.objects.create(
            name="Duffel",
            category=self.category,
            price=90000,
            stock=2,
        )
        self.client = Client()

    def test_cart_add_does_not_exceed_stock(self):

        for _ in range(3):  # try adding 3 units of a bag with only 2 in stock
            self.client.post(f"/cart/add/{self.bag.id}/")

        session = self.client.session
        self.assertEqual(session["cart"][str(self.bag.id)], 2)
    def test_cart_drops_item_when_stock_falls_to_zero(self):

        self.client.post(f"/cart/add/{self.bag.id}/")

        # simulate the bag selling out elsewhere while it sits in this cart
        self.bag.stock = 0
        self.bag.save(update_fields=["stock"])

        self.client.get("/cart/")

        session = self.client.session
        self.assertNotIn(str(self.bag.id), session.get("cart", {}))

    def test_cart_add_rejects_get(self):

        self.client.get(f"/cart/add/{self.bag.id}/")

        session = self.client.session
        self.assertNotIn(str(self.bag.id), session.get("cart", {}))        


class OrderAccessTests(TestCase):

    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner@example.com",
            email="owner@example.com",
            password="a-strong-test-password-99",
        )
        self.other_user = User.objects.create_user(
            username="other@example.com",
            email="other@example.com",
            password="a-strong-test-password-99",
        )
        self.order = Order.objects.create(
            user=self.owner,
            order_number="TESTORDER1",
            email="owner@example.com",
            full_name="Jane Doe",
            phone="0700000000",
            address="1 Market Street",
            city="Kampala",
            total=90000,
        )
        self.client = Client()

    def test_owner_can_view_their_order(self):
        self.client.login(
            username="owner@example.com",
            password="a-strong-test-password-99",
        )
        response = self.client.get(f"/order/{self.order.order_number}/")
        self.assertEqual(response.status_code, 200)

    def test_other_user_cannot_view_someone_elses_order(self):
        self.client.login(
            username="other@example.com",
            password="a-strong-test-password-99",
        )
        response = self.client.get(f"/order/{self.order.order_number}/")
        self.assertEqual(response.status_code, 404)

    def test_invalid_order_number_404s(self):
        self.client.login(
            username="owner@example.com",
            password="a-strong-test-password-99",
        )
        response = self.client.get("/order/DOESNOTEXIST/")
        self.assertEqual(response.status_code, 404)

class PasswordTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="pwtest@example.com",
            email="pwtest@example.com",
            password="original-strong-password-1",
        )
        self.client = Client()

    def test_password_change_requires_login(self):
        response = self.client.get("/accounts/password/change/")
        self.assertEqual(response.status_code, 302)

    def test_password_change_updates_password(self):

        self.client.login(
            username="pwtest@example.com",
            password="original-strong-password-1",
        )

        self.client.post("/accounts/password/change/", {
            "old_password": "original-strong-password-1",
            "new_password1": "brand-new-strong-password-2",
            "new_password2": "brand-new-strong-password-2",
        })

        self.assertTrue(
            self.client.login(
                username="pwtest@example.com",
                password="brand-new-strong-password-2",
            )
        )

    def test_password_reset_flow(self):

        self.client.post("/accounts/password-reset/", {
            "email": "pwtest@example.com"
        })

        self.assertEqual(len(mail.outbox), 1)

        match = re.search(r"(/accounts/password-reset/confirm/\S+)", mail.outbox[0].body)
        self.assertIsNotNone(match)

        response = self.client.get(match.group(1), follow=True)
        confirm_path = response.request["PATH_INFO"]

        self.client.post(confirm_path, {
            "new_password1": "reset-strong-password-3",
            "new_password2": "reset-strong-password-3",
        })

        self.assertTrue(
            self.client.login(
                username="pwtest@example.com",
                password="reset-strong-password-3",
            )
        )


class FullCustomerJourneyTests(TestCase):

    def setUp(self):
        self.category = Category.objects.create(name="Travel")
        self.bag = Bag.objects.create(
            name="Rolling Duffel",
            category=self.category,
            price=180000,
            stock=5,
            show_on_homepage=True,   # the default homepage shows featured bags only
            homepage_order=1,
        )
        self.client = Client()

    def test_full_journey_browse_to_confirmation(self):

        self.client.post("/accounts/register/", {
            "email": "journey@example.com",
            "password": "a-strong-journey-password-1",
            "password_confirm": "a-strong-journey-password-1",
        })

        response = self.client.get("/")
        self.assertContains(response, "Rolling Duffel")

        self.client.post(f"/cart/add/{self.bag.id}/")

        response = self.client.get("/cart/")
        self.assertContains(response, "Rolling Duffel")

        response = self.client.post("/checkout/", {
            "name": "Journey Tester",
            "email": "journey@example.com",
            "phone": "0700000001",
            "address": "42 Test Lane",
            "city": "Kampala",
            "notes": "",
        }, follow=True)

        self.assertEqual(Order.objects.count(), 1)
        order = Order.objects.first()
        self.assertContains(response, order.order_number)


# ===========================================================================
# AUTHENTICATION: login, register, logout, password reset, Google
# ===========================================================================

PASSWORD = "a-strong-test-password-99"


def make_customer(email="ann@example.com", password=PASSWORD):
    """A customer registered through the shop's own form (username == email)."""
    return User.objects.create_user(username=email, email=email, password=password)


class LoginRoutingTests(TestCase):

    def setUp(self):
        self.customer = make_customer()
        self.client = Client()

    def test_header_login_link_goes_to_main_login(self):
        response = self.client.get("/")
        html = response.content.decode()
        self.assertRegex(html, r'href="/login/"\s+class="header-account-link"')
        self.assertNotIn('href="/accounts/login/"', html)

    def test_header_shows_account_link_when_logged_in(self):
        self.client.post("/login/", {"email": "ann@example.com", "password": PASSWORD})
        html = self.client.get("/").content.decode()
        self.assertRegex(html, r'href="/accounts/account/"\s+class="header-account-link"')
        self.assertNotRegex(html, r'href="/login/"\s+class="header-account-link"')

    def test_main_login_is_the_shops_own_page(self):
        response = self.client.get("/login/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "store/login.html")

    def test_legacy_login_address_redirects_to_main_login(self):
        response = self.client.get("/accounts/login/?next=/checkout/")
        self.assertRedirects(
            response, "/login/?next=/checkout/", fetch_redirect_response=False
        )

    def test_allauth_signup_and_reset_pages_redirect_to_the_shops_pages(self):
        self.assertRedirects(
            self.client.get("/accounts/signup/"),
            "/accounts/register/", fetch_redirect_response=False,
        )
        self.assertRedirects(
            self.client.get("/accounts/password/reset/"),
            "/accounts/password-reset/", fetch_redirect_response=False,
        )

    def test_login_succeeds_goes_home_with_one_message(self):
        response = self.client.post(
            "/login/", {"email": "ann@example.com", "password": PASSWORD}, follow=True
        )
        self.assertEqual(response.redirect_chain[-1][0], "/")
        self.assertIn("_auth_user_id", self.client.session)
        self.assertContains(response, "SUCCESSFULLY LOGGED IN.", count=1)

    def test_login_email_is_case_insensitive(self):
        self.client.post("/login/", {"email": "  ANN@Example.COM ", "password": PASSWORD})
        self.assertIn("_auth_user_id", self.client.session)

    def test_login_with_wrong_password_shows_error(self):
        response = self.client.post(
            "/login/", {"email": "ann@example.com", "password": "wrong-password"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid email or password.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_returns_customer_to_the_page_they_wanted(self):
        response = self.client.get("/checkout/")
        self.assertEqual(response["Location"], "/login/?next=/checkout/")
        response = self.client.post(
            "/login/?next=/checkout/",
            {"email": "ann@example.com", "password": PASSWORD},
        )
        self.assertRedirects(response, "/checkout/", fetch_redirect_response=False)

    def test_login_ignores_unsafe_next_addresses(self):
        for unsafe in ("https://evil.example/", "//evil.example/", "javascript:alert(1)"):
            client = Client()
            response = client.post(
                "/login/", {"email": "ann@example.com", "password": PASSWORD, "next": unsafe}
            )
            self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_logged_in_customer_visiting_login_goes_home(self):
        self.client.login(username="ann@example.com", password=PASSWORD)
        response = self.client.get("/login/")
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_login_works_when_username_differs_from_email(self):
        # e.g. an account created through Google, whose username is not the e-mail
        User.objects.create_user(
            username="grace", email="grace@example.com", password=PASSWORD
        )
        self.client.post("/login/", {"email": "grace@example.com", "password": PASSWORD})
        self.assertIn("_auth_user_id", self.client.session)

    def test_admin_can_still_log_in_with_a_username(self):
        User.objects.create_superuser("shopadmin", "owner@example.com", PASSWORD)
        self.assertTrue(self.client.login(username="shopadmin", password=PASSWORD))
        self.assertEqual(self.client.get("/admin/").status_code, 200)


class LogoutTests(TestCase):

    def setUp(self):
        make_customer()
        self.client = Client()
        self.client.login(username="ann@example.com", password=PASSWORD)

    def test_logout_signs_out_goes_home_and_confirms(self):
        response = self.client.post("/accounts/logout/", follow=True)
        self.assertEqual(response.redirect_chain[-1][0], "/")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "SUCCESSFULLY LOGGED OUT.", count=1)
        self.assertRegex(
            response.content.decode(), r'href="/login/"\s+class="header-account-link"'
        )

    def test_visiting_the_logout_address_does_not_log_out_or_error(self):
        response = self.client.get("/accounts/logout/")
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertIn("_auth_user_id", self.client.session)


class RegistrationFlowTests(TestCase):

    def register(self, email="new@example.com", password=PASSWORD, confirm=None, **extra):
        return self.client.post(
            "/accounts/register/",
            {
                "email": email,
                "password": password,
                "password_confirm": password if confirm is None else confirm,
            },
            **extra,
        )

    def test_register_logs_the_customer_in_with_one_message(self):
        response = self.register(follow=True)
        self.assertIn("_auth_user_id", self.client.session)
        self.assertEqual(response.redirect_chain[-1][0], "/")
        self.assertContains(response, "ACCOUNT CREATED SUCCESSFULLY.", count=1)

    def test_register_rejects_an_existing_email_in_any_case(self):
        make_customer("ann@example.com")
        response = self.register(email="ANN@example.com")
        self.assertContains(response, "AN ACCOUNT WITH THIS EMAIL ALREADY EXISTS.")
        self.assertEqual(User.objects.count(), 1)

    def test_register_rejects_the_email_of_a_google_account(self):
        User.objects.create_user(username="grace", email="grace@example.com")
        response = self.register(email="grace@example.com")
        self.assertContains(response, "AN ACCOUNT WITH THIS EMAIL ALREADY EXISTS.")
        self.assertEqual(User.objects.count(), 1)

    def test_register_error_is_shown_once(self):
        response = self.register(confirm="something-else-entirely-1")
        self.assertContains(response, "PASSWORDS DO NOT MATCH.", count=1)


class AccountAccessTests(TestCase):

    def test_account_and_orders_need_a_login_and_come_back_afterwards(self):
        for path in ("/accounts/account/", "/accounts/orders/", "/checkout/"):
            response = Client().get(path)
            self.assertRedirects(
                response, f"/login/?next={path}", fetch_redirect_response=False
            )

    def test_account_page_shows_the_customers_details(self):
        make_customer("ann@example.com")
        self.client.login(username="ann@example.com", password=PASSWORD)
        response = self.client.get("/accounts/account/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ann@example.com")


class PasswordResetFlowTests(TestCase):

    def test_reset_email_link_points_at_the_site_being_used(self):
        make_customer("ann@example.com")
        self.client.post("/accounts/password-reset/", {"email": "ann@example.com"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("http://testserver/accounts/password-reset/confirm/", mail.outbox[0].body)
        self.assertNotIn("example.com/accounts", mail.outbox[0].body)

    def test_unknown_email_sends_nothing_but_looks_identical(self):
        response = self.client.post("/accounts/password-reset/", {"email": "nobody@example.com"})
        self.assertRedirects(
            response, "/accounts/password-reset/done/", fetch_redirect_response=False
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_google_customer_without_a_password_can_set_one(self):
        user = User.objects.create_user(username="grace", email="grace@example.com")
        user.set_unusable_password()
        user.save()

        self.client.post("/accounts/password-reset/", {"email": "grace@example.com"})
        self.assertEqual(len(mail.outbox), 1)

        link = re.search(r"(/accounts/password-reset/confirm/\S+)", mail.outbox[0].body).group(1)
        confirm = self.client.get(link, follow=True).request["PATH_INFO"]
        self.client.post(confirm, {
            "new_password1": "brand-new-strong-password-5",
            "new_password2": "brand-new-strong-password-5",
        })

        response = self.client.post(
            "/login/", {"email": "grace@example.com", "password": "brand-new-strong-password-5"}
        )
        self.assertRedirects(response, "/", fetch_redirect_response=False)


class GoogleLoginTests(TestCase):
    """
    The complete Google round trip. Only Google's own answer (the token
    response, containing a real JWT) is faked: URLs, the state check, sessions,
    the adapters, user creation and redirects are all the real code.
    """

    CALLBACK = "/accounts/google/login/callback/"

    def setUp(self):
        app = SocialApp.objects.create(
            provider="google", name="Google",
            client_id="test-client-id", secret="test-secret",
        )
        app.sites.add(Site.objects.get_current())
        self.client = Client()

    def token_response(self, email, name="Grace Hopper", sub="google-user-1", status=200):
        now = int(time.time())
        id_token = jwt.encode(
            {
                "iss": "https://accounts.google.com", "aud": "test-client-id",
                "sub": sub, "email": email, "email_verified": True,
                "name": name, "given_name": name.split()[0], "family_name": name.split()[-1],
                "iat": now, "exp": now + 3600,
            },
            "not-checked-by-allauth-for-direct-token-responses",
            algorithm="HS256",
        )
        response = requests.Response()
        response.status_code = status
        response.headers["Content-Type"] = "application/json; charset=utf-8"
        response._content = json.dumps(
            {"access_token": "fake-token", "id_token": id_token,
             "token_type": "Bearer", "expires_in": 3600}
        ).encode()
        return response

    def start(self, **data):
        response = self.client.post("/accounts/google/login/", data)
        self.assertEqual(response.status_code, 302)
        return response["Location"]

    def come_back_from_google(self, google_url, token_response):
        state = parse_qs(urlparse(google_url).query)["state"][0]
        with mock.patch("requests.Session.request", return_value=token_response):
            return self.client.get(
                self.CALLBACK, {"code": "fake-code", "state": state}, follow=True
            )

    def sign_in_with_google(self, email="grace@example.com", **kwargs):
        url = self.start()
        return self.come_back_from_google(url, self.token_response(email, **kwargs))

    # -- the button ---------------------------------------------------------

    def test_login_and_register_pages_offer_google_as_a_post_form(self):
        for path in ("/login/", "/accounts/register/"):
            html = self.client.get(path).content.decode()
            self.assertIn('action="/accounts/google/login/"', html)
            self.assertIn("Continue with Google", html)

    def test_google_button_is_hidden_when_google_is_not_configured(self):
        SocialApp.objects.all().delete()
        for path in ("/login/", "/accounts/register/"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "Continue with Google")

    # -- the round trip -----------------------------------------------------

    def test_google_login_starts_at_google_and_returns_to_the_registered_callback(self):
        url = self.start()
        parts = urlparse(url)
        self.assertEqual(parts.netloc, "accounts.google.com")
        self.assertEqual(
            parse_qs(parts.query)["redirect_uri"][0],
            "http://testserver/accounts/google/login/callback/",
        )

    def test_new_google_customer_is_created_and_logged_in(self):
        response = self.sign_in_with_google("grace@example.com")
        self.assertEqual(response.redirect_chain[-1][0], "/")
        self.assertIn("_auth_user_id", self.client.session)
        self.assertContains(response, "ACCOUNT CREATED SUCCESSFULLY.", count=1)
        self.assertRegex(
            response.content.decode(), r'href="/accounts/account/"\s+class="header-account-link"'
        )
        user = User.objects.get(email="grace@example.com")
        self.assertEqual(user.username, "grace@example.com")
        self.assertEqual(User.objects.count(), 1)

    def test_returning_google_customer_is_not_duplicated(self):
        self.sign_in_with_google("grace@example.com")
        self.client.post("/accounts/logout/")
        response = self.sign_in_with_google("grace@example.com")
        self.assertEqual(User.objects.count(), 1)
        self.assertContains(response, "SUCCESSFULLY LOGGED IN.", count=1)

    def test_google_connects_to_a_customer_who_registered_with_the_same_email(self):
        existing = make_customer("ann@example.com")
        self.sign_in_with_google("ann@example.com", name="Ann Customer", sub="google-ann")
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(int(self.client.session["_auth_user_id"]), existing.pk)

    def test_google_signin_clears_an_unverified_form_password_and_reset_restores_it(self):
        # allauth's protection against "account pre-hijacking": the shop never verifies
        # the e-mail typed into the registration form, so when that e-mail signs in
        # through Google the old (unverified) password is cleared. The customer keeps
        # the same account and can set a new password from "Forgot password?".
        existing = make_customer("ann@example.com")
        self.sign_in_with_google("ann@example.com", name="Ann Customer", sub="google-ann")

        existing.refresh_from_db()
        self.assertFalse(existing.has_usable_password())
        self.assertEqual(User.objects.count(), 1)

        self.client.post("/accounts/logout/")
        mail.outbox.clear()
        self.client.post("/accounts/password-reset/", {"email": "ann@example.com"})
        self.assertEqual(len(mail.outbox), 1)

    def test_google_login_returns_to_the_page_the_customer_wanted(self):
        url = self.start(next="/accounts/account/")
        response = self.come_back_from_google(url, self.token_response("grace@example.com"))
        self.assertEqual(response.redirect_chain[-1][0], "/accounts/account/")
        self.assertEqual(response.status_code, 200)

    def test_cancelling_at_google_returns_to_login_with_a_message(self):
        url = self.start()
        state = parse_qs(urlparse(url).query)["state"][0]
        response = self.client.get(
            self.CALLBACK, {"error": "access_denied", "state": state}, follow=True
        )
        self.assertEqual(response.redirect_chain[-1][0], "/login/")
        self.assertContains(response, "GOOGLE SIGN-IN WAS CANCELLED.", count=1)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_a_failed_google_sign_in_returns_to_login_with_a_message(self):
        url = self.start()
        response = self.come_back_from_google(
            url, self.token_response("grace@example.com", status=400)
        )
        self.assertEqual(response.redirect_chain[-1][0], "/login/")
        self.assertContains(response, "GOOGLE SIGN-IN FAILED. PLEASE TRY AGAIN.", count=1)
        self.assertNotIn("_auth_user_id", self.client.session)


# ===========================================================================
# HOMEPAGE = PAGE 1 OF THE CATALOGUE, PAGINATION, SEARCH & FILTERS
# ===========================================================================

from django.core.exceptions import ValidationError


def make_bag(name, price=50000, stock=5, category=None, featured=None, **extra):
    """featured=<position> puts the bag on the homepage at that position."""
    if category is None:
        category, _ = Category.objects.get_or_create(name="Everyday")
    if featured:
        extra.update(show_on_homepage=True, homepage_order=featured)
    return Bag.objects.create(
        name=name, price=price, stock=stock, category=category, **extra
    )


def names(response):
    return [bag.name for bag in response.context["bags"]]


def ids(response):
    return [bag.id for bag in response.context["bags"]]


def bar_text(response):
    """The page bar as text, e.g. "Prev 1 2 3 Next". None when there is no bar."""
    nav = re.search(r'<nav class="pagination".*?</nav>', response.content.decode(), re.S)
    if not nav:
        return None
    return " ".join(re.sub(r"<[^>]+>", " ", nav.group(0)).split())


def page_title(response):
    """The text inside <title>, with the whitespace tidied."""
    found = re.search(r"<title>(.*?)</title>", response.content.decode(), re.S)
    return " ".join(found.group(1).split())


def make_many(count, prefix="Bag"):
    """Create `count` bags with one INSERT (fast even for 1,000+), oldest first."""
    category, _ = Category.objects.get_or_create(name="Everyday")
    Bag.objects.bulk_create([
        Bag(name=f"{prefix} {i:04d}", price=50000, stock=5, category=category)
        for i in range(1, count + 1)
    ])
    return list(Bag.objects.filter(name__startswith=prefix).order_by("id"))


def spread_created_at(bags):
    """Give every bag its own created_at, in a different order from its id."""
    start = timezone.now() - timedelta(days=1000)
    for n, bag in enumerate(sorted(bags, key=lambda b: (b.id * 7919) % 10007)):
        bag.created_at = start + timedelta(minutes=n)
    Bag.objects.bulk_update(bags, ["created_at"], batch_size=100)


class HomepageCurationTests(TestCase):
    """1 + 2: Page 1 of the homepage is the bags chosen in the admin (max 12), in that order."""

    def setUp(self):
        self.client = Client()

    def feature(self, count, offset=0):
        """Create `count` featured bags; creation order differs from position order."""
        bags = [make_bag(f"Bag {i:02d}") for i in range(1, count + 1)]
        for i, bag in enumerate(reversed(bags), start=1):   # last created = position 1
            bag.show_on_homepage = True
            bag.homepage_order = i + offset
            bag.save()
        return list(reversed(bags))                          # in position order

    def test_default_homepage_shows_featured_bags_in_position_order(self):
        in_order = self.feature(12)
        make_bag("Not Featured A")
        make_bag("Not Featured B")

        response = self.client.get("/")

        self.assertEqual(names(response), [b.name for b in in_order])
        self.assertNotContains(response, "Not Featured A")
        self.assertTrue(response.context["is_curated"])

    def test_homepage_never_shows_more_than_twelve(self):
        in_order = self.feature(14)
        response = self.client.get("/")
        self.assertEqual(names(response), [b.name for b in in_order[:12]])
        self.assertNotContains(response, in_order[12].name)
        self.assertNotContains(response, in_order[13].name)

    def test_a_new_bag_never_appears_on_the_homepage_by_itself(self):
        in_order = self.feature(12)
        make_bag("Brand New Bag")

        response = self.client.get("/")

        self.assertEqual(names(response), [b.name for b in in_order])
        self.assertNotContains(response, "Brand New Bag")

    def test_featuring_a_new_bag_at_a_position_puts_it_exactly_there(self):
        in_order = self.feature(11)
        new = make_bag("Chosen Bag")
        new.show_on_homepage = True
        new.homepage_order = 3
        new.save()

        # positions: 1, 2, [3 = new], then the old 3rd (which is also position 3)
        # is moved out of the way by the owner by giving it a new position
        third = in_order[2]
        third.homepage_order = 12
        third.save()

        listed = names(self.client.get("/"))
        self.assertEqual(listed[2], "Chosen Bag")
        self.assertEqual(len(listed), 12)

    def test_changing_positions_changes_the_order(self):
        in_order = self.feature(12)
        first, last = in_order[0], in_order[-1]
        first.homepage_order, last.homepage_order = 12, 1
        first.save(); last.save()

        listed = names(self.client.get("/"))
        self.assertEqual(listed[0], last.name)
        self.assertEqual(listed[-1], first.name)

    def test_unfeatured_bags_leave_the_homepage_but_stay_in_the_shop(self):
        in_order = self.feature(12)
        gone = in_order[4]
        gone.show_on_homepage = False
        gone.save()

        self.assertNotIn(gone.name, names(self.client.get("/")))
        self.assertIn(gone.name, names(self.client.get("/?page=2")))

    def test_homepage_with_nothing_featured_points_to_page_two(self):
        make_bag("Only On Page Two")
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(names(response), [])
        self.assertContains(response, "No bags have been chosen for the homepage yet.")
        self.assertContains(response, 'href="?page=2" class="button-secondary"')
        self.assertEqual(names(self.client.get("/?page=2")), ["Only On Page Two"])

    def test_page_one_offers_more_bags_only_when_there_are_more(self):
        self.feature(3)
        self.assertNotContains(self.client.get("/"), "View more bags")
        make_bag("Not Featured")
        self.assertContains(
            self.client.get("/"),
            '<a href="?page=2" class="text-link">View more bags</a>',
        )

    def test_empty_or_invalid_options_do_not_leave_the_curated_homepage(self):
        in_order = self.feature(3)
        make_bag("Hidden Bag")
        for query in (
            "/?q=&category=&sort=&min_price=&max_price=",
            "/?sort=not-a-sort",
            "/?min_price=abc&max_price=-5",
            "/?q=%20%20",
        ):
            response = self.client.get(query)
            self.assertTrue(response.context["is_curated"], query)
            self.assertEqual(names(response), [b.name for b in in_order], query)


class HomepageBrowsingModeTests(TestCase):
    """2: any search / filter / sort lists every matching bag (featured ones too), 16 per page."""

    def setUp(self):
        self.client = Client()
        gym = Category.objects.create(name="Gym")
        travel = Category.objects.create(name="Travel")
        self.featured = [make_bag(f"Featured {i}", featured=i, category=gym) for i in (1, 2)]
        # 18 bags that are NOT featured -> 20 in the catalogue, more than the 12 limit
        self.others = [
            make_bag(f"Other {i:02d}", price=10000 * i, stock=0 if i == 1 else 4,
                     category=travel if i % 2 else gym)
            for i in range(1, 19)
        ]

    def assertBrowsing(self, response):
        self.assertFalse(response.context["is_curated"])

    def test_every_option_switches_to_the_whole_catalogue_without_a_limit(self):
        for query in (
            "/?q=Featured", "/?q=Other", "/?category=Travel", "/?category=Gym",
            "/?in_stock=1", "/?min_price=1000", "/?max_price=999999999",
            "/?sort=newest", "/?sort=price_asc",
        ):
            response = self.client.get(query)
            self.assertBrowsing(response)
            self.assertGreater(len(names(response)), 0, query)

    def test_sort_alone_lists_all_twenty_bags_sixteen_per_page(self):
        first = self.client.get("/?sort=name_asc")
        second = self.client.get("/?sort=name_asc&page=2")
        self.assertBrowsing(first)
        self.assertEqual(first.context["result_count"], 20)   # every bag, not just the 12 picked
        self.assertEqual((len(names(first)), len(names(second))), (16, 4))
        self.assertEqual(len(set(names(first) + names(second))), 20)

    def test_search_finds_bags_that_are_not_featured(self):
        response = self.client.get("/?q=Other 07")
        self.assertEqual(names(response), ["Other 07"])

    def test_category_covers_the_entire_catalogue(self):
        response = self.client.get("/?category=Gym")
        expected = {b.name for b in Bag.objects.filter(category__name="Gym")}
        self.assertEqual(set(names(response)), expected)
        self.assertTrue(any(n.startswith("Other") for n in names(response)))

    def test_price_range_and_stock_filters_combine(self):
        response = self.client.get("/?min_price=50000&max_price=120000&in_stock=1")
        got = Bag.objects.filter(price__gte=50000, price__lte=120000, stock__gt=0)
        self.assertEqual(set(names(response)), {b.name for b in got})

    def test_stock_filter_hides_out_of_stock_bags(self):
        first = self.client.get("/?in_stock=1")
        second = self.client.get("/?in_stock=1&page=2")
        self.assertEqual(first.context["result_count"], 19)
        self.assertNotIn("Other 01", names(first) + names(second))     # stock 0
        self.assertEqual(len(names(first)) + len(names(second)), 19)

    def test_sorting_orders_are_correct(self):
        prices = lambda r: [b.price for b in r.context["bags"]]
        asc = prices(self.client.get("/?sort=price_asc"))
        desc = prices(self.client.get("/?sort=price_desc"))
        self.assertEqual(asc, sorted(asc))
        self.assertEqual(desc, sorted(desc, reverse=True))
        alpha = names(self.client.get("/?sort=name_asc"))
        self.assertEqual(alpha, sorted(alpha))
        newest = [b.id for b in self.client.get("/?sort=newest").context["bags"]]
        self.assertEqual(newest, sorted(newest, reverse=True))

    def test_browsing_page_offers_a_way_back(self):
        response = self.client.get("/?category=Gym")
        self.assertContains(response, "Clear filters")

    def test_no_results_page_is_friendly(self):
        response = self.client.get("/?q=zzzz-nothing")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No results for")


class HomepageIsPageOneTests(TestCase):
    """Page 1 is the picked bags. Page 2, 3, ... are every other bag, 16 per page, newest first."""

    def setUp(self):
        self.client = Client()
        self.picks = [make_bag(f"Pick {i:02d}", featured=i) for i in range(1, 6)]    # only 5 picked
        self.others = [make_bag(f"Other {i:02d}") for i in range(1, 31)]            # 30 not picked

    def test_fewer_than_twelve_picks_show_only_those(self):
        page_one = self.client.get("/")
        self.assertEqual(names(page_one), [b.name for b in self.picks])     # never topped up
        self.assertTrue(page_one.context["is_curated"])

    def test_later_pages_hold_every_other_bag_newest_first(self):
        two = self.client.get("/?page=2")
        three = self.client.get("/?page=3")
        self.assertEqual((len(names(two)), len(names(three))), (16, 14))
        self.assertEqual(names(two) + names(three), [b.name for b in reversed(self.others)])
        self.assertFalse(two.context["is_curated"])
        picked = {b.name for b in self.picks}
        self.assertFalse(picked & set(names(two) + names(three)))           # Page 1 bags never come back

    def test_the_page_bar(self):
        one = self.client.get("/")
        self.assertEqual(bar_text(one), "Prev 1 2 3 Next")
        self.assertEqual(bar_text(self.client.get("/?page=2")), "Prev 1 2 3 Next")
        self.assertIn('aria-current="page">1<', one.content.decode())
        # with no search or filter, a page link carries nothing but the page number
        links = set(re.findall(r'href="(\?[^"]*)"', one.content.decode()))
        self.assertEqual(links, {"?page=2", "?page=3"})
        # "Prev" from Page 2 goes back to Page 1, which is the picked bags again
        self.assertEqual(names(self.client.get("/?page=1")), [b.name for b in self.picks])

    def test_heading_and_title(self):
        one = self.client.get("/")
        self.assertContains(one, '<h1 class="shop-title">Featured</h1>')
        self.assertEqual(page_title(one), "Bags &amp; Beyond \u2014 Featured")

        two = self.client.get("/?page=2")
        self.assertContains(two, '<h1 class="shop-title">All Bags</h1>')
        self.assertNotContains(two, '<h1 class="shop-title">Featured</h1>')
        self.assertEqual(page_title(two), "Bags &amp; Beyond \u2014 All Bags - Page 2")
        self.assertEqual(
            page_title(self.client.get("/?page=3")), "Bags &amp; Beyond \u2014 All Bags - Page 3"
        )
        self.assertTrue(
            page_title(self.client.get("/?category=Everyday&page=2")).endswith("Everyday - Page 2")
        )

    def test_view_more_bags_is_on_page_one_only(self):
        self.assertContains(
            self.client.get("/"), '<a href="?page=2" class="text-link">View more bags</a>'
        )
        two = self.client.get("/?page=2")
        self.assertNotContains(two, "View more bags")
        self.assertContains(two, "<span>35 bags</span>")                    # 5 picked + 30 others

    def test_the_view_passes_everything_the_template_needs(self):
        keys = (
            "bags", "page_obj", "result_count", "page_numbers", "querystring", "categories",
            "is_curated", "query", "category_slug", "sort", "in_stock_only", "min_price", "max_price",
        )
        for url in ("/", "/?page=2", "/?sort=price_asc&page=2", "/?q=Other"):
            response = self.client.get(url)
            for key in keys:
                self.assertIn(key, response.context, f"{url} is missing {key}")
        self.assertEqual(self.client.get("/").context["result_count"], 35)
        self.assertEqual(self.client.get("/?page=2").context["querystring"], "")
        self.assertEqual(
            parse_qs(self.client.get("/?q=Other&sort=price_asc&page=2").context["querystring"]),
            {"q": ["Other"], "sort": ["price_asc"]},                        # the options, without "page"
        )

    def test_bad_page_numbers_do_not_break_the_homepage(self):
        for bad, expected in (("abc", 1), ("", 1), ("1.5", 1), ("999", 3)):
            response = self.client.get("/", {"page": bad})
            self.assertEqual(response.status_code, 200, bad)
            self.assertEqual(response.context["page_obj"].number, expected, bad)
        for bad in ("0", "-2", "99999999999999999999"):
            self.assertEqual(self.client.get("/", {"page": bad}).status_code, 200, bad)


class PicksBeyondTheLimitTests(TestCase):
    """Only the bags really shown on Page 1 are left out of the later pages."""

    def test_picks_beyond_twelve_still_appear_on_a_later_page(self):
        picks = [make_bag(f"Pick {i:02d}", featured=i) for i in range(1, 16)]     # 15 picked, limit is 12
        others = [make_bag(f"Other {i:02d}") for i in range(1, 11)]               # 10 not picked

        page_one = names(self.client.get("/"))
        self.assertEqual(page_one, [b.name for b in picks[:12]])

        # the 3 picked bags that did not fit + the 10 others = 13 bags, newest first
        page_two = self.client.get("/?page=2")
        self.assertEqual(names(page_two), [b.name for b in reversed(picks[12:] + others)])
        self.assertEqual(bar_text(page_two), "Prev 1 2 Next")

        everything = page_one + names(page_two)
        self.assertEqual(len(everything), 25)                                     # none repeated ...
        self.assertEqual(set(everything), {b.name for b in picks + others})       # ... and none skipped

    def test_equal_positions_fall_back_to_newest_first(self):
        picks = [make_bag(f"Tie {i:02d}", featured=1) for i in range(1, 15)]      # 14 bags, all "position 1"
        base = timezone.now() - timedelta(days=30)
        for n, bag in enumerate(picks):
            Bag.objects.filter(pk=bag.pk).update(created_at=base + timedelta(hours=n))   # Tie 14 is newest

        self.assertEqual(names(self.client.get("/")), [b.name for b in reversed(picks)][:12])
        self.assertEqual(names(self.client.get("/?page=2")), ["Tie 02", "Tie 01"])


class SmallAndEmptyShopTests(TestCase):
    """The page bar shows only when at least one bag is not on Page 1."""

    def test_an_empty_shop_is_a_friendly_single_page(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(names(response), [])
        self.assertEqual(response.context["result_count"], 0)
        self.assertContains(response, "No bags have been chosen for the homepage yet.")
        self.assertIsNone(bar_text(response))
        self.assertNotContains(response, "View more bags")
        for url in ("/?page=2", "/?page=abc", "/?page=-1", "/?q=nothing", "/?sort=newest&page=3"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_page_one_empty_but_the_bar_still_shows(self):
        for i in range(1, 21):
            make_bag(f"Other {i:02d}")                                    # nothing picked yet
        response = self.client.get("/")
        self.assertEqual(names(response), [])
        self.assertContains(response, "No bags have been chosen for the homepage yet.")
        self.assertEqual(bar_text(response), "Prev 1 2 3 Next")
        self.assertEqual(len(names(self.client.get("/?page=2"))), 16)
        self.assertEqual(len(names(self.client.get("/?page=3"))), 4)

    def test_twelve_picks_and_nothing_else_has_no_bar(self):
        for i in range(1, 13):
            make_bag(f"Pick {i:02d}", featured=i)
        response = self.client.get("/")
        self.assertEqual(len(names(response)), 12)
        self.assertIsNone(bar_text(response))
        self.assertNotContains(response, "View more bags")
        self.assertEqual(self.client.get("/?page=2").context["page_obj"].number, 1)    # nothing beyond Page 1

    def test_one_bag_outside_page_one_is_enough_for_the_bar(self):
        for i in range(1, 13):
            make_bag(f"Pick {i:02d}", featured=i)
        make_bag("Lonely Bag")
        response = self.client.get("/")
        self.assertEqual(len(names(response)), 12)
        self.assertEqual(bar_text(response), "Prev 1 2 Next")
        self.assertContains(response, "View more bags")
        self.assertEqual(names(self.client.get("/?page=2")), ["Lonely Bag"])


class CataloguePaginationTests(TestCase):
    """4: search / filter / sort list every matching bag, 16 per page, and the options survive every page link."""

    def setUp(self):
        self.client = Client()

    def make(self, count, **extra):
        return [make_bag(f"Bag {i:02d}", **extra) for i in range(1, count + 1)]

    def page_names(self, url):
        return names(self.client.get(url))

    def test_sixteen_per_page_across_three_pages(self):
        self.make(40)
        one = self.page_names("/?sort=newest")
        two = self.page_names("/?sort=newest&page=2")
        three = self.page_names("/?sort=newest&page=3")
        self.assertEqual((len(one), len(two), len(three)), (16, 16, 8))
        self.assertEqual(len(set(one + two + three)), 40)    # none repeated, none missing

    def test_sixteen_or_fewer_matches_show_without_pagination(self):
        self.make(16)
        response = self.client.get("/?sort=newest")
        self.assertEqual(len(names(response)), 16)
        self.assertNotContains(response, 'class="pagination"')

    def test_seventeen_matches_show_pagination(self):
        self.make(17)
        response = self.client.get("/?sort=newest")
        self.assertContains(response, 'class="pagination"')
        self.assertEqual(len(names(response)), 16)

    def test_search_can_find_a_bag_picked_beyond_the_limit(self):
        for i in range(1, 16):
            make_bag(f"Pick {i:02d}", featured=i)            # 15 picked, only 12 fit on Page 1
        self.assertEqual(self.page_names("/?q=Pick 15"), ["Pick 15"])
        self.assertEqual(len(self.page_names("/?q=Pick")), 15)

    def test_page_links_keep_every_filter_and_search(self):
        gym = Category.objects.create(name="Gym")
        for i in range(1, 31):
            make_bag(f"Gym Bag {i:02d}", price=20000 + i * 1000, stock=3, category=gym)
        make_bag("Gym Bag Sold Out", price=25000, stock=0, category=gym)
        make_bag("Other Thing", price=30000, category=gym)

        base = "/?category=Gym&q=Bag&in_stock=1&min_price=21000&max_price=48000&sort=price_asc"
        first = self.client.get(base)
        html = first.content.decode()

        links = re.findall(r'href="(\?[^"]*page=\d+[^"]*)"', html)
        self.assertTrue(links)
        for link in links:
            query = parse_qs(urlparse(link.replace("&amp;", "&")).query)
            self.assertEqual(query["category"], ["Gym"])
            self.assertEqual(query["q"], ["Bag"])
            self.assertEqual(query["in_stock"], ["1"])
            self.assertEqual(query["min_price"], ["21000"])
            self.assertEqual(query["max_price"], ["48000"])
            self.assertEqual(query["sort"], ["price_asc"])

        # Follow "next": it is page 2 of the SAME filtered, sorted list
        next_link = re.search(r'rel="next"\s+href="([^"]+)"', html).group(1).replace("&amp;", "&")
        second = self.client.get("/" + next_link)
        everything = list(
            Bag.objects.filter(
                category__name="Gym", name__icontains="Bag", stock__gt=0,
                price__gte=21000, price__lte=48000,
            ).order_by("price", "id").values_list("name", flat=True)
        )
        self.assertEqual(len(everything), 28)
        self.assertEqual(names(first) + names(second), everything[:16] + everything[16:32])
        self.assertEqual(second.context["page_obj"].number, 2)
        self.assertEqual(second.context["result_count"], 28)

    def test_order_is_stable_when_prices_tie(self):
        self.make(30, price=40000)                          # every price identical
        seen = []
        for page in (1, 2):
            seen += self.page_names(f"/?sort=price_asc&page={page}")
        self.assertEqual(len(seen), 30)
        self.assertEqual(len(set(seen)), 30)

    def test_name_sort_runs_across_pages(self):
        self.make(20)
        joined = self.page_names("/?sort=name_asc") + self.page_names("/?sort=name_asc&page=2")
        self.assertEqual(joined, sorted(joined))
        self.assertEqual(len(joined), 20)

    def test_bad_page_numbers_do_not_break_the_page(self):
        self.make(25)
        self.assertEqual(self.client.get("/?sort=newest&page=abc").context["page_obj"].number, 1)
        self.assertEqual(self.client.get("/?sort=newest&page=999").context["page_obj"].number, 2)
        self.assertEqual(self.client.get("/?sort=newest&page=0").status_code, 200)
        self.assertEqual(self.client.get("/?sort=newest&page=-2").status_code, 200)

    def test_all_links_stay_on_the_homepage(self):
        make_bag("A Bag", category=Category.objects.create(name="Gym"))
        html = self.client.get("/?category=Gym").content.decode()
        pills = re.findall(r'class="category-filter-link[^"]*"', html)
        self.assertTrue(pills)
        hrefs = re.findall(r'href="(/\?[^"]*)"\s+class="category-filter-link', html)
        self.assertEqual(len(hrefs), len(pills))
        self.assertFalse(any("page=" in href for href in hrefs))     # a new filter starts at page 1
        self.assertRegex(html, r'href="/"\s+class="text-link"')       # "Clear filters"
        self.assertNotIn("/collection/", html)

    def test_filters_work_on_the_homepage(self):
        gym = Category.objects.create(name="Gym")
        make_bag("Cheap Gym", price=10000, category=gym)
        make_bag("Pricey Gym", price=200000, category=gym, stock=0)
        make_bag("Travel Thing", price=50000)
        self.assertEqual(set(self.page_names("/?category=Gym")), {"Cheap Gym", "Pricey Gym"})
        self.assertEqual(self.page_names("/?q=travel"), ["Travel Thing"])
        self.assertEqual(self.page_names("/?in_stock=1&category=Gym"), ["Cheap Gym"])
        self.assertEqual(self.page_names("/?min_price=100000"), ["Pricey Gym"])
        self.assertEqual(self.page_names("/?max_price=10000"), ["Cheap Gym"])

    def test_filter_forms_start_again_from_page_one(self):
        self.make(25)
        html = self.client.get("/?page=2&sort=price_asc").content.decode()
        forms = re.findall(r'<form method="get" action="/"[^>]*>.*?</form>', html, re.S)
        self.assertEqual(len(forms), 2)
        for form in forms:
            self.assertNotIn('name="page"', form)

    def test_the_menu_links_to_the_homepage(self):
        Category.objects.create(name="Gym")
        html = self.client.get("/").content.decode()
        self.assertIn('href="/"', html)
        self.assertIn('href="/?category=Gym"', html)
        self.assertNotIn("/collection/", html)


class FiveHundredBagTests(TestCase):
    """500 bags, 12 picked: 488 left = Page 1 (12) + pages 2-31 (16 each) + page 32 (8)."""

    @classmethod
    def setUpTestData(cls):
        bags = make_many(500)
        spread_created_at(bags)
        picks = bags[5::41][:12]                                     # 12 bags scattered through the shop
        for position, bag in enumerate(reversed(picks), start=1):    # positions run against the id order
            Bag.objects.filter(pk=bag.pk).update(show_on_homepage=True, homepage_order=position)
        picked = {bag.id for bag in picks}
        cls.picked_ids = [bag.id for bag in reversed(picks)]         # Page 1, in position order
        cls.later_ids = [
            bag.id
            for bag in sorted(bags, key=lambda b: (b.created_at, b.id), reverse=True)
            if bag.id not in picked
        ]
        cls.all_ids = {bag.id for bag in bags}

    def test_pages_are_12_then_16_each_then_8(self):
        sizes, seen = [], []
        for number in range(1, 33):
            response = self.client.get("/", {"page": number})
            self.assertEqual(response.context["page_obj"].number, number)
            sizes.append(len(response.context["bags"]))
            seen.append(ids(response))
        self.assertEqual(sizes, [12] + [16] * 30 + [8])
        self.assertEqual(response.context["page_obj"].paginator.num_pages, 32)

        self.assertEqual(seen[0], self.picked_ids)                   # Page 1 = the picked bags, in order
        later = [bag_id for page in seen[1:] for bag_id in page]
        self.assertEqual(later, self.later_ids)                      # the rest: newest first
        everything = seen[0] + later
        self.assertEqual(len(everything), 500)                       # none skipped ...
        self.assertEqual(len(set(everything)), 500)                  # ... and none repeated
        self.assertEqual(set(everything), self.all_ids)

    def test_the_page_bar_stays_short(self):
        dots = "\u2026"
        self.assertEqual(bar_text(self.client.get("/")), f"Prev 1 2 {dots} 32 Next")
        self.assertEqual(bar_text(self.client.get("/?page=4")), f"Prev 1 2 3 4 5 {dots} 32 Next")
        self.assertEqual(bar_text(self.client.get("/?page=16")), f"Prev 1 {dots} 15 16 17 {dots} 32 Next")
        self.assertEqual(bar_text(self.client.get("/?page=29")), f"Prev 1 {dots} 28 29 30 31 32 Next")
        self.assertEqual(bar_text(self.client.get("/?page=32")), f"Prev 1 {dots} 31 32 Next")


class LargeShopQueryTests(TestCase):
    """1,000+ bags: a page counts the shop and reads one slice. It never loads every bag."""

    @classmethod
    def setUpTestData(cls):
        bags = make_many(1200)
        for position, bag in enumerate(bags[::97][:12], start=1):
            Bag.objects.filter(pk=bag.pk).update(show_on_homepage=True, homepage_order=position)

    def setUp(self):
        # A visitor's first request also creates their session (4 extra queries).
        # Do that now, so the checks below only measure the catalogue itself.
        self.client.get("/cart/")

    def check_queries(self, url):
        """Load `url` and check that every query that reads bags is a COUNT or has a LIMIT."""
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)

        queries = [q["sql"] for q in captured.captured_queries]
        reading_bags = [sql for sql in queries if '"store_bag"' in sql]
        for sql in reading_bags:
            self.assertTrue(
                "COUNT(" in sql or " LIMIT " in sql,
                f"{url} reads bags without a LIMIT: {sql[:200]}",
            )
        self.assertEqual(sum("COUNT(" in sql for sql in reading_bags), 1, url)   # one COUNT(*) ...
        self.assertLessEqual(len(reading_bags), 3, url)    # ... Page 1's picks, and one LIMIT/OFFSET page
        self.assertLessEqual(len(queries), 8, url)         # nothing runs once per bag
        self.assertLessEqual(len(response.context["bags"]), 16, url)
        return response

    def test_every_page_reads_only_a_count_and_a_limited_slice(self):
        for url in (
            "/", "/?page=2", "/?page=38", "/?page=76",
            "/?q=Bag", "/?q=Bag&page=40", "/?sort=price_asc&page=75",
            "/?category=Everyday&in_stock=1&page=3",
        ):
            self.check_queries(url)

    def test_the_page_count_matches_the_shop(self):
        # 1,200 bags - 12 picked = 1,188 left = 74 pages of 16 + 1 page of 4, plus Page 1
        home = self.check_queries("/")
        self.assertEqual(home.context["page_obj"].paginator.num_pages, 76)
        self.assertEqual(home.context["result_count"], 1200)
        self.assertEqual(len(self.check_queries("/?page=76").context["bags"]), 4)
        self.assertEqual(self.check_queries("/?page=999").context["page_obj"].number, 76)

        searched = self.check_queries("/?q=Bag")                    # every bag matches: 75 pages of 16
        self.assertEqual(searched.context["result_count"], 1200)
        self.assertEqual(searched.context["page_obj"].paginator.num_pages, 75)


class CollectionRedirectTests(TestCase):
    """The old /collection/ address sends everyone to the homepage and keeps the query string."""

    def test_collection_redirects_to_the_homepage(self):
        response = self.client.get("/collection/")
        self.assertRedirects(response, "/", status_code=302, fetch_redirect_response=False)

    def test_the_options_and_page_number_are_kept(self):
        response = self.client.get("/collection/?category=Gym&q=a%20b&sort=price_asc&page=2")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/?category=Gym&q=a%20b&sort=price_asc&page=2")

    def test_following_the_redirect_lands_on_the_catalogue(self):
        make_bag("Gym One", category=Category.objects.create(name="Gym"))
        response = self.client.get("/collection/?category=Gym", follow=True)
        self.assertEqual(response.redirect_chain, [("/?category=Gym", 302)])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(names(response), ["Gym One"])

    def test_no_page_links_to_the_old_address(self):
        bag = make_bag("A Bag", featured=1)
        for url in ("/", "/?page=2", "/?q=Bag", "/cart/", f"/bag/{bag.id}/"):
            self.assertNotContains(self.client.get(url), "/collection/", msg_prefix=url)
        self.assertContains(
            self.client.get("/cart/"), 'href="/" class="button-secondary">View collection</a>'
        )


class ProductCardTests(TestCase):
    """3: the image, the name and the price all open the product page."""

    def setUp(self):
        self.client = Client()
        self.bag = make_bag("Linked Bag", price=70000, featured=1)

    def check_card(self, url):
        html = self.client.get(url).content.decode()
        link = f"/bag/{self.bag.id}/"
        self.assertGreaterEqual(html.count(f'href="{link}"'), 2, url)
        # the name and price sit inside a link to the product page
        meta = re.search(
            r'<a href="%s" class="product-meta">(.*?)</a>' % re.escape(link), html, re.S
        )
        self.assertIsNotNone(meta, url)
        self.assertIn("Linked Bag", meta.group(1))
        self.assertIn("UGX 70,000", meta.group(1))
        # and the image links there too
        self.assertRegex(html, r'<a\s+href="%s"\s+class="product-image"' % re.escape(link))

    def test_homepage_cards_link_to_the_product(self):
        self.check_card("/")

    def test_later_page_cards_link_to_the_product(self):
        Bag.objects.filter(pk=self.bag.pk).update(show_on_homepage=False)   # now it sits on Page 2
        self.check_card("/?page=2")

    def test_cards_link_to_the_product_while_browsing_too(self):
        self.check_card("/?q=Linked")


class StockDisplayTests(TestCase):
    """5: out-of-stock bags stay visible and are clearly marked."""

    def setUp(self):
        self.client = Client()
        self.out = make_bag("Gone Bag", stock=0, featured=1)
        # different categories, so the product pages do not list each other
        self.low = make_bag(
            "Plenty Bag", stock=9, featured=2,
            category=Category.objects.create(name="Premium"),
        )
        self.sibling = make_bag("Sibling Bag", stock=3)     # same category as Gone Bag

    def test_out_of_stock_bag_is_visible_and_labelled_everywhere(self):
        for url in ("/", "/?sort=newest", "/?q=Gone"):
            response = self.client.get(url)
            self.assertIn("Gone Bag", names(response), url)
            self.assertContains(response, "OUT OF STOCK")

    def test_in_stock_bags_are_not_labelled(self):
        html = self.client.get("/?q=Plenty").content.decode()
        self.assertNotIn("OUT OF STOCK", html)

    def test_product_page_marks_it_and_disables_the_button(self):
        response = self.client.get(f"/bag/{self.out.id}/")
        self.assertContains(response, "OUT OF STOCK")
        self.assertContains(response, 'class="pdp-add-to-cart disabled" disabled')
        self.assertNotContains(response, "Sold out")
        self.assertNotContains(response, f"/cart/add/{self.out.id}/")

    def test_product_page_for_an_in_stock_bag_still_offers_add_to_cart(self):
        response = self.client.get(f"/bag/{self.low.id}/")
        self.assertContains(response, f"/cart/add/{self.low.id}/")
        self.assertNotContains(response, "OUT OF STOCK")

    def test_related_products_mark_out_of_stock_bags(self):
        response = self.client.get(f"/bag/{self.sibling.id}/")      # lists Gone Bag
        self.assertContains(response, "related-product-stock")
        self.assertContains(response, "OUT OF STOCK")

    def test_in_stock_filter_is_the_only_thing_that_hides_them(self):
        self.assertNotIn("Gone Bag", names(self.client.get("/?in_stock=1")))
        self.assertIn("Gone Bag", names(self.client.get("/")))
        self.assertIn("Gone Bag", names(self.client.get("/?sort=newest")))


class CartStockTests(TestCase):
    """5: customers can never add quantities that are not available."""

    def setUp(self):
        self.client = Client()
        self.bag = make_bag("Limited Bag", stock=2)
        self.out = make_bag("Empty Bag", stock=0)

    def cart_contents(self):
        return dict(self.client.session.get("cart", {}))

    def last_message(self, response):
        return [str(m) for m in response.context["messages"]]

    def test_out_of_stock_bag_cannot_be_added(self):
        response = self.client.post(f"/cart/add/{self.out.id}/", follow=True)
        self.assertEqual(self.cart_contents(), {})           # not even an empty entry
        self.assertIn("EMPTY BAG IS OUT OF STOCK.", self.last_message(response))
        self.assertNotIn("EMPTY BAG ADDED TO BAG", self.last_message(response))

    def test_adding_stops_at_the_available_quantity(self):
        self.client.post(f"/cart/add/{self.bag.id}/")
        self.client.post(f"/cart/add/{self.bag.id}/")
        response = self.client.post(f"/cart/add/{self.bag.id}/", follow=True)
        self.assertEqual(self.cart_contents(), {str(self.bag.id): 2})
        self.assertTrue(any("ONLY 2" in m for m in self.last_message(response)))

    def test_a_successful_add_says_so(self):
        response = self.client.post(f"/cart/add/{self.bag.id}/", follow=True)
        self.assertIn("LIMITED BAG ADDED TO BAG", self.last_message(response))
        self.assertEqual(self.cart_contents(), {str(self.bag.id): 1})

    def test_the_plus_button_cannot_go_past_the_stock(self):
        self.client.post(f"/cart/add/{self.bag.id}/")
        self.client.post(f"/cart/increase/{self.bag.id}/")
        response = self.client.post(f"/cart/increase/{self.bag.id}/", follow=True)
        self.assertEqual(self.cart_contents(), {str(self.bag.id): 2})
        self.assertIn("NO MORE LIMITED BAG IN STOCK.", self.last_message(response))

    def test_stock_that_sells_out_while_in_a_cart_is_removed(self):
        self.client.post(f"/cart/add/{self.bag.id}/")
        Bag.objects.filter(id=self.bag.id).update(stock=0)
        response = self.client.get("/cart/")
        self.assertNotContains(response, "Limited Bag")


class HomepageAdminTests(TestCase):
    """1: the owner controls the homepage from the admin."""

    def setUp(self):
        self.client = Client()
        User.objects.create_superuser("owner", "owner@example.com", PASSWORD)
        self.client.login(username="owner", password=PASSWORD)

    def changelist(self, query=""):
        return self.client.get("/admin/store/bag/" + query, follow=True)

    def messages(self, response):
        return [str(m) for m in response.context["messages"]]

    # -- the model ------------------------------------------------------------

    def test_new_bags_are_not_featured_by_default(self):
        bag = make_bag("Fresh")
        self.assertFalse(bag.show_on_homepage)

    def test_a_featured_bag_needs_a_position(self):
        bag = make_bag("Needs Position")
        bag.show_on_homepage = True
        bag.homepage_order = 0
        with self.assertRaises(ValidationError) as caught:
            bag.full_clean()
        self.assertIn("homepage_order", caught.exception.message_dict)

        bag.homepage_order = 4
        bag.full_clean()                                       # fine now

    def test_an_unfeatured_bag_does_not_need_a_position(self):
        make_bag("Plain").full_clean()

    # -- the list -------------------------------------------------------------

    def test_changelist_loads_and_lists_the_homepage_columns(self):
        make_bag("Listed", stock=0, featured=1)
        response = self.changelist()
        self.assertEqual(response.status_code, 200)
        for text in ("Show on homepage", "Homepage position", "OUT OF STOCK"):
            self.assertContains(response, text)

    def test_featured_bags_are_listed_first_in_homepage_order(self):
        make_bag("Zzz Not Featured")
        second = make_bag("Second", featured=2)
        first = make_bag("First", featured=1)
        rows = [b.name for b in self.changelist().context["cl"].result_list]
        self.assertEqual(rows[:3], ["First", "Second", "Zzz Not Featured"])

    def test_filters_for_homepage_and_stock_work(self):
        make_bag("On", featured=1)
        make_bag("Off", stock=0)
        pick = lambda q: [b.name for b in self.changelist(q).context["cl"].result_list]
        self.assertEqual(pick("?homepage=yes"), ["On"])
        self.assertEqual(pick("?homepage=no"), ["Off"])
        self.assertEqual(pick("?stock_level=out"), ["Off"])

    def test_warns_when_nothing_is_selected(self):
        make_bag("Lonely")
        self.assertTrue(any("No bags are selected" in m for m in self.messages(self.changelist())))

    def test_shows_how_many_slots_are_left(self):
        for i in range(1, 8):
            make_bag(f"B{i}", featured=i)
        self.assertTrue(any("7 of 12" in m for m in self.messages(self.changelist())))

    def test_warns_when_more_than_twelve_are_selected(self):
        for i in range(1, 14):
            make_bag(f"B{i:02d}", featured=i)
        self.assertTrue(any("only the first 12" in m for m in self.messages(self.changelist())))

    def test_warns_about_repeated_positions(self):
        make_bag("One", featured=3)
        make_bag("Two", featured=3)
        self.assertTrue(any("same position" in m for m in self.messages(self.changelist())))

    # -- editing in the list ---------------------------------------------------

    def save_list(self, rows):
        data = {
            "form-TOTAL_FORMS": str(len(rows)), "form-INITIAL_FORMS": str(len(rows)),
            "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000", "_save": "Save",
        }
        for i, (bag, featured, position) in enumerate(rows):
            data[f"form-{i}-id"] = str(bag.id)
            data[f"form-{i}-stock"] = str(bag.stock)
            data[f"form-{i}-homepage_order"] = str(position)
            if featured:
                data[f"form-{i}-show_on_homepage"] = "on"
        return self.client.post("/admin/store/bag/", data, follow=True)

    def test_ticking_a_bag_and_giving_it_a_position_features_it(self):
        bag = make_bag("Pick Me")
        self.save_list([(bag, True, 5)])
        bag.refresh_from_db()
        self.assertTrue(bag.show_on_homepage)
        self.assertEqual(bag.homepage_order, 5)

    def test_ticking_a_bag_without_a_position_is_refused(self):
        bag = make_bag("No Position")
        response = self.save_list([(bag, True, 0)])
        bag.refresh_from_db()
        self.assertFalse(bag.show_on_homepage)
        self.assertContains(response, "Give this bag a homepage position")

    def test_swapping_two_positions_in_one_save_works(self):
        a, b = make_bag("A", featured=1), make_bag("B", featured=2)
        self.save_list([(a, True, 2), (b, True, 1)])
        self.assertEqual(names(self.client.get("/")), ["B", "A"])

    # -- bulk actions ----------------------------------------------------------

    def run_action(self, action, bags):
        return self.client.post("/admin/store/bag/", {
            "action": action, "_selected_action": [str(b.id) for b in bags],
        }, follow=True)

    def test_action_appends_bags_to_the_end_of_the_homepage(self):
        make_bag("Existing", featured=4)
        new = [make_bag("New 1"), make_bag("New 2")]
        self.run_action("add_to_homepage", new)
        self.assertEqual(names(self.client.get("/")), ["Existing", "New 1", "New 2"])

    def test_action_refuses_to_go_past_twelve(self):
        for i in range(1, 12):
            make_bag(f"B{i:02d}", featured=i)
        extra = [make_bag("Extra 1"), make_bag("Extra 2")]
        response = self.run_action("add_to_homepage", extra)
        self.assertTrue(any("room for 1 more" in m for m in self.messages(response)))
        self.assertEqual(Bag.objects.filter(show_on_homepage=True).count(), 11)

    def test_action_removes_bags_from_the_homepage(self):
        keep, drop = make_bag("Keep", featured=1), make_bag("Drop", featured=2)
        self.run_action("remove_from_homepage", [drop])
        self.assertEqual(names(self.client.get("/")), ["Keep"])
        drop.refresh_from_db()
        self.assertFalse(drop.show_on_homepage)


# ===========================================================================
# THE FIXED CATEGORY LIST (A TO Z), THE HEALTH CHECK AND THE FAVICON
# ===========================================================================

CATEGORY_LIST = [
    "Briefcases",
    "Camera Bags",
    "Crossbody Bags",
    "Duffle Bags",
    "Gym Bags",
    "Handbags",
    "Kids Bags",
    "Laptop Bags",
    "Luggage Bags",
    "Lunchbox Bags",
    "Marathon Kit Bags",
    "Suit Carriers",
    "Suitcase Sets",
    "Suitcase Single",
    "Tote Bags",
]

fixed_category_migration = importlib.import_module(
    "store.migrations.0012_fixed_category_list"
)


def run_category_migration():
    """Run the data part of migration 0012 now, and return what it printed."""
    printed = io.StringIO()
    with redirect_stdout(printed):
        fixed_category_migration.set_categories(
            django_apps, SimpleNamespace(connection=connection)
        )
    return printed.getvalue()


class FixedCategoryListTests(TestCase):
    """The shop has the 15 categories the owner chose, and always lists them A to Z."""

    def test_a_new_database_has_exactly_the_fifteen_categories(self):
        self.assertEqual(
            list(Category.objects.values_list("name", flat=True)), CATEGORY_LIST
        )
        self.assertEqual(CATEGORY_LIST, sorted(CATEGORY_LIST))

    def test_the_admin_calls_them_categories(self):
        self.assertEqual(str(Category._meta.verbose_name_plural), "categories")

    def test_the_menu_and_the_filter_buttons_list_them_a_to_z(self):
        response = self.client.get("/")
        self.assertEqual([c.name for c in response.context["categories"]], CATEGORY_LIST)
        self.assertEqual([c.name for c in response.context["nav_categories"]], CATEGORY_LIST)

        links = [
            unquote(name)
            for name in re.findall(r'href="/\?category=([^"&]+)"', response.content.decode())
        ]
        self.assertEqual(list(dict.fromkeys(links)), CATEGORY_LIST)      # in this order, first to last

    def test_a_category_added_later_slots_into_the_order(self):
        Category.objects.create(name="Backpacks")
        Category.objects.create(name="Wallets")
        names = [c.name for c in self.client.get("/").context["categories"]]
        self.assertEqual(names[0], "Backpacks")
        self.assertEqual(names[-1], "Wallets")
        self.assertEqual(names, sorted(names))

    def test_filtering_by_a_new_category_name_works(self):
        make_bag("Gym Thing", category=Category.objects.get(name="Gym Bags"))
        make_bag("Tote Thing", category=Category.objects.get(name="Tote Bags"))
        response = self.client.get("/", {"category": "Gym Bags"})
        self.assertEqual(names(response), ["Gym Thing"])
        self.assertContains(response, '<h1 class="shop-title">Gym Bags</h1>')


class FixedCategoryMigrationTests(TestCase):
    """Moving an older shop onto the fixed list without losing a bag."""

    def setUp(self):
        Category.objects.all().delete()          # start from an older shop's own messy list

    def bag_in(self, category, name):
        return Bag.objects.create(name=name, category=category, price=50000, stock=3)

    def category_names(self):
        return list(Category.objects.values_list("name", flat=True))

    def test_an_empty_shop_gets_the_fifteen_categories(self):
        self.assertEqual(run_category_migration(), "")
        self.assertEqual(self.category_names(), CATEGORY_LIST)

    def test_old_names_that_mean_a_new_category_are_renamed(self):
        gym = Category.objects.create(name="Gym")
        tote = Category.objects.create(name="tote")
        carriers = Category.objects.create(name="suit carrier")
        sets = Category.objects.create(name="suitecase sets")        # the spelling the owner typed
        gym_bag = self.bag_in(gym, "Gym One")

        self.assertEqual(run_category_migration(), "")

        for category, new_name in (
            (gym, "Gym Bags"), (tote, "Tote Bags"),
            (carriers, "Suit Carriers"), (sets, "Suitcase Sets"),
        ):
            category.refresh_from_db()
            self.assertEqual(category.name, new_name)                # same category, new name

        gym_bag.refresh_from_db()
        self.assertEqual(gym_bag.category_id, gym.id)                # the bag did not move
        self.assertEqual(self.category_names(), CATEGORY_LIST)

    def test_two_old_categories_with_the_same_meaning_are_merged(self):
        first = Category.objects.create(name="Gym")
        second = Category.objects.create(name="gym bag")
        self.bag_in(first, "Gym One")
        self.bag_in(second, "Gym Two")

        run_category_migration()

        merged = Category.objects.get(name="Gym Bags")
        self.assertEqual(
            set(Bag.objects.filter(category=merged).values_list("name", flat=True)),
            {"Gym One", "Gym Two"},
        )
        self.assertEqual(self.category_names(), CATEGORY_LIST)

    def test_a_duplicated_new_category_is_merged(self):
        one = Category.objects.create(name="Handbags")
        two = Category.objects.create(name="Handbags")
        self.bag_in(one, "Lady One")
        self.bag_in(two, "Lady Two")

        run_category_migration()

        self.assertEqual(Category.objects.filter(name="Handbags").count(), 1)
        self.assertEqual(Bag.objects.filter(category__name="Handbags").count(), 2)
        self.assertEqual(self.category_names(), CATEGORY_LIST)

    def test_empty_old_categories_are_removed(self):
        Category.objects.create(name="Women")
        Category.objects.create(name="Everyday")
        self.assertEqual(run_category_migration(), "")
        self.assertEqual(self.category_names(), CATEGORY_LIST)

    def test_an_old_category_that_still_holds_bags_is_kept_and_reported(self):
        backpack = Category.objects.create(name="Backpack")          # no new category fits
        self.bag_in(backpack, "Pack A")
        self.bag_in(backpack, "Pack B")

        printed = run_category_migration()

        self.assertIn("Backpack (2 bags)", printed)
        self.assertEqual(self.category_names(), ["Backpack"] + CATEGORY_LIST)
        self.assertEqual(Bag.objects.filter(category=backpack).count(), 2)   # nothing lost

    def test_running_it_twice_changes_nothing(self):
        gym = Category.objects.create(name="Gym")
        self.bag_in(gym, "Gym One")
        run_category_migration()
        before = list(Category.objects.values_list("id", "name"))

        self.assertEqual(run_category_migration(), "")

        self.assertEqual(list(Category.objects.values_list("id", "name")), before)


class HealthCheckTests(TestCase):
    """/healthz/ is what an uptime monitor opens to keep a free Render site awake."""

    def test_it_answers_ok_without_touching_the_database(self):
        with self.assertNumQueries(0):
            response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")
        self.assertEqual(response["Content-Type"], "text/plain")

    def test_it_is_never_cached(self):
        self.assertIn("no-store", self.client.get("/healthz/")["Cache-Control"])

    def test_monitors_that_use_head_get_a_200_too(self):
        self.assertEqual(self.client.head("/healthz/").status_code, 200)

    def test_it_only_answers_get_and_head(self):
        self.assertEqual(self.client.post("/healthz/").status_code, 405)


class FaviconTests(TestCase):
    """The tab icon and the iPhone home-screen icon."""

    def fetch(self, url):
        response = self.client.get(url)
        data = b"".join(response.streaming_content)
        response.close()
        return response, data

    def test_the_tab_icon_is_served_at_favicon_ico(self):
        response, data = self.fetch("/favicon.ico")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/x-icon")
        self.assertEqual(data[:4], b"\x00\x00\x01\x00")               # the .ico file signature
        sizes = Image.open(io.BytesIO(data)).ico.sizes()
        self.assertTrue({(16, 16), (32, 32), (48, 48)} <= set(sizes))

    def test_the_iphone_icon_is_a_180px_png(self):
        response, data = self.fetch("/apple-touch-icon.png")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(Image.open(io.BytesIO(data)).size, (180, 180))

    def test_the_icons_can_be_cached(self):
        response, _ = self.fetch("/favicon.ico")
        self.assertIn("max-age=", response["Cache-Control"])

    def test_every_page_links_to_the_icons(self):
        bag = make_bag("Icon Bag", featured=1)
        for url in ("/", "/?page=2", "/cart/", f"/bag/{bag.id}/", "/login/"):
            html = self.client.get(url, follow=True).content.decode()
            self.assertIn('<link rel="icon" href="/favicon.ico">', html, url)
            self.assertIn(
                '<link rel="apple-touch-icon" href="/apple-touch-icon.png">', html, url
            )

    def test_an_unknown_icon_name_is_a_404(self):
        request = RequestFactory().get("/nope.png")
        for name in ("nope.png", "../models.py"):
            with self.assertRaises(Http404):
                views.site_icon(request, name)