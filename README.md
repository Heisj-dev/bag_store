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

## Categories

The shop has these 15 categories and no others, always listed A to Z in the menu, the filter buttons and the admin:

Briefcases, Camera Bags, Crossbody Bags, Duffle Bags, Gym Bags, Handbags, Kids Bags, Laptop Bags, Luggage Bags, Lunchbox Bags, Marathon Kit Bags, Suit Carriers, Suitcase Sets, Suitcase Single, Tote Bags.

Migration `0012_fixed_category_list` sets them when you run `python manage.py migrate`:

- Old categories that mean the same thing are renamed (for example Gym becomes Gym Bags).
- Empty old categories are removed.
- An old category that still holds bags is kept, so no bag is lost. The migration prints its name. In the admin, open each of those bags, pick one of the 15 categories, then delete the old category.

A category you add later in the admin is still listed A to Z.

---

## Favicon

The tab icon and the iPhone home-screen icon are `favicon.ico` and `apple-touch-icon.png` in `store/static/store/images/`. They are made from the pink bag in the logo and are served at `/favicon.ico` and `/apple-touch-icon.png`. To change them, replace those two files (the .ico holds 16, 32 and 48 px; the iPhone icon is 180 x 180 px).

---

## Keeping the site awake on Render

Render's free web services are spun down after 15 minutes without a visit. The next visitor waits up to a minute while Render shows its loading page. To stop that:

1. **Free: have a monitor open the site every 5 minutes.** `/healthz/` is a tiny page made for this: it answers `ok` and never touches the database.
   - Make a free account at uptimerobot.com (its free plan checks every 5 minutes).
   - Add a new monitor of type **HTTP(s)** with the URL `https://YOUR-SITE.onrender.com/healthz/` (use your own domain if you have one) and a 5 minute interval.
   - Open that URL in a browser once: you should see `ok`.
2. **Paid: always on.** Upgrade the service to a paid instance in the Render dashboard (the Starter type is about $7 a month). It is never spun down.

Things to know about option 1:

- Render gives each workspace 750 free instance hours a month. A site that never sleeps runs about 720-744 hours, so it only fits if it is the only free web service in the workspace. If the hours run out, Render suspends all your free web services until the next month.
- Render can still restart a free service now and then, so an occasional slow first visit can still happen.
- If your database is Render's free Postgres, it expires after 30 days (then a 14-day grace period before it is deleted). Upgrade it or move the data before then.

---

## Visitor analytics

Open **Admin > Store > Visitor analytics** (`/admin/store/visitevent/`) and pick Today, 7 days, 30 days, 90 days or All time. It shows:

- visitors, pages viewed, bag pages opened, bags added to the cart, orders and their value;
- the bags people open the most (a bag's page opened is a click on that bag), with how many times each was added to the cart and bought;
- the path from visit to order, where visitors come from, what they search for (red = searches that found no bag: bags your customers want that you do not show), the categories they open, phones versus computers, browsers, and the busiest days and hours (Kampala time).

How it works: a very small script at the end of every page tells the shop about the page view once the page has loaded. No cookie is set and no name or IP address is stored. A visitor is a scrambled code that changes every day, so someone who comes back tomorrow counts as a new visitor. Search engines, link previews, staff (you, while signed in) and browsers that send "Do Not Track" are not counted, and the privacy policy says so.

"Direct" means typed in, or a link from an app that does not say where it came from (WhatsApp often). Add `?utm_source=whatsapp` (or `tiktok`, `instagram`, ...) to the links you share and they appear under their own name.

Events older than 400 days are deleted now and then. To clear them yourself: `python manage.py prune_visits --days 400`.

---

## Search engines (SEO)

What the shop does by itself:

- Every page has its own title and description. The front page, each category (`/category/gym-bags/`) and each bag (`/bag/12/zara-tote/`) has one proper address; the short `/bag/12/` leads to it for good.
- Links shared on WhatsApp, Facebook or TikTok show a title, a description and a picture.
- Google is told about the shop, each bag's price and stock, and the path to each page (structured data).
- `/robots.txt` and `/sitemap.xml` exist. Pages for one customer (cart, checkout, accounts) and search or sorted lists are kept out of search results.

What you do, once:

1. In Render set `SITE_URL=https://bagsnbeyond.com` (your own domain) and `CANONICAL_HOST=bagsnbeyond.com`. The second sends anyone who arrives by the onrender.com address or `www.` to the proper address for good, so Google sees one site and not two copies.
2. Add the site in Google Search Console (search.google.com/search-console) with "URL prefix". Choose the "HTML tag" way to verify and put only the `content` code in Render as `GOOGLE_SITE_VERIFICATION`. Once it is verified, open Sitemaps and submit `sitemap.xml`. (`BING_SITE_VERIFICATION` does the same for Bing Webmaster Tools.)
3. In **Admin > Categories** write a Description for each category in your own words: it becomes the text under the category's heading and its description in Google. Write a Description for every bag too, and upload clear photos.
4. Share the category and bag addresses (not search results), and make a Google Business Profile and social profiles with the same name, phone number and link.

Google decides when and where pages appear. For a new site that takes days to weeks, and nobody can promise a position.

---

## Speed

- Pictures are asked from Cloudinary at the size the screen needs, in the best format the browser can show (WebP or AVIF), instead of the full upload. Phones on mobile data load a fraction of the bytes. Each size and format Cloudinary makes counts toward its monthly free allowance, so keep an eye on your Cloudinary dashboard.
- Only the first bags on a page load at once; the rest load as you scroll.
- The font and the logo no longer hold the page back (the logo is a small WebP).
- Pages are compressed, the category list is kept for a minute instead of being read from the database on every page, and a visitor who has put nothing in the cart gets no session and no cookie.
- Keep Render and your Neon database in the same region (check both dashboards): every page asks the database a few questions, and a long distance adds to each one.

---

## Deploying to Render (with Neon, Brevo and Google sign-in)

**Files the deploy uses:** `build.sh` (installs, collects static files, migrates), `.python-version` (the Python version) and `.gitattributes` (keeps `build.sh` in Unix line endings, which Render needs). The repository must not contain `.env`, `venv/`, `db.sqlite3`, `db_backup.sqlite3`, `data_dump.json`, `media/`, `staticfiles/` or `__pycache__/` (`.gitignore` already skips them). Check with `git ls-files`; if one is listed, run `git rm -r --cached NAME` and commit.

**1. Render service.** New > **Web Service** (not a Static Site), connect the GitHub repository, then set:

- Build Command: `bash build.sh`
- Start Command: `gunicorn bagstore_config.wsgi:application`
- Health Check Path (optional): `/healthz/`
- Do not set a `PYTHON_VERSION` variable: `.python-version` already chooses the Python version.

**2. Environment variables** (Render > the service > Environment):

| Name | Value |
|---|---|
| `SECRET_KEY` | a NEW long random value, never the one in your `.env` |
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | `bagsnbeyond.com,www.bagsnbeyond.com` (your own domain if different; the `onrender.com` address is added automatically) |
| `CSRF_TRUSTED_ORIGINS` | `https://bagsnbeyond.com,https://www.bagsnbeyond.com` |
| `DATABASE_URL` | the Neon connection string (the pooled one is fine) |
| `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` | from Cloudinary |
| `BREVO_API_KEY` | a Brevo API key (it starts with `xkeysib-`). Sends email over HTTPS, so it works on Render's free plan |
| `DEFAULT_FROM_EMAIL` | `Bags & Beyond <orders@bagsnbeyond.com>`, a sender verified in Brevo |
| `ORDER_NOTIFICATION_EMAIL` | where the "NEW BAG STORE ORDER" alerts go |
| `DB_CONN_MAX_AGE` | optional, seconds to keep a database connection (default 60) |
| `SITE_URL` | `https://bagsnbeyond.com`: the shop's one proper address, used in the page tags, shared links and the sitemap |
| `CANONICAL_HOST` | `bagsnbeyond.com`: sends the onrender.com address and `www.` to it for good (leave out until the domain works) |
| `GOOGLE_SITE_VERIFICATION`, `BING_SITE_VERIFICATION` | the codes Google Search Console and Bing give you, optional |

Render's free plan blocks the SMTP ports (25, 465 and 587), so email over SMTP only works on a paid plan. If you are on a paid plan and prefer SMTP, leave `BREVO_API_KEY` out and set `EMAIL_HOST=smtp-relay.brevo.com`, `EMAIL_PORT=587`, `EMAIL_USE_TLS=True`, `EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD` instead.

**3. Database (Neon).** Before the first deploy, make a backup: a Neon branch or a `pg_dump`. Never upload `db.sqlite3`. The build runs `migrate` on every deploy, which also applies the category list (`0012`) and the cancellation fix (`0013`) to the live data.

**4. First admin account.** The free plan has no Shell, so add `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL` and `DJANGO_SUPERUSER_PASSWORD` in Render for the first deploy only. `build.sh` creates the admin from them, and does nothing if it already exists. Delete the three variables afterwards. Then open `/admin/` and set up the categories, bags and photos, the homepage bags, the Google `SocialApp` and the `Sites` entry (change `example.com` to your domain).

**5. Google sign-in.** In Google Cloud, under the OAuth client, add these Authorized redirect URIs (keep the local one for development):

- `https://bagsnbeyond.com/accounts/google/login/callback/`
- `https://www.bagsnbeyond.com/accounts/google/login/callback/`
- `http://127.0.0.1:8000/accounts/google/login/callback/`

Publish the consent screen (in testing mode only listed test users can sign in) and give it your privacy policy link, `https://bagsnbeyond.com/privacy/`. Then test: Login > Continue with Google > Google > Bags & Beyond > Account.

**6. Email tests (after the first deploy).** Send real ones: password reset, new order (you get the alert, the customer gets "We've got your order"), order confirmed, order shipped, order delivered, order cancelled. Check the spam folder. If an email does not arrive, open Render > Logs: a failed send is written there as "Could not send the email ... through Brevo".

**7. Domain (Namecheap).** Add `bagsnbeyond.com` and `www.bagsnbeyond.com` in Render > Settings > Custom Domains, then in Namecheap > Advanced DNS: remove any old `A` records for `@`, any `AAAA` records and any `www` CNAME or redirect, and add `A` record `@` -> `216.24.57.1` and `CNAME` record `www` -> `YOUR-SERVICE.onrender.com` (TTL 1 minute). Render then issues the HTTPS certificate and redirects HTTP to HTTPS.

**Cancelled orders.** Cancelling an order puts its bags back in stock once (never twice) and emails the customer once. A cancelled order cannot be reopened: create a new order instead.

---

## Installation & Setup

### 1. Clone the repository and enter the project folder
```bash
git clone [https://github.com/Heisj-dev/bag_store.git](https://github.com/Heisj-dev/bag_store.git)
cd bag_store