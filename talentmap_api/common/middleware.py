
class IE11Middleware:
    '''
    Informs the  browser not to use browser-side caching for API responses.
    This resolves an issue where the front end was unable to retrieve fresh data.
    '''

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response['Cache-Control'] = "no-cache,no-store"
        return response


class SecurityHeadersMiddleware:
    '''
    STIG V-220641 / NIST SI-11: Adds defense-in-depth HTTP security headers
    to every response. These supplement Django's built-in SecurityMiddleware
    and XFrameOptionsMiddleware with headers that Django does not set by
    default.
    '''

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Content-Security-Policy: restrict resource loading to same origin
        response['Content-Security-Policy'] = "default-src 'self'; frame-ancestors 'none'"

        # Prevent the browser from MIME-sniffing (belt-and-suspenders with Django setting)
        response['X-Content-Type-Options'] = 'nosniff'

        # Disable browser DNS prefetching to prevent information leakage
        response['X-DNS-Prefetch-Control'] = 'off'

        # Prevent this site from being loaded inside an iframe (defense-in-depth)
        response['X-Frame-Options'] = 'DENY'

        # Disable client-side caching of sensitive responses
        response['Pragma'] = 'no-cache'

        # Referrer policy: only send origin on cross-origin requests
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'

        # Restrict browser features
        response['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'

        return response


class TokenActivityMiddleware:
    '''
    STIG V-220630: Converts the absolute token timeout into an inactivity
    timeout by refreshing the token's ``created`` timestamp on each
    authenticated request.  A cache guard throttles DB writes so the
    timestamp is only updated once per minute per token.
    '''

    REFRESH_INTERVAL_SECONDS = 60  # only write to DB once per minute

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        self._refresh_token(request)
        return response

    def _refresh_token(self, request):
        from django.utils import timezone
        from django.core.cache import cache

        user = getattr(request, 'user', None)
        auth = getattr(request, 'auth', None)

        if user is None or not user.is_authenticated or auth is None:
            return

        # Only act on ExpiringToken instances
        from rest_framework_expiring_authtoken.models import ExpiringToken
        if not isinstance(auth, ExpiringToken):
            return

        cache_key = f'token_refresh_{auth.pk}'
        if cache.get(cache_key):
            return  # Already refreshed recently

        auth.created = timezone.now()
        auth.save(update_fields=['created'])
        cache.set(cache_key, True, self.REFRESH_INTERVAL_SECONDS)
