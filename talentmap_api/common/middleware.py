
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
