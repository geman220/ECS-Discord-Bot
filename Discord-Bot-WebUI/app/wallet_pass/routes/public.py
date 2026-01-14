# app/wallet_pass/routes/public.py

"""
Public Wallet Pass Download Routes

These endpoints allow customers to download their wallet passes
from WooCommerce order confirmation pages using secure tokens.
No authentication required - security via unique download tokens.
"""

import logging
from flask import Blueprint, request, jsonify, send_file, render_template, redirect, url_for, make_response

from app.models.wallet import WalletPass
from app.wallet_pass.services.pass_service import pass_service

logger = logging.getLogger(__name__)

public_wallet_bp = Blueprint('public_wallet', __name__, url_prefix='/membership/wallet')


@public_wallet_bp.route('/pass/download')
def download_pass_by_token():
    """
    Download a wallet pass using order ID and token.

    This endpoint is called from WooCommerce order confirmation pages.

    URL: /membership/wallet/pass/download?order=12345&token=abc123&platform=apple

    Query params:
        order: WooCommerce order ID (for logging/verification)
        token: Secure download token
        platform: 'apple' or 'google' (defaults to 'apple')
    """
    try:
        order_id = request.args.get('order')
        token = request.args.get('token')
        platform = request.args.get('platform', 'apple')

        if not token:
            logger.warning(f"Pass download attempted without token, order: {order_id}")
            return render_template(
                'wallet/download_error_flowbite.html',
                error='Missing download token',
                message='Please use the download link from your order confirmation email.'
            ), 400

        # Find pass by token
        wallet_pass = pass_service.find_by_download_token(token)

        if not wallet_pass:
            logger.warning(f"Pass not found for token: {token[:8]}...")
            return render_template(
                'wallet/download_error_flowbite.html',
                error='Pass not found',
                message='This download link may be invalid or expired.'
            ), 404

        # Verify order ID matches (if provided)
        if order_id and wallet_pass.woo_order_id:
            try:
                if int(order_id) != wallet_pass.woo_order_id:
                    logger.warning(
                        f"Order ID mismatch: provided {order_id}, "
                        f"expected {wallet_pass.woo_order_id}"
                    )
                    return render_template(
                        'wallet/download_error_flowbite.html',
                        error='Invalid order',
                        message='This download link does not match the provided order.'
                    ), 403
            except ValueError:
                pass  # Invalid order ID format, continue anyway

        # Check if pass is still valid
        if wallet_pass.status == 'voided':
            return render_template(
                'wallet/download_error_flowbite.html',
                error='Pass voided',
                message='This membership pass has been voided and is no longer available.'
            ), 410

        # Generate and return the pass
        if platform == 'apple':
            try:
                pass_file, filename, mimetype = pass_service.get_pass_download(
                    wallet_pass, platform='apple'
                )
                logger.info(
                    f"Pass downloaded: {wallet_pass.member_name}, "
                    f"order: {order_id}, platform: apple"
                )

                # Build response with headers optimized for iOS browser compatibility
                # These headers help Chrome/Firefox on iOS handle the pass correctly
                response = make_response(send_file(
                    pass_file,
                    mimetype=mimetype,
                    as_attachment=True,
                    download_name=filename
                ))

                # Ensure correct content type (critical for iOS pass handling)
                response.headers['Content-Type'] = 'application/vnd.apple.pkpass'
                # Prevent caching issues that can cause pass installation failures
                response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
                response.headers['Pragma'] = 'no-cache'
                # Set last modified to help with pass updates
                if wallet_pass.updated_at:
                    response.headers['Last-Modified'] = wallet_pass.updated_at.strftime('%a, %d %b %Y %H:%M:%S GMT')

                return response
            except Exception as e:
                logger.error(f"Error generating Apple pass: {e}")
                return render_template(
                    'wallet/download_error_flowbite.html',
                    error='Generation failed',
                    message='Unable to generate your wallet pass. Please try again later.'
                ), 500

        elif platform == 'google':
            # Google Wallet returns a URL for redirect
            try:
                url = pass_service.generate_google_pass_url(wallet_pass)
                logger.info(
                    f"Google pass redirect: {wallet_pass.member_name}, order: {order_id}"
                )
                return redirect(url)
            except NotImplementedError:
                return render_template(
                    'wallet/download_error_flowbite.html',
                    error='Coming soon',
                    message='Google Wallet passes are coming soon. Please use Apple Wallet for now.'
                ), 501
            except Exception as e:
                logger.error(f"Error generating Google pass URL: {e}")
                return render_template(
                    'wallet/download_error_flowbite.html',
                    error='Generation failed',
                    message='Unable to generate your wallet pass. Please try again later.'
                ), 500

        else:
            return render_template(
                'wallet/download_error_flowbite.html',
                error='Invalid platform',
                message='Please specify a valid wallet platform (apple or google).'
            ), 400

    except Exception as e:
        logger.error(f"Unexpected error in pass download: {e}")
        return render_template(
            'wallet/download_error_flowbite.html',
            error='Server error',
            message='An unexpected error occurred. Please try again later.'
        ), 500


@public_wallet_bp.route('/pass/info')
def pass_info():
    """
    Get pass information without downloading.

    Returns a page showing pass details and download options.

    URL: /membership/wallet/pass/info?token=abc123
    """
    token = request.args.get('token')

    if not token:
        return render_template(
            'wallet/download_error_flowbite.html',
            error='Missing token',
            message='Please use the link from your order confirmation.'
        ), 400

    wallet_pass = pass_service.find_by_download_token(token)

    if not wallet_pass:
        return render_template(
            'wallet/download_error_flowbite.html',
            error='Pass not found',
            message='This download link may be invalid or expired.'
        ), 404

    return render_template(
        'wallet/pass_info_flowbite.html',
        wallet_pass=wallet_pass,
        download_token=token
    )


@public_wallet_bp.route('/api/pass/status')
def pass_status_api():
    """
    API endpoint to check pass status by token.

    Used by JavaScript on WooCommerce pages to check if pass is ready.

    URL: /membership/wallet/api/pass/status?token=abc123
    """
    token = request.args.get('token')

    if not token:
        return jsonify({'error': 'Missing token'}), 400

    wallet_pass = pass_service.find_by_download_token(token)

    if not wallet_pass:
        return jsonify({'found': False}), 404

    # Check Google Wallet configuration status
    google_config = pass_service.get_google_config_status()

    return jsonify({
        'found': True,
        'status': wallet_pass.status,
        'is_valid': wallet_pass.is_valid,
        'member_name': wallet_pass.member_name,
        'pass_type': wallet_pass.pass_type.name if wallet_pass.pass_type else None,
        'valid_until': wallet_pass.valid_until.isoformat() if wallet_pass.valid_until else None,
        'download_count': wallet_pass.download_count,
        'apple_available': True,
        'google_available': google_config.get('configured', False)
    })


# =============================================================================
# PUBLIC ASSET ROUTES (for Google Wallet to fetch images)
# =============================================================================

@public_wallet_bp.route('/assets/<pass_type_code>/<asset_type>.png')
def serve_public_asset(pass_type_code, asset_type):
    """
    Serve wallet pass assets publicly for Google Wallet to access.

    This endpoint is needed because Google's servers fetch images from URLs
    we provide in the pass definition. The images must be publicly accessible.

    URL: /membership/wallet/assets/ecs_membership/strip.png

    Args:
        pass_type_code: Pass type code (e.g., 'ecs_membership', 'pub_league')
        asset_type: Asset type (e.g., 'strip', 'logo', 'icon')
    """
    import os
    from flask import send_file
    from app.models.wallet import WalletPassType
    from app.models.wallet_asset import WalletAsset

    try:
        # Find pass type by code
        pass_type = WalletPassType.query.filter_by(code=pass_type_code).first()
        if not pass_type:
            logger.warning(f"Pass type not found: {pass_type_code}")
            return jsonify({'error': 'Pass type not found'}), 404

        # Find asset for this pass type
        asset = WalletAsset.query.filter_by(
            pass_type_id=pass_type.id,
            asset_type=asset_type
        ).first()

        if not asset:
            logger.warning(f"Asset not found: {pass_type_code}/{asset_type}")
            return jsonify({'error': 'Asset not found'}), 404

        # Find the file
        paths_to_try = [
            asset.file_path,
            os.path.join('app', asset.file_path) if not asset.file_path.startswith('app/') else asset.file_path,
        ]

        for try_path in paths_to_try:
            if os.path.exists(try_path):
                response = make_response(send_file(
                    os.path.abspath(try_path),
                    mimetype=asset.content_type or 'image/png'
                ))
                # Allow caching for performance
                response.headers['Cache-Control'] = 'public, max-age=86400'
                return response

        logger.error(f"Asset file not found on disk: {asset.file_path}")
        return jsonify({'error': 'Asset file not found'}), 404

    except Exception as e:
        logger.error(f"Error serving public asset: {e}")
        return jsonify({'error': 'Server error'}), 500
