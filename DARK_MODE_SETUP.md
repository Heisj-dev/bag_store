# Bags & Beyond — refined dark mode

## Install
Copy only these three files into the matching locations in C:\Users\JOSSEN\bag_store:

- store/templates/store/base.html (replace)
- store/static/store/css/style.css (replace)
- store/static/store/js/theme.js (new, or replace the first version)

Keep your existing .env, database, uploaded media and virtual environment.
No migrations or new dependencies are required.

Run:
    python manage.py check
    python manage.py runserver

For Render, deploy your changes through your normal Git workflow. Your build must run:
    python manage.py collectstatic --noinput

## How it works
First visit follows the browser/device colour preference. On desktop (900px and wider), the sun/moon switch sits next to the menu icon. On phones and tablets it is at the top of the menu, preserving space for the centred logo and shopping controls. The extra theme row from the first version has been removed.

Menu > Appearance offers Device, Light and Dark. Device follows live device changes; manual settings persist in this browser and synchronize between open tabs. If storage is blocked, switching still works for the current page. Controls have keyboard support and visible focus. Reduced-motion preferences are respected.

Dark mode uses black backgrounds, soft white text and charcoal surfaces. Inputs, validation messages, dropdown suggestions, modal buttons, footer and image arrows have dedicated dark treatments. The original logo mask makes the lettering white while retaining the original pink artwork. Product images are never inverted, tinted or darkened. Light mode retains the original palette.

## Validation
- Ten templates rendered with isolated Django 5.2 settings and synthetic fixture data.
- Chromium checked homepage, product detail, cart, checkout, login, registration and order confirmation at 320, 390, 768 and 1440 pixels in light and dark modes: 56 page/viewport checks; no horizontal overflow.
- Screenshots inspected for desktop storefront/product and mobile menu/cart/checkout/login.
- Additional header collision checks at 900, 1024 and 1440 pixels.
- Browser checks: saved manual choice after reload, radio controls via keyboard, live device changes and cross-tab synchronization.
- Node checks: initial application, device defaults, manual overrides, reset to device, invalid saved values and blocked storage.

Limits: the uploaded archive does not contain product media or a live database. Previews use sample products and image placeholders. External fonts were blocked during isolated visual checks, so the fallback font was displayed. Full Django application/backend tests were not run; no backend code was changed.
