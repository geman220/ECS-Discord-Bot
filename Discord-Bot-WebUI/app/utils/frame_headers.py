# app/utils/frame_headers.py

"""
Canonical frame-embedding policy — the ONE place that decides X-Frame-Options.

Two after_request hooks historically both set frame headers with CONFLICTING
values (security_middleware.py sent DENY, init/middleware.py sent SAMEORIGIN;
whichever ran last won). Both now call frame_headers_for_path() so the result
is identical regardless of hook ordering.

Policy:
- /preview/* — the public site rendered inside the portal. The site editor
  loads these pages in a same-origin iframe as its edit surface, so they may
  be framed by THIS origin only (SAMEORIGIN + CSP frame-ancestors 'self').
- everything else — DENY, as before.
"""


def frame_headers_for_path(path):
    if path == '/preview' or (path or '').startswith('/preview/'):
        return {
            'X-Frame-Options': 'SAMEORIGIN',
            'Content-Security-Policy': "frame-ancestors 'self'",
        }
    return {'X-Frame-Options': 'DENY'}
