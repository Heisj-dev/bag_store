from .models import Bag


class Cart:

    def __init__(self, request):

        self.session = request.session

        cart = self.session.get("cart")

        if cart is None:
            cart = self.session["cart"] = {}

        self.cart = cart


    def add(self, bag, quantity=1):

        bag_id = str(bag.id)

        if bag_id not in self.cart:
            self.cart[bag_id] = 0

        new_quantity = self.cart[bag_id] + quantity

        if new_quantity <= bag.stock:

            self.cart[bag_id] = new_quantity

            self.session.modified = True


    def increase(self, bag):

        bag_id = str(bag.id)

        if bag_id in self.cart:

            current_quantity = self.cart[bag_id]

            if current_quantity < bag.stock:

                self.cart[bag_id] += 1

                self.session.modified = True


    def decrease(self, bag):

        bag_id = str(bag.id)

        if bag_id in self.cart:

            if self.cart[bag_id] > 1:

                self.cart[bag_id] -= 1

                self.session.modified = True


    def remove(self, bag):

        bag_id = str(bag.id)

        if bag_id in self.cart:

            del self.cart[bag_id]

            self.session.modified = True


    def __iter__(self):

        bag_ids = self.cart.keys()

        bags = Bag.objects.filter(id__in=bag_ids)

        for bag in bags:

            bag_id = str(bag.id)

            quantity = self.cart[bag_id]

            if quantity > bag.stock:

                quantity = bag.stock

                self.cart[bag_id] = quantity

                self.session.modified = True

            yield {
                "bag": bag,
                "quantity": quantity,
                "price": bag.price,
                "total":bag.price * quantity,
            }


    def get_total_price(self):

        total = 0

        for item in self:

            total += item["price"] * item["quantity"]

        return total