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

## Installation & Setup

### 1. Clone the repository and enter the project folder
```bash
git clone [https://github.com/Heisj-dev/bag_store.git](https://github.com/Heisj-dev/bag_store.git)
cd bag_store