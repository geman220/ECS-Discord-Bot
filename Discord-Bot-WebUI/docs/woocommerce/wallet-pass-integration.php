<?php
/**
 * ECS Digital Wallet Pass - WooCommerce Integration
 *
 * This code adds digital wallet pass download functionality to WooCommerce.
 * Add this code to your theme's functions.php or create a custom plugin.
 *
 * Configuration:
 * 1. Set up a WooCommerce webhook in WooCommerce > Settings > Advanced > Webhooks:
 *    - Name: Wallet Pass Creation
 *    - Status: Active
 *    - Topic: Order completed
 *    - Delivery URL: https://portal.ecsfc.com/api/v1/wallet/webhook/order-completed
 *    - Secret: (your webhook secret, same as WALLET_WEBHOOK_SECRET env var)
 *
 * 2. Add this code to functions.php or custom plugin
 *
 * 3. Set the PORTAL_URL constant to your portal URL
 */

// Configuration - CHANGE THESE VALUES
define('ECS_PORTAL_URL', 'https://portal.ecsfc.com');
define('ECS_WALLET_WEBHOOK_SECRET', ''); // Set same as WALLET_WEBHOOK_SECRET in portal

/**
 * Product patterns that qualify for wallet passes.
 * These patterns match product names that should trigger wallet pass creation.
 */
function ecs_get_membership_product_patterns() {
    return array(
        'ecs_membership' => array(
            '/ECS.*Membership.*Card/i',
            '/ECS Membership \d{4}/i',
            '/ECS Membership Package/i',
        ),
        'pub_league' => array(
            '/Pub League.*Registration/i',
            '/Pub League.*Spring/i',
            '/Pub League.*Fall/i',
            '/Pub League.*Season/i',
        ),
    );
}

/**
 * Check if an order contains membership products.
 *
 * @param WC_Order $order The order to check
 * @return array Array of matching products with their pass types
 */
function ecs_get_membership_products($order) {
    $membership_products = array();
    $patterns = ecs_get_membership_product_patterns();

    foreach ($order->get_items() as $item) {
        $product_name = $item->get_name();

        foreach ($patterns as $pass_type => $type_patterns) {
            foreach ($type_patterns as $pattern) {
                if (preg_match($pattern, $product_name)) {
                    $membership_products[] = array(
                        'name' => $product_name,
                        'pass_type' => $pass_type,
                        'quantity' => $item->get_quantity(),
                    );
                    break 2; // Found a match, move to next item
                }
            }
        }
    }

    return $membership_products;
}

/**
 * Display wallet pass download section on order thank you page.
 *
 * @param int $order_id The order ID
 */
function ecs_display_wallet_pass_download($order_id) {
    $order = wc_get_order($order_id);
    if (!$order) return;

    // Only show for completed orders
    if ($order->get_status() !== 'completed') return;

    $membership_products = ecs_get_membership_products($order);
    if (empty($membership_products)) return;

    // Get the download token from order meta (set by webhook response)
    $download_token = $order->get_meta('_wallet_pass_token');

    if (!$download_token) {
        // Token not yet available - webhook may not have fired yet
        // Show a loading state that polls for the token
        ?>
        <section class="ecs-wallet-pass-section" style="margin-top: 30px; padding: 20px; background: #f8f8f8; border-radius: 8px;">
            <h2 style="margin-top: 0; color: #1a472a;">
                <span style="margin-right: 10px;">📱</span>
                Your Digital Membership Card
            </h2>
            <p>Your digital membership card is being prepared...</p>
            <div id="wallet-pass-loading">
                <p><em>Please wait a moment while we generate your pass.</em></p>
                <div class="ecs-loading-spinner" style="display: inline-block; width: 20px; height: 20px; border: 3px solid #ddd; border-top-color: #1a472a; border-radius: 50%; animation: spin 1s linear infinite;"></div>
            </div>
            <div id="wallet-pass-buttons" style="display: none;"></div>
            <style>
                @keyframes spin { to { transform: rotate(360deg); } }
            </style>
            <script>
            (function() {
                var pollCount = 0;
                var maxPolls = 30; // Poll for up to 30 seconds

                function checkPassStatus() {
                    if (pollCount >= maxPolls) {
                        document.getElementById('wallet-pass-loading').innerHTML =
                            '<p style="color: #856404;">Your pass is still being generated. ' +
                            'Please check your email or refresh this page in a few minutes.</p>';
                        return;
                    }

                    pollCount++;

                    fetch('<?php echo admin_url('admin-ajax.php'); ?>?action=ecs_check_wallet_pass&order_id=<?php echo $order_id; ?>')
                        .then(function(response) { return response.json(); })
                        .then(function(data) {
                            if (data.success && data.token) {
                                document.getElementById('wallet-pass-loading').style.display = 'none';
                                document.getElementById('wallet-pass-buttons').style.display = 'block';
                                document.getElementById('wallet-pass-buttons').innerHTML = data.html;
                            } else {
                                setTimeout(checkPassStatus, 1000);
                            }
                        })
                        .catch(function() {
                            setTimeout(checkPassStatus, 1000);
                        });
                }

                setTimeout(checkPassStatus, 2000);
            })();
            </script>
        </section>
        <?php
        return;
    }

    // Token available - show download buttons
    ecs_render_wallet_buttons($download_token, $order_id, $membership_products);
}
add_action('woocommerce_thankyou', 'ecs_display_wallet_pass_download', 20);

/**
 * Render the wallet download buttons.
 */
function ecs_render_wallet_buttons($download_token, $order_id, $membership_products) {
    $apple_url = ECS_PORTAL_URL . '/membership/wallet/pass/download?order=' . $order_id . '&token=' . $download_token . '&platform=apple';
    $google_url = ECS_PORTAL_URL . '/membership/wallet/pass/download?order=' . $order_id . '&token=' . $download_token . '&platform=google';
    $info_url = ECS_PORTAL_URL . '/membership/wallet/pass/info?token=' . $download_token;

    $pass_type = $membership_products[0]['pass_type'] ?? 'ecs_membership';
    $is_ecs = ($pass_type === 'ecs_membership');
    ?>
    <section class="ecs-wallet-pass-section" style="margin-top: 30px; padding: 20px; background: <?php echo $is_ecs ? '#e8f5e9' : '#e3f2fd'; ?>; border-radius: 8px; border-left: 4px solid <?php echo $is_ecs ? '#1a472a' : '#213e96'; ?>;">
        <h2 style="margin-top: 0; color: <?php echo $is_ecs ? '#1a472a' : '#213e96'; ?>;">
            <span style="margin-right: 10px;"><?php echo $is_ecs ? '⚽' : '🍺'; ?></span>
            Your <?php echo $is_ecs ? 'ECS Membership' : 'Pub League'; ?> Digital Card
        </h2>

        <p style="margin-bottom: 20px;">
            Add your digital membership card to your phone's wallet for easy access at matches and events.
        </p>

        <div class="wallet-buttons" style="display: flex; flex-wrap: wrap; gap: 15px; margin-bottom: 15px;">
            <!-- Apple Wallet Button -->
            <a href="<?php echo esc_url($apple_url); ?>"
               class="wallet-button apple-wallet"
               style="display: inline-flex; align-items: center; padding: 12px 24px; background: #000; color: #fff; text-decoration: none; border-radius: 8px; font-weight: 500; transition: transform 0.2s;">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor" style="margin-right: 10px;">
                    <path d="M18.71 19.5c-.83 1.24-1.71 2.45-3.05 2.47-1.34.03-1.77-.79-3.29-.79-1.53 0-2 .77-3.27.82-1.31.05-2.3-1.32-3.14-2.53C4.25 17 2.94 12.45 4.7 9.39c.87-1.52 2.43-2.48 4.12-2.51 1.28-.02 2.5.87 3.29.87.78 0 2.26-1.07 3.81-.91.65.03 2.47.26 3.64 1.98-.09.06-2.17 1.28-2.15 3.81.03 3.02 2.65 4.03 2.68 4.04-.03.07-.42 1.44-1.38 2.83M13 3.5c.73-.83 1.94-1.46 2.94-1.5.13 1.17-.34 2.35-1.04 3.19-.69.85-1.83 1.51-2.95 1.42-.15-1.15.41-2.35 1.05-3.11z"/>
                </svg>
                Add to Apple Wallet
            </a>

            <!-- Google Wallet Button -->
            <a href="<?php echo esc_url($google_url); ?>"
               class="wallet-button google-wallet"
               style="display: inline-flex; align-items: center; padding: 12px 24px; background: #4285f4; color: #fff; text-decoration: none; border-radius: 8px; font-weight: 500; transition: transform 0.2s; position: relative;">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor" style="margin-right: 10px;">
                    <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                    <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                    <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                    <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                </svg>
                Add to Google Wallet
                <span style="position: absolute; top: -8px; right: -8px; background: #ffc107; color: #000; font-size: 10px; padding: 2px 6px; border-radius: 4px;">Soon</span>
            </a>
        </div>

        <p style="margin: 0; font-size: 0.9em; color: #666;">
            <a href="<?php echo esc_url($info_url); ?>" target="_blank" style="color: <?php echo $is_ecs ? '#1a472a' : '#213e96'; ?>;">
                View pass details →
            </a>
        </p>
    </section>

    <style>
        .wallet-button:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }
        @media (max-width: 480px) {
            .wallet-buttons {
                flex-direction: column;
            }
            .wallet-button {
                justify-content: center;
            }
        }
    </style>
    <?php
}

/**
 * AJAX handler to check if wallet pass token is available.
 */
function ecs_check_wallet_pass_ajax() {
    $order_id = isset($_GET['order_id']) ? intval($_GET['order_id']) : 0;

    if (!$order_id) {
        wp_send_json(array('success' => false));
    }

    $order = wc_get_order($order_id);
    if (!$order) {
        wp_send_json(array('success' => false));
    }

    $download_token = $order->get_meta('_wallet_pass_token');

    if ($download_token) {
        $membership_products = ecs_get_membership_products($order);

        ob_start();
        ecs_render_wallet_buttons($download_token, $order_id, $membership_products);
        $html = ob_get_clean();

        wp_send_json(array(
            'success' => true,
            'token' => $download_token,
            'html' => $html,
        ));
    }

    wp_send_json(array('success' => false));
}
add_action('wp_ajax_ecs_check_wallet_pass', 'ecs_check_wallet_pass_ajax');
add_action('wp_ajax_nopriv_ecs_check_wallet_pass', 'ecs_check_wallet_pass_ajax');

/**
 * Store wallet pass token from webhook response.
 *
 * This function should be called from the webhook handler when the portal
 * returns a download token. Alternatively, you can set up a webhook in
 * WooCommerce to receive the response automatically.
 *
 * @param int $order_id The WooCommerce order ID
 * @param string $token The download token from the portal
 */
function ecs_store_wallet_pass_token($order_id, $token) {
    $order = wc_get_order($order_id);
    if ($order) {
        $order->update_meta_data('_wallet_pass_token', $token);
        $order->save();
    }
}

/**
 * REST API endpoint to receive wallet pass tokens from the portal.
 *
 * This endpoint receives callbacks from the portal after pass creation.
 * The portal calls this with the order_id and download_token.
 *
 * POST /wp-json/ecs/v1/wallet-callback
 * Body: { "order_id": 12345, "download_token": "abc123..." }
 */
function ecs_register_wallet_callback_endpoint() {
    register_rest_route('ecs/v1', '/wallet-callback', array(
        'methods' => 'POST',
        'callback' => 'ecs_handle_wallet_callback',
        'permission_callback' => 'ecs_verify_wallet_callback',
    ));
}
add_action('rest_api_init', 'ecs_register_wallet_callback_endpoint');

function ecs_verify_wallet_callback($request) {
    // Verify the request is from our portal using shared secret
    $provided_secret = $request->get_header('X-Webhook-Secret');

    if (empty(ECS_WALLET_WEBHOOK_SECRET)) {
        // No secret configured - allow for testing but log warning
        error_log('ECS Wallet: No webhook secret configured');
        return true;
    }

    return hash_equals(ECS_WALLET_WEBHOOK_SECRET, $provided_secret);
}

function ecs_handle_wallet_callback($request) {
    $params = $request->get_json_params();

    $order_id = isset($params['order_id']) ? intval($params['order_id']) : 0;
    $download_token = isset($params['download_token']) ? sanitize_text_field($params['download_token']) : '';

    if (!$order_id || !$download_token) {
        return new WP_Error('invalid_params', 'Missing order_id or download_token', array('status' => 400));
    }

    ecs_store_wallet_pass_token($order_id, $download_token);

    return array(
        'success' => true,
        'message' => 'Token stored for order ' . $order_id,
    );
}

/**
 * Display wallet pass download in My Account > Orders.
 *
 * @param array $actions Existing order actions
 * @param WC_Order $order The order
 * @return array Modified actions
 */
function ecs_add_wallet_action_to_orders($actions, $order) {
    if ($order->get_status() !== 'completed') {
        return $actions;
    }

    $membership_products = ecs_get_membership_products($order);
    if (empty($membership_products)) {
        return $actions;
    }

    $download_token = $order->get_meta('_wallet_pass_token');
    if (!$download_token) {
        return $actions;
    }

    $info_url = ECS_PORTAL_URL . '/membership/wallet/pass/info?token=' . $download_token;

    $actions['wallet_pass'] = array(
        'url' => $info_url,
        'name' => 'Digital Pass',
    );

    return $actions;
}
add_filter('woocommerce_my_account_my_orders_actions', 'ecs_add_wallet_action_to_orders', 10, 2);

/**
 * Display wallet pass section on order details page in My Account.
 *
 * @param WC_Order $order The order
 */
function ecs_display_wallet_on_order_details($order) {
    if ($order->get_status() !== 'completed') {
        return;
    }

    $membership_products = ecs_get_membership_products($order);
    if (empty($membership_products)) {
        return;
    }

    $download_token = $order->get_meta('_wallet_pass_token');
    if (!$download_token) {
        echo '<p><em>Your digital membership card is being generated. Please check back soon.</em></p>';
        return;
    }

    ecs_render_wallet_buttons($download_token, $order->get_id(), $membership_products);
}
add_action('woocommerce_order_details_after_order_table', 'ecs_display_wallet_on_order_details');

/**
 * Add wallet pass info to order emails.
 *
 * @param WC_Order $order The order
 * @param bool $sent_to_admin Whether email is for admin
 * @param bool $plain_text Whether email is plain text
 */
function ecs_add_wallet_to_order_email($order, $sent_to_admin, $plain_text) {
    // Only add to customer emails for completed orders
    if ($sent_to_admin || $order->get_status() !== 'completed') {
        return;
    }

    $membership_products = ecs_get_membership_products($order);
    if (empty($membership_products)) {
        return;
    }

    $download_token = $order->get_meta('_wallet_pass_token');
    if (!$download_token) {
        return;
    }

    $info_url = ECS_PORTAL_URL . '/membership/wallet/pass/info?token=' . $download_token;
    $apple_url = ECS_PORTAL_URL . '/membership/wallet/pass/download?order=' . $order->get_id() . '&token=' . $download_token . '&platform=apple';

    if ($plain_text) {
        echo "\n\n";
        echo "===========================================\n";
        echo "YOUR DIGITAL MEMBERSHIP CARD\n";
        echo "===========================================\n\n";
        echo "Add your digital membership card to your phone's wallet:\n\n";
        echo "Apple Wallet: " . $apple_url . "\n";
        echo "View Pass Details: " . $info_url . "\n\n";
    } else {
        ?>
        <div style="margin: 30px 0; padding: 20px; background: #e8f5e9; border-radius: 8px; border-left: 4px solid #1a472a;">
            <h2 style="margin-top: 0; color: #1a472a;">📱 Your Digital Membership Card</h2>
            <p>Add your digital membership card to your phone's wallet for easy access at matches and events.</p>
            <p>
                <a href="<?php echo esc_url($apple_url); ?>"
                   style="display: inline-block; padding: 12px 24px; background: #000; color: #fff; text-decoration: none; border-radius: 8px; font-weight: 500;">
                    Add to Apple Wallet
                </a>
            </p>
            <p style="margin-bottom: 0;">
                <a href="<?php echo esc_url($info_url); ?>" style="color: #1a472a;">View pass details →</a>
            </p>
        </div>
        <?php
    }
}
add_action('woocommerce_email_order_details', 'ecs_add_wallet_to_order_email', 20, 3);

/**
 * Admin: Display wallet pass status in order edit page.
 *
 * @param WC_Order $order The order
 */
function ecs_admin_display_wallet_status($order) {
    $membership_products = ecs_get_membership_products($order);
    if (empty($membership_products)) {
        return;
    }

    $download_token = $order->get_meta('_wallet_pass_token');
    $pass_type = $membership_products[0]['pass_type'] ?? 'ecs_membership';

    ?>
    <div class="order_data_column" style="width: 100%; margin-top: 20px; padding: 15px; background: #f0f0f1; border-radius: 4px;">
        <h3 style="margin-top: 0;">🎫 Digital Wallet Pass</h3>

        <p>
            <strong>Pass Type:</strong>
            <?php echo $pass_type === 'ecs_membership' ? 'ECS Membership' : 'Pub League'; ?>
        </p>

        <?php if ($download_token): ?>
            <p>
                <strong>Status:</strong>
                <span style="color: #46b450;">✓ Pass Created</span>
            </p>
            <p>
                <strong>Download Token:</strong>
                <code><?php echo esc_html(substr($download_token, 0, 12) . '...'); ?></code>
            </p>
            <p>
                <a href="<?php echo esc_url(ECS_PORTAL_URL . '/membership/wallet/pass/info?token=' . $download_token); ?>"
                   target="_blank" class="button">
                    View Pass Details
                </a>
            </p>
        <?php else: ?>
            <p>
                <strong>Status:</strong>
                <span style="color: #dba617;">⏳ Pending</span>
            </p>
            <p>
                <em>Pass will be created when order is marked as completed.</em>
            </p>
        <?php endif; ?>
    </div>
    <?php
}
add_action('woocommerce_admin_order_data_after_order_details', 'ecs_admin_display_wallet_status');
