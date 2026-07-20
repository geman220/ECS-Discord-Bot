# app/init/error_handlers.py

"""
Error Handlers

HTTP error handlers and exception handling.
Provides secure error responses that don't leak sensitive information.
"""

import logging

from flask import request, redirect, url_for, render_template, session as flask_session, jsonify, Response, g
from werkzeug.routing import BuildError
from werkzeug.routing.exceptions import WebsocketMismatch
from werkzeug.exceptions import HTTPException
from flask_limiter.errors import RateLimitExceeded
from flask_wtf.csrf import CSRFError

from app.alert_helpers import show_error

logger = logging.getLogger(__name__)

# Safe error messages for production (don't leak internal details)
SAFE_ERROR_MESSAGES = {
    400: 'Bad Request',
    401: 'Unauthorized',
    403: 'Forbidden',
    404: 'Not Found',
    405: 'Method Not Allowed',
    408: 'Request Timeout',
    409: 'Conflict',
    413: 'Request Too Large',
    415: 'Unsupported Media Type',
    422: 'Unprocessable Entity',
    429: 'Too Many Requests',
    500: 'Internal Server Error',
    502: 'Bad Gateway',
    503: 'Service Unavailable',
    504: 'Gateway Timeout',
}


def _is_api_request():
    """Check if the current request expects a JSON response."""
    return (
        request.path.startswith('/api/') or
        request.path.startswith('/admin-panel/api/') or
        request.path.startswith('/mobile-api/') or
        request.path.startswith('/external-api/') or
        request.headers.get('Accept', '').startswith('application/json') or
        request.content_type == 'application/json' or
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    )


def _get_safe_error_message(status_code, default='An error occurred'):
    """Get a safe error message that doesn't expose internal details."""
    return SAFE_ERROR_MESSAGES.get(status_code, default)


def _is_public_error_request():
    """True when the error should be branded for the public marketing site.

    Matches the /preview mount (portal-hosted demo) and the live public
    domain. The public pages are self-contained standalone HTML, so they
    render even when the portal shell's context processors can't run.
    """
    path = request.path or ''
    host = (request.host or '').split(':')[0].lower()
    return (
        path == '/preview'
        or path.startswith('/preview/')
        or host in ('ecspubleague.org', 'www.ecspubleague.org')
    )


def _render_error_html(status_code):
    """Render a branded error page, host-aware, with layered fallbacks.

    Public marketing requests get the standalone ``public/<code>.html``;
    everything else gets the portal ``<code>_flowbite.html``. Each render is
    wrapped so a template or session failure (e.g. Redis down) degrades to a
    plain-text body rather than a second exception inside the error handler.
    """
    if _is_public_error_request():
        for template in (f'public/{status_code}.html', 'public/500.html'):
            try:
                return render_template(template), status_code
            except Exception:
                continue
        return _get_safe_error_message(status_code), status_code, {'Content-Type': 'text/plain'}

    for template in (f'{status_code}_flowbite.html', '500_flowbite.html'):
        try:
            return render_template(template), status_code
        except Exception:
            continue
    return _get_safe_error_message(status_code), status_code, {'Content-Type': 'text/plain'}


def _compute_retry_after(error) -> int:
    """Extract Retry-After seconds from a Flask-Limiter exception, fallback to 60.

    ``RateLimitExceeded.limit`` wraps a ``limits.RateLimitItem`` whose
    ``get_expiry()`` returns the window length in seconds — the worst-case
    wait under the fixed-window strategy. Matches what Flask-Limiter itself
    emits in its ``Retry-After`` header.
    """
    try:
        if isinstance(error, RateLimitExceeded) and getattr(error, 'limit', None):
            item = error.limit.limit  # limits.RateLimitItem
            seconds = int(item.get_expiry())
            if seconds > 0:
                return seconds
    except Exception:
        pass
    # Werkzeug TooManyRequests may populate .retry_after on some versions.
    retry = getattr(error, 'retry_after', None)
    if isinstance(retry, (int, float)) and retry > 0:
        return int(retry)
    return 60


def install_error_handlers(app):
    """
    Install custom error handlers with the Flask application.

    Args:
        app: The Flask application instance.
    """

    @app.errorhandler(WebsocketMismatch)
    def handle_websocket_mismatch(error):
        """Handle WebSocket mismatch errors."""
        app.logger.warning(f"WebSocket mismatch for {request.path} - this should be rare now")
        return None

    @app.errorhandler(405)
    def handle_method_not_allowed(error):
        """Handle 405 errors with detailed logging for debugging."""
        app.logger.error(
            f"405 Method Not Allowed: {request.method} {request.url} | "
            f"Valid methods: {error.valid_methods} | "
            f"User-Agent: {request.headers.get('User-Agent', 'unknown')[:100]}"
        )
        if _is_api_request():
            return jsonify({
                'success': False,
                'error': 'Method Not Allowed',
                'detail': f'{request.method} is not allowed for {request.path}',
                'allowed_methods': list(error.valid_methods or []),
                'status_code': 405
            }), 405
        return render_template("500_flowbite.html"), 405

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        """Handle CSRF failures.

        A missing/invalid CSRF token is a client-side condition (400), not a
        server fault — typically scanners POSTing to the site or a stale form.
        Log it at WARNING without a stack trace so it doesn't drown error.log,
        and return the same secure response shape as other 4xx errors.
        """
        app.logger.warning(
            f"CSRF validation failed: {error.description} | "
            f"{request.method} {request.path} | "
            f"User-Agent: {request.headers.get('User-Agent', 'unknown')[:100]}"
        )
        if _is_api_request():
            return jsonify({
                'success': False,
                'error': _get_safe_error_message(400),
                'status_code': 400
            }), 400
        try:
            return render_template("500_flowbite.html"), 400
        except Exception:
            return _get_safe_error_message(400), 400, {'Content-Type': 'text/plain'}

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        """Handle unexpected exceptions with secure error messages."""
        # Log the full error internally (not exposed to user)
        app.logger.error(
            f"Unhandled Exception: {error} | "
            f"{request.method} {request.url}",
            exc_info=True
        )

        # Determine status code
        if isinstance(error, HTTPException):
            status_code = error.code
        else:
            status_code = 500

        # Return JSON for API requests
        if _is_api_request():
            return jsonify({
                'success': False,
                'error': _get_safe_error_message(status_code),
                'status_code': status_code
            }), status_code

        # Return HTML for browser requests. _render_error_html is host-aware
        # (public marketing vs portal) and already layers template → 500 page →
        # plain-text fallbacks for the session-unavailable (Redis down) case.
        return _render_error_html(status_code)

    @app.errorhandler(401)
    def unauthorized(error):
        """Handle unauthorized access."""
        next_url = request.path
        if next_url != '/':
            flask_session['next'] = next_url
        return redirect(url_for('auth.login'))

    @app.errorhandler(403)
    def forbidden(error):
        """Handle 403 forbidden.

        Two very different callers land here: (1) the security middleware
        banning a hostile IP — those get a bare, DB-free response and no
        logging so a scanner flood can't amplify load or drown the logs; and
        (2) legitimate role/permission denials via ``abort(403)`` — those get
        the branded "Access Denied" page so a real user isn't staring at the
        browser's raw 403. The middleware flags its own case on ``g``.
        """
        if _is_api_request():
            return jsonify({
                'success': False,
                'error': 'Forbidden',
                'status_code': 403
            }), 403
        # WAF ban: minimal response, no template, no logging.
        if getattr(g, '_waf_banned', False):
            return '', 403
        return _render_error_html(403)

    # Paths that 404 so often they drown real 404s: browser auto-requests for
    # favicons/apple-touch-icons and the known stale mobile-client prefix
    # /api/v1/v1/... (client-side bug, real fix lives in the RN app).
    QUIET_404_PATHS = (
        '/favicon.ico',
        '/apple-touch-icon.png',
        '/apple-touch-icon-precomposed.png',
        '/apple-touch-icon-120x120.png',
        '/apple-touch-icon-120x120-precomposed.png',
        '/api/v1/v1/',
    )

    static_prefix = (app.static_url_path or '/static') + '/'

    @app.errorhandler(404)
    def not_found(error):
        """Handle 404 not found errors."""
        path = request.path

        # Missing static asset (typically a stale, content-hashed bundle URL that
        # a cached client is still requesting after a redeploy moved it). There's
        # no user-facing page to show a <script>/<link> fetch, and rendering the
        # full 404 template pulls in base_flowbite's context processors — ~13 DB
        # queries and connection checkouts per miss, which under a burst of stale
        # bundle requests is real DB pressure. Answer with a bare, DB-free 404.
        if path.startswith(static_prefix):
            logger.debug(f"404 (static asset): {path}")
            return Response('Not Found', status=404, mimetype='text/plain')

        if any(path == p or path.startswith(p) for p in QUIET_404_PATHS):
            logger.debug(f"404 (suppressed): {path}")
        else:
            logger.warning(f"404 error: {path}")

        # Return JSON for API requests
        if _is_api_request():
            return jsonify({
                'success': False,
                'error': 'Not Found',
                'status_code': 404
            }), 404

        # Branded 404 — public marketing site gets its standalone page, the
        # portal gets its Flowbite page, with plain-text fallback baked in.
        return _render_error_html(404)

    @app.errorhandler(429)
    def handle_too_many_requests(error):
        """Handle 429 with Retry-After derived from the tripped Flask-Limiter rule."""
        retry_after = _compute_retry_after(error)

        if _is_api_request():
            response = jsonify({
                'success': False,
                'error': 'Too Many Requests',
                'message': 'Rate limit exceeded. Please wait before retrying.',
                'retry_after_seconds': retry_after,
                'status_code': 429,
            })
        else:
            try:
                body, _status = _render_error_html(429)[:2]
                response = app.make_response(body)
            except Exception:
                response = app.make_response(('Too Many Requests', 429))

        response.status_code = 429
        response.headers['Retry-After'] = str(retry_after)

        # Preserve Flask-Limiter's X-RateLimit-* headers from the exception.
        if isinstance(error, RateLimitExceeded):
            try:
                for k, v in (error.get_headers() or []):
                    if k.lower() == 'retry-after':
                        continue  # don't clobber our own computed value
                    response.headers.setdefault(k, v)
            except Exception:
                pass

        return response

    @app.errorhandler(BuildError)
    def handle_url_build_error(error):
        """Handle URL build errors."""
        logger.error(f"URL build error: {str(error)}")
        if 'main.index' in str(error):
            try:
                return redirect(url_for('main.index'))
            except:
                return redirect('/')
        show_error('An error occurred while redirecting. You have been returned to the home page.')
        return redirect('/')
