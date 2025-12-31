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
                'wallet/download_error.html',
                error='Missing download token',
                message='Please use the download link from your order confirmation email.'
            ), 400

        # Find pass by token
        wallet_pass = pass_service.find_by_download_token(token)

        if not wallet_pass:
            logger.warning(f"Pass not found for token: {token[:8]}...")
            return render_template(
                'wallet/download_error.html',
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
                        'wallet/download_error.html',
                        error='Invalid order',
                        message='This download link does not match the provided order.'
                    ), 403
            except ValueError:
                pass  # Invalid order ID format, continue anyway

        # Check if pass is still valid
        if wallet_pass.status == 'voided':
            return render_template(
                'wallet/download_error.html',
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
                    'wallet/download_error.html',
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
                    'wallet/download_error.html',
                    error='Coming soon',
                    message='Google Wallet passes are coming soon. Please use Apple Wallet for now.'
                ), 501
            except Exception as e:
                logger.error(f"Error generating Google pass URL: {e}")
                return render_template(
                    'wallet/download_error.html',
                    error='Generation failed',
                    message='Unable to generate your wallet pass. Please try again later.'
                ), 500

        else:
            return render_template(
                'wallet/download_error.html',
                error='Invalid platform',
                message='Please specify a valid wallet platform (apple or google).'
            ), 400

    except Exception as e:
        logger.error(f"Unexpected error in pass download: {e}")
        return render_template(
            'wallet/download_error.html',
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
            'wallet/download_error.html',
            error='Missing token',
            message='Please use the link from your order confirmation.'
        ), 400

    wallet_pass = pass_service.find_by_download_token(token)

    if not wallet_pass:
        return render_template(
            'wallet/download_error.html',
            error='Pass not found',
            message='This download link may be invalid or expired.'
        ), 404

    return render_template(
        'wallet/pass_info.html',
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
