from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from .models import Category, Bag, Order, OrderItem
from django.core import mail
import json
import re
import time
from unittest import mock
from urllib.parse import parse_qs, urlparse

import jwt
import requests
from allauth.socialaccount.models import SocialApp


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
