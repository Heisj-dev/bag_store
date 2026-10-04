from .models import Bag


class Cart:

    def __init__(self, request):

        self.session = request.session

        cart = self.session.get("cart")

        if cart is None:
            cart = self.session["cart"] = {}

        self.cart = cart


    def add(self, bag, quantity=1):
        """
        Add a bag to the cart, never beyond the stock available.
        Returns True if it was added, False if it was refused.
        """

        bag_id = str(bag.id)

        new_quantity = self.cart.get(bag_id, 0) + quantity

        if new_quantity > bag.stock:
            # Nothing is stored, so an out-of-stock bag never leaves an
            # empty entry behind in the cart.
            return False

        self.cart[bag_id] = new_quantity
        self.session.modified = True

        return True

    def increase(self, bag):
        """One more of a bag already in the cart. False if stock ran out."""

        bag_id = str(bag.id)

        if bag_id in self.cart:

            current_quantity = self.cart[bag_id]

            if current_quantity < bag.stock:
                self.cart[bag_id] += 1
                self.session.modified = True
                return True

        return False

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

        bag_ids = list(self.cart.keys())

        bags = Bag.objects.filter(id__in=bag_ids)

        for bag in bags:

            bag_id = str(bag.id)

            quantity = self.cart[bag_id]

            if quantity > bag.stock:

                quantity = bag.stock

            if quantity <= 0:

                del self.cart[bag_id]

                self.session.modified = True

                continue

            if quantity != self.cart[bag_id]:

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