# Product image sizing correction

This full project includes dark mode and the improved desktop photo sizing.
Clicking a product-detail photo no longer opens or zooms it. The normal gallery arrows and swipe behaviour remain.

Extract over C:\Users\JOSSEN\bag_store, replacing matching files, then run python manage.py check and restart your server. Hard-refresh the browser with Ctrl+F5.

The old photo-viewer.js is replaced with an inactive file and is no longer referenced by the template. No manual deletion is required. No migrations or dependencies are needed.
