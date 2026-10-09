from django.conf import settings
from django.http import HttpResponsePermanentRedirect

# Pages that belong to one customer or to the owner: never for search results.
PRIVATE_PREFIXES = (
    "/admin/", "/cart/", "/checkout/", "/accounts/", "/login/",
    "/order/", "/orders/", "/v/", "/healthz/",
)


class CanonicalHostMiddleware:
    """
    The shop has one address (CANONICAL_HOST, for example bagsnbeyond.com).
    Visitors who arrive by another one (your-app.onrender.com, www.) are sent
    to it for good, so search engines see one site and not two copies.
    Does nothing while CANONICAL_HOST is empty. The health check is left alone.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        wanted = settings.CANONICAL_HOST

        if (
            wanted
            and request.method in ("GET", "HEAD")
            and request.get_host().split(":")[0].lower() != wanted.lower()
            and not request.path.startswith("/healthz/")
        ):
            return HttpResponsePermanentRedirect(
                f"https://{wanted}{request.get_full_path()}"
            )

        return self.get_response(request)


class PrivatePagesMiddleware:
    """Ask search engines to keep the private pages out of their results."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        response = self.get_response(request)

        if request.path.startswith(PRIVATE_PREFIXES):
            response.headers.setdefault("X-Robots-Tag", "noindex, nofollow")

        return response
