from django.test import TestCase, Client
from django.contrib.auth.models import User
from .models import Category, Bag, Order, OrderItem
from django.core import mail
import re


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
        self.assertContains(response, "DUFFEL")

    def test_product_detail_404_on_missing_bag(self):
        response = self.client.get("/bag/9999/")
        self.assertEqual(response.status_code, 404)

    def test_category_filter(self):
        response = self.client.get("/?category=Gym")
        self.assertContains(response, "DUFFEL")


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
        self.assertContains(response, "ROLLING DUFFEL")

        self.client.post(f"/cart/add/{self.bag.id}/")

        response = self.client.get("/cart/")
        self.assertContains(response, "ROLLING DUFFEL")

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
