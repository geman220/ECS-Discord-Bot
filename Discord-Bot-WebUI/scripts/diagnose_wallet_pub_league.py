#!/usr/bin/env python3
"""
Diagnose Pub League wallet passes for BOTH Apple (iOS) and Google (Android).

Why this exists: Apple passes are signed 100% locally, so if the certs are in
place they "just work". Google passes make LIVE calls to Google's Wallet API at
download time — they GET the pass "class" and, if it's missing, POST to create
it, then sign a JWT. So Android can fail while iOS is fine, and the only way to
know is to actually exercise that path. This script does exactly that.

It is SAFE to run repeatedly:
  * Read-only for the DB (it never commits).
  * The Google "ensure class exists" call is idempotent — it creates the
    pub-league class if the service account is allowed to, otherwise it prints
    the exact Google error so you know whether it's a permissions/console issue.
  * The end-to-end generation builds a real save URL / .pkpass in memory but
    does NOT persist anything.

Run it inside the webui container:
    docker exec -it webui python scripts/diagnose_wallet_pub_league.py
Optionally point it at a specific pass:
    docker exec -it webui python scripts/diagnose_wallet_pub_league.py --pass-id 123
"""
import argparse
import sys
import traceback

from app import create_app


PASS_TYPE_CODE = 'pub_league'


def _hr(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Diagnose Pub League wallet passes")
    parser.add_argument('--pass-id', type=int, default=None,
                        help="Test end-to-end generation against this WalletPass id")
    parser.add_argument('--create-class', action='store_true',
                        help="Actually create/update the Google class (default: also creates, "
                             "but this makes the intent explicit)")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        from app.models.wallet import WalletPassType, WalletPass
        from app.wallet_pass.services.pass_service import pass_service

        # ---- 1. Does the Pub League pass type exist? -------------------------
        _hr("1. Pub League pass type")
        pass_type = WalletPassType.get_by_code(PASS_TYPE_CODE)
        if not pass_type:
            print(f"  ✗ No WalletPassType with code '{PASS_TYPE_CODE}'. Passes can't be built at all.")
            print("    Create it in the wallet admin before anything else.")
            return 1
        print(f"  ✓ Found pass type #{pass_type.id}: '{pass_type.name}' (code={pass_type.code})")
        print(f"    background_color   = {pass_type.background_color}")
        print(f"    google_logo_url    = {pass_type.google_logo_url or '(none - falls back to /assets route)'}")
        print(f"    google_hero_image  = {pass_type.google_hero_image_url or '(none - falls back to strip)'}")
        print(f"    suppress_barcode   = {pass_type.suppress_barcode}")

        # ---- 2. Apple readiness (iOS) ---------------------------------------
        _hr("2. Apple / iOS readiness")
        try:
            ready = pass_service.is_pass_type_ready(PASS_TYPE_CODE)
            print(f"  ready = {ready.get('ready')}")
            for k in ('pass_type_exists', 'certificates_complete', 'assets_complete', 'template_complete'):
                print(f"    {k:22} = {ready.get(k)}")
            if ready.get('issues'):
                print("  issues:")
                for i in ready['issues']:
                    print(f"    - {i}")
        except Exception as e:
            print(f"  ✗ is_pass_type_ready raised: {e}")

        # ---- 3. Google config (Android) -------------------------------------
        _hr("3. Google / Android configuration")
        from app.wallet_pass.generators.google import (
            GOOGLE_WALLET_AVAILABLE, validate_google_config, _get_class_id,
        )
        gstatus = pass_service.get_google_config_status()
        print(f"  GOOGLE_WALLET_AVAILABLE (at import) = {GOOGLE_WALLET_AVAILABLE}")
        print(f"  get_google_config_status.configured = {gstatus.get('configured')}")
        if gstatus.get('issues'):
            print("  config issues:")
            for i in gstatus['issues']:
                print(f"    - {i}")
        is_valid, errs = validate_google_config()
        if not is_valid:
            print("  ✗ Google config invalid — Android will 501 'coming soon'. Fix these first:")
            for e in errs:
                print(f"    - {e}")
            print("\n  (Apple/iOS is independent and may still be fine per section 2.)")
            return 1

        # ---- 4. THE definitive test: ensure the Google class exists ---------
        _hr("4. Google Wallet CLASS (the usual Android failure point)")
        from app.wallet_pass.generators.google import (
            GooglePassConfig, ensure_google_wallet_class_exists,
        )
        config = GooglePassConfig()
        class_id = _get_class_id(config.issuer_id, pass_type.code)
        print(f"  Expected class id: {class_id}")
        print(f"  Service account:   {config.service_account_email}")
        try:
            returned = ensure_google_wallet_class_exists(config, pass_type,
                                                         force_update=args.create_class)
            print(f"  ✓ Class is present/creatable: {returned}")
            print("    => Android can generate pub-league passes.")
        except Exception as e:
            print(f"  ✗ Could NOT ensure the class: {e}")
            print("    This is why Android fails while iOS works. Almost always one of:")
            print("      - the service account isn't linked to the issuer in the Google")
            print("        Wallet console, or lacks 'create class' permission (403), or")
            print("      - the issuer id is wrong.")
            traceback.print_exc()
            return 1

        # ---- 5. End-to-end generation for a real pass -----------------------
        _hr("5. End-to-end generation for a real Pub League pass")
        wp = None
        if args.pass_id:
            wp = WalletPass.query.get(args.pass_id)
            if not wp:
                print(f"  --pass-id {args.pass_id} not found.")
        if not wp:
            wp = (WalletPass.query
                  .filter_by(pass_type_id=pass_type.id)
                  .order_by(WalletPass.id.desc())
                  .first())
        if not wp:
            print("  (No pub-league WalletPass exists yet to test — sections 1-4 still")
            print("   tell you whether the pipeline is ready.)")
            return 0
        print(f"  Testing pass #{wp.id} — {wp.member_name} (serial {wp.serial_number})")

        # Apple (in-memory, no persistence)
        try:
            pass_file, filename, mimetype = pass_service.get_pass_download(wp, platform='apple')
            size = getattr(pass_file, 'getbuffer', lambda: b'')().nbytes if hasattr(pass_file, 'getbuffer') else '?'
            print(f"  ✓ Apple  .pkpass built ({filename}, {mimetype}, {size} bytes)")
        except Exception as e:
            print(f"  ✗ Apple generation failed: {e}")
            traceback.print_exc()

        # Google (in-memory: call the generator directly so nothing is committed)
        try:
            from app.wallet_pass.generators.google import GooglePassGenerator
            url = GooglePassGenerator(pass_type).generate(wp)
            print(f"  ✓ Google save URL built ({len(url)} chars): {url[:60]}...")
            print("    => Tapping 'Google Wallet' on Android will work.")
        except Exception as e:
            print(f"  ✗ Google generation failed: {e}")
            traceback.print_exc()

        _hr("Done")
        return 0


if __name__ == '__main__':
    sys.exit(main())
