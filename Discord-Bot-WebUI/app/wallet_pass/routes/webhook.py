# app/wallet_pass/routes/webhook.py

"""
WooCommerce Webhook Handlers

Handles incoming webhooks from WooCommerce when orders are completed,
automatically creating wallet passes for membership products.
"""

import os
import hmac
import hashlib
import logging
import requests
from flask import Blueprint, request, jsonify

from app.core import db
from app.wallet_pass.services.pass_service import pass_service

logger = logging.getLogger(__name__)

webhook_bp = Blueprint('wallet_webhook', __name__, url_prefix='/api/v1/wallet')


def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """
    Verify WooCommerce webhook signature.

    Args:
        payload: Raw request body
        signature: X-WC-Webhook-Signature header value

    Returns:
        True if signature is valid
    """
    secret = os.getenv('WALLET_WEBHOOK_SECRET', '')
    if not secret:
        logger.warning("WALLET_WEBHOOK_SECRET not configured")
        return False

    expected = hmac.new(
        secret.encode('utf-8'),
        payload,
        hashlib.sha256
    ).digest()

    try:
        import base64
        provided = base64.b64decode(signature)
        return hmac.compare_digest(expected, provided)
    except Exception as e:
        logger.warning(f"Signature verification failed: {e}")
        return False


@webhook_bp.route('/webhook/order-completed', methods=['GET', 'POST'])
def handle_order_completed():
    """
    Handle WooCommerce order.updated webhook.

    Note: WooCommerce doesn't have an "order.completed" webhook topic,
    so we use "order.updated" and filter by status. This webhook fires
    on ANY order status change, so we check if status is "completed".

    When an order is completed in WooCommerce and contains a membership
    product, automatically create a wallet pass.

    Expected payload:
    {
        "id": 12345,
        "status": "completed",
        "billing": {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john@example.com"
        },
        "line_items": [
            {
                "name": "ECS 2026 Membership Card",
                "quantity": 1
            }
        ]
    }

    Returns:
    {
        "success": true,
        "passes_created": 1,
        "download_tokens": ["abc123..."]
    }
    """
    # Handle GET requests (browser visits) - return 404 to not expose endpoint
    if request.method == 'GET':
        from flask import abort
        abort(404)

    import json as json_module

    # Check for WooCommerce ping/test request
    # When you create a webhook, WooCommerce sends a ping to verify the URL
    wc_webhook_topic = request.headers.get('X-WC-Webhook-Topic', '')
    wc_webhook_resource = request.headers.get('X-WC-Webhook-Resource', '')
    wc_webhook_event = request.headers.get('X-WC-Webhook-Event', '')
    wc_webhook_id = request.headers.get('X-WC-Webhook-ID', '')

    logger.info(f"Webhook received - Topic: {wc_webhook_topic}, Resource: {wc_webhook_resource}, "
                f"Event: {wc_webhook_event}, ID: {wc_webhook_id}, Content-Type: {request.content_type}")

    # Handle ping requests (sent when webhook is created/updated)
    # WooCommerce sends pings with various header combinations
    if wc_webhook_resource == 'action' and wc_webhook_event == 'woocommerce_webhook_payload':
        logger.info("WooCommerce webhook ping received (action/payload) - responding OK")
        return jsonify({'status': 'ok', 'message': 'Webhook endpoint ready'}), 200

    # Also handle empty body pings (WooCommerce sometimes sends these)
    if not request.data or request.data == b'':
        logger.info("Empty webhook request received (likely ping) - responding OK")
        return jsonify({'status': 'ok', 'message': 'Webhook endpoint ready'}), 200

    # Verify webhook signature (optional but recommended)
    signature = request.headers.get('X-WC-Webhook-Signature', '')
    if signature and os.getenv('WALLET_WEBHOOK_SECRET'):
        if not verify_webhook_signature(request.data, signature):
            logger.warning("Invalid webhook signature")
            return jsonify({'error': 'Invalid signature'}), 401

    # Also check custom header secret for simpler setups
    header_secret = request.headers.get('X-Webhook-Secret', '')
    expected_secret = os.getenv('WALLET_WEBHOOK_SECRET', '')
    if expected_secret and header_secret != expected_secret:
        if not signature:  # Only fail if no WC signature either
            logger.warning("Invalid webhook secret header")
            return jsonify({'error': 'Unauthorized'}), 401

    try:
        # Log raw data for debugging
        raw_data = request.data.decode('utf-8') if request.data else ''
        logger.debug(f"Raw webhook data (first 500 chars): {raw_data[:500]}")

        # WooCommerce should send JSON, but handle various cases
        data = None

        # Try to parse as JSON first
        if request.content_type and 'application/json' in request.content_type:
            data = request.get_json(silent=True)

        # If not JSON content-type, try force parsing
        if not data:
            data = request.get_json(force=True, silent=True)

        # If still no data, try manual JSON parsing
        if not data and raw_data:
            try:
                data = json_module.loads(raw_data)
            except json_module.JSONDecodeError:
                pass

        # If it's form data, try to extract from form
        if not data and request.content_type and 'form-urlencoded' in request.content_type:
            # WooCommerce ping requests might come as form data
            form_data = request.form.to_dict()
            if form_data:
                logger.info(f"Received form data: {form_data}")
                # This is likely a ping or malformed request
                return jsonify({
                    'status': 'ok',
                    'message': 'Received form data - webhook endpoint is reachable',
                    'note': 'Expected JSON payload for order processing'
                }), 200

        if not data:
            logger.warning(f"Could not parse webhook data. Content-Type: {request.content_type}, Data length: {len(raw_data)}")
            return jsonify({'error': 'No valid JSON data provided', 'content_type': request.content_type}), 400

        order_id = data.get('id')
        order_status = data.get('status', '').lower()
        billing = data.get('billing', {})
        line_items = data.get('line_items', [])

        # Process orders that are paid (processing) or completed
        # - 'processing' = payment received, this is when users want their pass
        # - 'completed' = order fulfilled (also valid)
        # WooCommerce "Order updated" webhook fires on ANY status change
        valid_statuses = ['processing', 'completed']
        if order_status not in valid_statuses:
            logger.info(f"Ignoring order {order_id} with status '{order_status}' (not paid yet)")
            return jsonify({
                'success': True,
                'message': f'Order status is {order_status}, not paid yet. No action taken.',
                'passes_created': 0
            })

        if not order_id:
            return jsonify({'error': 'Missing order ID'}), 400

        # Check if pass already exists for this order (prevent duplicates)
        # This is important since webhook fires on both processing and completed
        from app.models.wallet import WalletPass
        existing_pass = WalletPass.query.filter_by(woo_order_id=order_id).first()
        if existing_pass:
            logger.info(f"Pass already exists for order {order_id}, skipping creation")
            return jsonify({
                'success': True,
                'passes_created': 0,
                'message': 'Pass already exists for this order',
                'existing_token': existing_pass.download_token
            })

        # Extract customer info
        customer_name = f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip()
        customer_email = billing.get('email', '')

        if not customer_name:
            customer_name = customer_email.split('@')[0] if customer_email else 'Unknown'

        # Format products for processing
        products = [
            {'name': item.get('name', ''), 'quantity': item.get('quantity', 1)}
            for item in line_items
        ]

        logger.info(f"Processing order {order_id} for {customer_name}, {len(products)} items")

        # Process the order
        created_passes = pass_service.process_woo_order(
            order_id=order_id,
            customer_name=customer_name,
            customer_email=customer_email,
            products=products
        )

        if created_passes:
            download_tokens = [p.download_token for p in created_passes]
            logger.info(
                f"Created {len(created_passes)} passes for order {order_id}"
            )

            # Callback to WordPress to store the download token on the order
            # This allows the thank-you page to show download buttons immediately
            # Run in background thread to avoid blocking the webhook response
            def send_wordpress_callback(app, order_id, download_token, webhook_data):
                """Send callback to WordPress in background thread"""
                # Use Flask app context for database access
                with app.app_context():
                    # Try to get WooCommerce site URL from multiple sources
                    woo_site_url = webhook_data.get('_links', {}).get('site', [{}])[0].get('href', '')
                    logger.debug(f"Callback: _links.site URL = '{woo_site_url}'")

                    if not woo_site_url:
                        woo_site_url = webhook_data.get('store_url', '')
                        logger.debug(f"Callback: store_url = '{woo_site_url}'")

                    if not woo_site_url:
                        try:
                            from app.models.admin_config import AdminConfig
                            woo_site_url = AdminConfig.get_setting('woocommerce_site_url', '')
                            logger.debug(f"Callback: AdminConfig URL = '{woo_site_url}'")
                        except Exception as db_err:
                            logger.warning(f"Callback: AdminConfig lookup failed: {db_err}")

                    if not woo_site_url:
                        woo_site_url = os.getenv('WOOCOMMERCE_SITE_URL', '')
                        logger.debug(f"Callback: env WOOCOMMERCE_SITE_URL = '{woo_site_url}'")

                    if not woo_site_url:
                        logger.warning(f"No WooCommerce site URL configured - cannot send callback for order {order_id}")
                        return

                    try:
                        callback_url = woo_site_url.rstrip('/') + '/wp-json/ecs/v1/wallet-callback'
                        callback_data = {
                            'order_id': order_id,
                            'download_token': download_token
                        }
                        callback_headers = {}
                        webhook_secret = os.getenv('WALLET_WEBHOOK_SECRET', '')
                        if webhook_secret:
                            callback_headers['X-Webhook-Secret'] = webhook_secret

                        logger.info(f"Sending callback to {callback_url} for order {order_id}")
                        callback_response = requests.post(
                            callback_url,
                            json=callback_data,
                            headers=callback_headers,
                            timeout=10
                        )
                        if callback_response.ok:
                            logger.info(f"Successfully sent callback to WordPress for order {order_id}")
                        else:
                            logger.warning(f"WordPress callback failed: {callback_response.status_code} - {callback_response.text}")
                    except Exception as callback_error:
                        logger.warning(f"Could not send callback to WordPress: {callback_error}")

            # Start callback in background thread so we don't block the webhook response
            import threading
            from flask import current_app
            app = current_app._get_current_object()  # Get actual app object, not proxy
            callback_thread = threading.Thread(
                target=send_wordpress_callback,
                args=(app, order_id, download_tokens[0], data),
                daemon=True
            )
            callback_thread.start()
            logger.info(f"Started background callback thread for order {order_id}")

            return jsonify({
                'success': True,
                'passes_created': len(created_passes),
                'download_tokens': download_tokens,
                # Return first token for simple single-pass orders
                'download_token': download_tokens[0] if download_tokens else None,
                'pass_type': created_passes[0].pass_type.code if created_passes else None
            })
        else:
            logger.info(f"No membership products found in order {order_id}")
            return jsonify({
                'success': True,
                'passes_created': 0,
                'message': 'No membership products found in order'
            })

    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@webhook_bp.route('/webhook/test', methods=['POST', 'GET'])
def test_webhook():
    """
    Test endpoint for verifying webhook connectivity.

    Can be used to verify that the WooCommerce webhook is properly
    configured and can reach the Flask server.
    """
    if request.method == 'GET':
        return jsonify({
            'status': 'ok',
            'message': 'Wallet webhook endpoint is reachable',
            'webhook_url': request.url.replace('/test', '/order-completed')
        })

    # POST - test with sample data
    data = request.get_json() or {}
    return jsonify({
        'status': 'ok',
        'message': 'Webhook test received',
        'received_data_keys': list(data.keys()) if data else [],
        'headers': {
            'content-type': request.headers.get('Content-Type'),
            'has_signature': bool(request.headers.get('X-WC-Webhook-Signature')),
            'has_secret': bool(request.headers.get('X-Webhook-Secret'))
        }
    })


@webhook_bp.route('/webhook/manual-create', methods=['POST'])
def manual_create_pass():
    """
    Manually create a pass (admin API endpoint).

    This can be called from WordPress/WooCommerce admin or other
    administrative tools when automatic webhook doesn't fire.

    Requires authentication via API key header.

    Expected payload:
    {
        "order_id": 12345,
        "customer_name": "John Doe",
        "customer_email": "john@example.com",
        "year": 2025,
        "pass_type": "ecs_membership"
    }
    """
    # Verify API key
    api_key = request.headers.get('X-API-Key', '')
    expected_key = os.getenv('WALLET_API_KEY', '')

    if not expected_key or api_key != expected_key:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        data = request.get_json()

        pass_type = data.get('pass_type', 'ecs_membership')
        order_id = data.get('order_id')
        customer_name = data.get('customer_name')
        customer_email = data.get('customer_email')
        year = data.get('year')

        if not customer_name:
            return jsonify({'error': 'customer_name is required'}), 400

        if pass_type == 'ecs_membership':
            if not year:
                from datetime import datetime
                year = datetime.now().year

            wallet_pass = pass_service.create_ecs_membership(
                member_name=customer_name,
                member_email=customer_email,
                year=year,
                woo_order_id=order_id
            )
        else:
            return jsonify({
                'error': f'Unsupported pass type: {pass_type}. Use ecs_membership.'
            }), 400

        return jsonify({
            'success': True,
            'pass_id': wallet_pass.id,
            'download_token': wallet_pass.download_token,
            'barcode': wallet_pass.barcode_data
        })

    except Exception as e:
        logger.error(f"Error in manual pass creation: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
