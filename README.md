# Bag Store

A minimalist Django-based e-commerce storefront for browsing and purchasing bags.

## Features

- Product catalog with categories, multiple images per product, search, filtering, and sorting
- Session-based shopping cart with stock-safe add/increase/decrease/remove
- Customer accounts: registration, login, password reset/change, order history
- Checkout with delivery details, atomic stock deduction, and order confirmation
- Django admin for managing products, categories, images, and orders


---

## Tech Stack
- **Backend:** Python, Django
- **Database:** SQLite
- **Frontend:** HTML5, CSS3, JavaScript

---

## Authentication

| Address | Purpose |
|---|---|
| `/login/` | The main customer login (email + password) |
| `/accounts/register/` | Create an account |
| `/accounts/logout/` | Log out (the Logout buttons POST here) |
| `/accounts/password-reset/` | "Forgot password?" - sends a reset link by email |
| `/accounts/password/change/` | Change password (logged-in customers) |
| `/accounts/account/` | My account (login required) |
| `/accounts/google/login/` | Starts "Continue with Google" (a POST from the button) |
| `/accounts/google/login/callback/` | Where Google sends the customer back |

`/accounts/login/`, `/accounts/signup/` and `/accounts/password/reset/` (django-allauth's own
pages) redirect to the shop's pages above. django-allauth is used only for Google sign-in.

### Setting up Google sign-in

1. In the Google Cloud console create an OAuth client (type *Web application*) and add the
   authorised redirect URI `https://YOUR-DOMAIN/accounts/google/login/callback/`
   (for local work also `http://127.0.0.1:8000/accounts/google/login/callback/`).
2. In the Django admin go to **Social applications -> Add**: provider *Google*, paste the
   client ID and secret, and move your site into *Chosen sites*.
3. The "Continue with Google" button on the login and register pages only appears once a Google
   app exists, so an unconfigured site never shows a button that cannot work.

Good to know: if someone registered with the form and later signs in with Google using the
same email, they are signed in to the same account and django-allauth clears that account's
old password (the shop does not verify the email typed into the form, so this stops anyone
else from keeping access with a password they chose). The customer can set a new password at
any time from "Forgot password?".

---

## Homepage & collection

**The homepage is Page 1 of a paginated catalogue. You choose Page 1 from the Django admin.**

1. Go to **Admin -> Bags**. Bags that are on the homepage are listed first, in the order customers see them.
2. Tick **Show on homepage** and give the bag a **Homepage position** (1 is first, 2 is second, ...). You can edit both straight from the list and press *Save*.
3. Page 1 shows at most **12** bags, in position order (bags with the same position: newest first). If fewer than 12 are picked, Page 1 shows only those: it is never topped up with other bags. A new bag is never added to Page 1 automatically, and adding one never pushes another out.
4. Two shortcuts in the *Action* menu: **Add selected bags to the end of the homepage** and **Remove selected bags from the homepage**.
5. The list warns you when more than 12 bags are selected, when fewer than 12 are, or when two bags share a position. Use the *Homepage* and *Stock* filters on the right to find bags quickly. A bag picked beyond the 12 limit is not lost: it appears on a later page.

**Page 2, 3, ... (`/?page=2`, `/?page=3`, ...) list every bag that is not on Page 1, 16 per page, newest first.** No bag is skipped or repeated, and a bag shown on Page 1 never comes back. Example: 500 bags with 12 picked leaves 488, which is 32 pages: Page 1 (12 bags), pages 2-31 (16 each) and page 32 (8).

**The page links** (`Prev | 1 | 2 | 3 | ... | Next`) sit under the bags and show only when there is more than one page, that is, when at least one bag is not on Page 1. Each page reads only its own bags from the database (one count plus one `LIMIT`/`OFFSET` query), so it stays fast with thousands of bags.

**Search, category, stock, price and sort list every matching bag** (picked ones too, so a search can always find a bag), 16 per page. The page links keep all of those options, and changing a filter starts again at page 1. Clear the filters and you are back at Page 1.

**`/collection/` redirects to the homepage** (`/`), keeping any search, filter, sort or page number in the address, so old links and bookmarks still work.

**Out-of-stock bags stay visible**, marked **OUT OF STOCK**, and cannot be added to the cart.

---

## Installation & Setup

### 1. Clone the repository and enter the project folder
```bash
git clone [https://github.com/Heisj-dev/bag_store.git](https://github.com/Heisj-dev/bag_store.git)
cd bag_store