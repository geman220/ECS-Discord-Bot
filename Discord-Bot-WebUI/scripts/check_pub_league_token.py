#!/usr/bin/env python3
"""
Verify that the portal's WALLET_WEBHOOK_SECRET matches the WooCommerce plugin's
Webhook Secret — i.e. that the order-link tokens the plugin generates will pass
the (now genuinely enforced) HMAC check.

Read-only. Touches no orders, consumes nothing, safe on an already-claimed order.

Usage, inside the webui container:

    python scripts/check_pub_league_token.py \
        --order-id 1014961 \
        --token 629224a827f33b1e1f2e49a6bf119029e75b254b775373ae3e3172963457a078

Take both values straight out of a real link-order URL you already have.
"""

import argparse
import hashlib
import hmac
import os
import sys


def expected_token(order_id: int, secret: str) -> str:
    """Exactly what app/pub_league/services.py:verify_order_token computes."""
    message = f"pub_league_order_{order_id}"
    return hmac.new(secret.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--order-id', type=int, required=True,
                        help='woo order id from the link (?order_id=...)')
    parser.add_argument('--token', required=True,
                        help='token from the link (&token=...)')
    parser.add_argument('--secret', default=None,
                        help='override; defaults to WALLET_WEBHOOK_SECRET from the env')
    args = parser.parse_args()

    secret = args.secret or os.getenv('WALLET_WEBHOOK_SECRET', '')
    if not secret:
        print("FAIL: WALLET_WEBHOOK_SECRET is not set in this environment.")
        print("      The order-link flow cannot work at all until it is.")
        return 2

    want = expected_token(args.order_id, secret)
    got = args.token.strip()
    ok = hmac.compare_digest(got, want)

    print(f"order_id        : {args.order_id}")
    print(f"secret (len)    : {len(secret)} chars, starts {secret[:4]}...")
    print(f"token in link   : {got[:20]}...")
    print(f"token expected  : {want[:20]}...")
    print()

    if ok:
        print("PASS — the secrets match. Real order links will verify.")
        print("       Safe to ship the token enforcement.")
        return 0

    print("FAIL — the portal's WALLET_WEBHOOK_SECRET does NOT match the secret the")
    print("       plugin used to sign this link.")
    print()
    print("       Before this change the token was never actually checked, so the")
    print("       flow 'worked' anyway. With enforcement on, every buyer will now")
    print("       hit 'This link is no longer valid.'")
    print()
    print("       Fix: set the portal's WALLET_WEBHOOK_SECRET to the value in the")
    print("       WooCommerce plugin settings (ECS Pub League -> Webhook Secret),")
    print("       or vice versa. They must be byte-identical.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
