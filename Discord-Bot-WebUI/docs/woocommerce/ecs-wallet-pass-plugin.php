<?php
/**
 * Plugin Name: ECS Digital Wallet Pass
 * Plugin URI: https://weareecs.com
 * Description: Adds digital wallet pass (Apple Wallet & Google Wallet) download functionality to WooCommerce orders for ECS memberships and Pub League registrations.
 * Version: 1.0.0
 * Author: Emerald City Supporters
 * Author URI: https://weareecs.com
 * License: GPL v2 or later
 * License URI: https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain: ecs-wallet-pass
 * Requires at least: 5.8
 * Requires PHP: 7.4
 * WC requires at least: 5.0
 * WC tested up to: 8.0
 *
 * INSTALLATION:
 * 1. Download this file
 * 2. Go to WordPress Admin > Plugins > Add New > Upload Plugin
 * 3. Upload this file and click "Install Now"
 * 4. Activate the plugin
 * 5. Go to Settings > ECS Wallet Pass to configure
 */

// Prevent direct access
if (!defined('ABSPATH')) {
    exit;
}

// Check if WooCommerce is active
if (!in_array('woocommerce/woocommerce.php', apply_filters('active_plugins', get_option('active_plugins')))) {
    add_action('admin_notices', function() {
        echo '<div class="error"><p><strong>ECS Digital Wallet Pass</strong> requires WooCommerce to be installed and active.</p></div>';
    });
    return;
}

/**
 * Main Plugin Class
 */
class ECS_Wallet_Pass {

    /**
     * Plugin version
     */
    const VERSION = '1.0.0';

    /**
     * Single instance
     */
    private static $instance = null;

    /**
     * Portal URL
     */
    private $portal_url;

    /**
     * Webhook secret
     */
    private $webhook_secret;

    /**
     * Get single instance
     */
    public static function get_instance() {
        if (null === self::$instance) {
            self::$instance = new self();
        }
        return self::$instance;
    }

    /**
     * Constructor
     */
    private function __construct() {
        $this->portal_url = get_option('ecs_wallet_portal_url', 'https://portal.ecsfc.com');
        $this->webhook_secret = get_option('ecs_wallet_webhook_secret', '');

        // Admin settings
        add_action('admin_menu', array($this, 'add_settings_page'));
        add_action('admin_init', array($this, 'register_settings'));

        // WooCommerce hooks
        add_action('woocommerce_thankyou', array($this, 'display_wallet_download'), 20);
        add_action('woocommerce_order_details_after_order_table', array($this, 'display_wallet_on_order_details'));
        add_action('woocommerce_email_order_details', array($this, 'add_wallet_to_email'), 20, 3);
        add_filter('woocommerce_my_account_my_orders_actions', array($this, 'add_wallet_order_action'), 10, 2);
        add_action('woocommerce_admin_order_data_after_order_details', array($this, 'admin_display_wallet_status'));

        // AJAX handlers
        add_action('wp_ajax_ecs_check_wallet_pass', array($this, 'ajax_check_wallet_pass'));
        add_action('wp_ajax_nopriv_ecs_check_wallet_pass', array($this, 'ajax_check_wallet_pass'));

        // REST API callback endpoint
        add_action('rest_api_init', array($this, 'register_callback_endpoint'));

        // Add settings link to plugins page
        add_filter('plugin_action_links_' . plugin_basename(__FILE__), array($this, 'add_settings_link'));
    }

    /**
     * Add settings page to admin menu
     */
    public function add_settings_page() {
        add_options_page(
            'ECS Wallet Pass Settings',
            'ECS Wallet Pass',
            'manage_options',
            'ecs-wallet-pass',
            array($this, 'render_settings_page')
        );
    }

    /**
     * Register settings
     */
    public function register_settings() {
        register_setting('ecs_wallet_pass', 'ecs_wallet_portal_url');
        register_setting('ecs_wallet_pass', 'ecs_wallet_webhook_secret');
    }

    /**
     * Render settings page
     */
    public function render_settings_page() {
        ?>
        <div class="wrap">
            <h1>ECS Digital Wallet Pass Settings</h1>

            <form method="post" action="options.php">
                <?php settings_fields('ecs_wallet_pass'); ?>

                <table class="form-table">
                    <tr>
                        <th scope="row">
                            <label for="ecs_wallet_portal_url">Portal URL</label>
                        </th>
                        <td>
                            <input type="url" id="ecs_wallet_portal_url" name="ecs_wallet_portal_url"
                                   value="<?php echo esc_attr(get_option('ecs_wallet_portal_url', 'https://portal.ecsfc.com')); ?>"
                                   class="regular-text" placeholder="https://portal.ecsfc.com">
                            <p class="description">The URL of your ECS Portal (Flask application).</p>
                        </td>
                    </tr>
                    <tr>
                        <th scope="row">
                            <label for="ecs_wallet_webhook_secret">Webhook Secret</label>
                        </th>
                        <td>
                            <input type="text" id="ecs_wallet_webhook_secret" name="ecs_wallet_webhook_secret"
                                   value="<?php echo esc_attr(get_option('ecs_wallet_webhook_secret', '')); ?>"
                                   class="regular-text" placeholder="your-secret-key">
                            <p class="description">
                                Must match the <code>WALLET_WEBHOOK_SECRET</code> environment variable in your Portal.
                                <br>Use a strong random string (e.g., generate one at <a href="https://randomkeygen.com/" target="_blank">randomkeygen.com</a>).
                            </p>
                        </td>
                    </tr>
                </table>

                <?php submit_button(); ?>
            </form>

            <hr>

            <h2>WooCommerce Webhook Setup</h2>
            <p>You also need to create a webhook in WooCommerce to notify the Portal when orders are updated:</p>

            <ol>
                <li>Go to <strong>WooCommerce > Settings > Advanced > Webhooks</strong></li>
                <li>Click <strong>"Add webhook"</strong></li>
                <li>Configure:
                    <ul>
                        <li><strong>Name:</strong> ECS Wallet Pass</li>
                        <li><strong>Status:</strong> Active</li>
                        <li><strong>Topic:</strong> Order updated <em>(Note: WooCommerce doesn't have "Order completed" - the Portal filters by status)</em></li>
                        <li><strong>Delivery URL:</strong> <code><?php echo esc_html(get_option('ecs_wallet_portal_url', 'https://portal.ecsfc.com')); ?>/api/v1/wallet/webhook/order-completed</code></li>
                        <li><strong>Secret:</strong> <em>(same as Webhook Secret above)</em></li>
                        <li><strong>API Version:</strong> WP REST API Integration v3</li>
                    </ul>
                </li>
                <li>Click <strong>"Save webhook"</strong></li>
            </ol>
            <p class="description"><strong>Why "Order updated"?</strong> WooCommerce sends this webhook whenever an order status changes. The Portal checks the order status and only creates passes when the status is "completed".</p>

            <h3>Test Connection</h3>
            <p>
                <a href="<?php echo esc_url(get_option('ecs_wallet_portal_url', 'https://portal.ecsfc.com') . '/api/v1/wallet/webhook/test'); ?>"
                   target="_blank" class="button">
                    Test Portal Connection
                </a>
                <span class="description">Opens in new tab - should show JSON response if Portal is reachable.</span>
            </p>

            <hr>

            <h2>Product Name Patterns</h2>
            <p>The plugin automatically detects membership products based on their names. Products matching these patterns will automatically generate digital wallet passes when orders are completed.</p>
            <p><strong>Note:</strong> Pattern matching is case-insensitive and ignores text in parentheses like "(testing)".</p>

            <table class="widefat" style="max-width: 700px;">
                <thead>
                    <tr>
                        <th>Pass Type</th>
                        <th>Product Name Examples</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td><strong>ECS Membership</strong></td>
                        <td>
                            <code>ECS 2026 Membership Card</code><br>
                            <code>ECS 2026 Membership Card (testing)</code> <em style="color: #666;">(for testing)</em><br>
                            <code>ECS Membership 2025</code><br>
                            <code>ECS Membership Card</code><br>
                            <code>ECS Membership Package 2024</code>
                        </td>
                    </tr>
                    <tr>
                        <td><strong>Pub League</strong></td>
                        <td>
                            <code>Pub League Registration</code><br>
                            <code>Pub League Spring 2025</code><br>
                            <code>Pub League Fall 2025</code><br>
                            <code>Pub League Season</code>
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
        <?php
    }

    /**
     * Add settings link to plugins page
     */
    public function add_settings_link($links) {
        $settings_link = '<a href="options-general.php?page=ecs-wallet-pass">Settings</a>';
        array_unshift($links, $settings_link);
        return $links;
    }

    /**
     * Get membership product patterns
     *
     * Patterns are case-insensitive and support optional suffixes like "(testing)"
     * Examples that will match:
     * - "ECS 2026 Membership Card"
     * - "ECS 2026 Membership Card (testing)"
     * - "ECS Membership 2025"
     * - "ECS Membership Package 2024"
     */
    public function get_product_patterns() {
        return array(
            'ecs_membership' => array(
                '/ECS\s+\d{4}\s+Membership/i',      // "ECS 2026 Membership Card" or "ECS 2026 Membership Card (testing)"
                '/ECS\s+Membership\s+\d{4}/i',      // "ECS Membership 2025"
                '/ECS\s+Membership\s+Card/i',       // "ECS Membership Card"
                '/ECS\s+Membership\s+Package/i',    // "ECS Membership Package"
            ),
            'pub_league' => array(
                '/Pub\s+League.*Registration/i',
                '/Pub\s+League.*(Spring|Fall|Summer|Winter)/i',
                '/Pub\s+League.*Season/i',
            ),
        );
    }

    /**
     * Check if order contains membership products
     */
    public function get_membership_products($order) {
        $membership_products = array();
        $patterns = $this->get_product_patterns();

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
                        break 2;
                    }
                }
            }
        }

        return $membership_products;
    }

    /**
     * Display wallet download on thank you page
     */
    public function display_wallet_download($order_id) {
        $order = wc_get_order($order_id);
        if (!$order) return;

        // Show download buttons for paid orders (processing = paid, completed = fulfilled)
        $valid_statuses = array('processing', 'completed');
        if (!in_array($order->get_status(), $valid_statuses)) return;

        $membership_products = $this->get_membership_products($order);
        if (empty($membership_products)) return;

        $download_token = $order->get_meta('_wallet_pass_token');

        if (!$download_token) {
            $this->render_loading_state($order_id);
            return;
        }

        $this->render_wallet_buttons($download_token, $order_id, $membership_products);
    }

    /**
     * Render loading state while pass is being generated
     */
    private function render_loading_state($order_id) {
        ?>
        <section class="ecs-wallet-pass-section" style="margin-top: 30px; padding: 20px; background: #f8f8f8; border-radius: 8px;">
            <h2 style="margin-top: 0; color: #1a472a;">
                <span style="margin-right: 10px;">📱</span>
                Your Digital Membership Card
            </h2>
            <p>Your digital membership card is being prepared...</p>
            <div id="wallet-pass-loading">
                <p><em>Please wait a moment while we generate your pass.</em></p>
                <div class="ecs-loading-spinner" style="display: inline-block; width: 20px; height: 20px; border: 3px solid #ddd; border-top-color: #1a472a; border-radius: 50%; animation: ecs-spin 1s linear infinite;"></div>
            </div>
            <div id="wallet-pass-buttons" style="display: none;"></div>
            <style>
                @keyframes ecs-spin { to { transform: rotate(360deg); } }
            </style>
            <script>
            (function() {
                var pollCount = 0;
                var maxPolls = 30;

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
                            if (data.success && data.html) {
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
    }

    /**
     * Render wallet download buttons
     */
    public function render_wallet_buttons($download_token, $order_id, $membership_products) {
        $apple_url = $this->portal_url . '/membership/wallet/pass/download?order=' . $order_id . '&token=' . $download_token . '&platform=apple';
        $google_url = $this->portal_url . '/membership/wallet/pass/download?order=' . $order_id . '&token=' . $download_token . '&platform=google';
        $info_url = $this->portal_url . '/membership/wallet/pass/info?token=' . $download_token;

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
                <a href="<?php echo esc_url($apple_url); ?>"
                   class="wallet-button"
                   style="display: inline-flex; align-items: center; padding: 12px 24px; background: #000; color: #fff; text-decoration: none; border-radius: 8px; font-weight: 500;">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor" style="margin-right: 10px;">
                        <path d="M18.71 19.5c-.83 1.24-1.71 2.45-3.05 2.47-1.34.03-1.77-.79-3.29-.79-1.53 0-2 .77-3.27.82-1.31.05-2.3-1.32-3.14-2.53C4.25 17 2.94 12.45 4.7 9.39c.87-1.52 2.43-2.48 4.12-2.51 1.28-.02 2.5.87 3.29.87.78 0 2.26-1.07 3.81-.91.65.03 2.47.26 3.64 1.98-.09.06-2.17 1.28-2.15 3.81.03 3.02 2.65 4.03 2.68 4.04-.03.07-.42 1.44-1.38 2.83M13 3.5c.73-.83 1.94-1.46 2.94-1.5.13 1.17-.34 2.35-1.04 3.19-.69.85-1.83 1.51-2.95 1.42-.15-1.15.41-2.35 1.05-3.11z"/>
                    </svg>
                    Add to Apple Wallet
                </a>

                <a href="<?php echo esc_url($google_url); ?>"
                   class="wallet-button"
                   style="display: inline-flex; align-items: center; padding: 12px 24px; background: #4285f4; color: #fff; text-decoration: none; border-radius: 8px; font-weight: 500;">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor" style="margin-right: 10px;">
                        <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                        <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                        <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                        <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                    </svg>
                    Add to Google Wallet
                </a>
            </div>

            <p style="margin: 0; font-size: 0.9em; color: #666;">
                <a href="<?php echo esc_url($info_url); ?>" target="_blank" style="color: <?php echo $is_ecs ? '#1a472a' : '#213e96'; ?>;">
                    View pass details →
                </a>
            </p>
        </section>
        <?php
    }

    /**
     * AJAX handler to check pass status
     */
    public function ajax_check_wallet_pass() {
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
            $membership_products = $this->get_membership_products($order);

            ob_start();
            $this->render_wallet_buttons($download_token, $order_id, $membership_products);
            $html = ob_get_clean();

            wp_send_json(array(
                'success' => true,
                'token' => $download_token,
                'html' => $html,
            ));
        }

        wp_send_json(array('success' => false));
    }

    /**
     * Register REST API callback endpoint
     */
    public function register_callback_endpoint() {
        register_rest_route('ecs/v1', '/wallet-callback', array(
            'methods' => 'POST',
            'callback' => array($this, 'handle_wallet_callback'),
            'permission_callback' => array($this, 'verify_callback_permission'),
        ));
    }

    /**
     * Verify callback permission
     */
    public function verify_callback_permission($request) {
        $provided_secret = $request->get_header('X-Webhook-Secret');

        if (empty($this->webhook_secret)) {
            return true; // No secret configured - allow for testing
        }

        return hash_equals($this->webhook_secret, $provided_secret);
    }

    /**
     * Handle wallet callback from Portal
     */
    public function handle_wallet_callback($request) {
        $params = $request->get_json_params();

        $order_id = isset($params['order_id']) ? intval($params['order_id']) : 0;
        $download_token = isset($params['download_token']) ? sanitize_text_field($params['download_token']) : '';

        if (!$order_id || !$download_token) {
            return new WP_Error('invalid_params', 'Missing order_id or download_token', array('status' => 400));
        }

        $order = wc_get_order($order_id);
        if ($order) {
            $order->update_meta_data('_wallet_pass_token', $download_token);
            $order->save();

            // Send dedicated wallet pass email with download links
            $this->send_wallet_pass_email($order, $download_token);
        }

        return array(
            'success' => true,
            'message' => 'Token stored for order ' . $order_id,
        );
    }

    /**
     * Send dedicated email with wallet pass download links
     * This is triggered after the pass is created via callback from the Portal
     */
    private function send_wallet_pass_email($order, $download_token) {
        $to = $order->get_billing_email();
        if (!$to) {
            return;
        }

        $subject = 'Your ECS Digital Membership Card is Ready!';

        $apple_url = $this->portal_url . '/membership/wallet/pass/download?order=' . $order->get_id() . '&token=' . $download_token . '&platform=apple';
        $google_url = $this->portal_url . '/membership/wallet/pass/download?order=' . $order->get_id() . '&token=' . $download_token . '&platform=google';

        $message = $this->get_wallet_email_template($order, $apple_url, $google_url);

        $headers = array('Content-Type: text/html; charset=UTF-8');

        // Use WooCommerce mailer if available for consistent styling
        if (function_exists('WC') && WC()->mailer()) {
            $mailer = WC()->mailer();
            $message = $mailer->wrap_message($subject, $message);
        }

        wp_mail($to, $subject, $message, $headers);
    }

    /**
     * Get HTML template for wallet pass email
     */
    private function get_wallet_email_template($order, $apple_url, $google_url) {
        $customer_name = $order->get_billing_first_name();

        return '
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="text-align: center; padding: 20px; background-color: #006633;">
                <h1 style="color: #ffffff; margin: 0;">Emerald City Supporters</h1>
            </div>

            <div style="padding: 30px; background-color: #ffffff;">
                <h2 style="color: #006633; margin-top: 0;">Your Digital Membership Card is Ready!</h2>

                <p>Hi ' . esc_html($customer_name) . ',</p>

                <p>Great news! Your ECS membership card is ready to add to your phone\'s wallet.
                   Use the buttons below to add your pass:</p>

                <div style="margin: 30px 0; text-align: center;">
                    <a href="' . esc_url($apple_url) . '"
                       style="display: inline-block; padding: 15px 30px; background: #000000; color: #ffffff;
                              text-decoration: none; border-radius: 8px; margin: 10px; font-weight: bold;">
                        Add to Apple Wallet
                    </a>
                    <br><br>
                    <a href="' . esc_url($google_url) . '"
                       style="display: inline-block; padding: 15px 30px; background: #4285f4; color: #ffffff;
                              text-decoration: none; border-radius: 8px; margin: 10px; font-weight: bold;">
                        Add to Google Wallet
                    </a>
                </div>

                <p style="color: #666666; font-size: 14px;">
                    <strong>Tip:</strong> Open this email on your phone and tap the button for your device type.
                </p>

                <hr style="border: none; border-top: 1px solid #eeeeee; margin: 30px 0;">

                <p style="color: #999999; font-size: 12px;">
                    Order #' . $order->get_id() . '<br>
                    If you have any questions, please contact us at info@weareecs.com
                </p>
            </div>

            <div style="text-align: center; padding: 20px; background-color: #f5f5f5; color: #666666; font-size: 12px;">
                Emerald City Supporters &bull; Seattle, WA
            </div>
        </div>';
    }

    /**
     * Display wallet on order details page
     */
    public function display_wallet_on_order_details($order) {
        // Show for paid orders (processing = paid, completed = fulfilled)
        $valid_statuses = array('processing', 'completed');
        if (!in_array($order->get_status(), $valid_statuses)) return;

        $membership_products = $this->get_membership_products($order);
        if (empty($membership_products)) return;

        $download_token = $order->get_meta('_wallet_pass_token');
        if (!$download_token) {
            echo '<p><em>Your digital membership card is being generated. Please check back soon.</em></p>';
            return;
        }

        $this->render_wallet_buttons($download_token, $order->get_id(), $membership_products);
    }

    /**
     * Add wallet to order emails
     */
    public function add_wallet_to_email($order, $sent_to_admin, $plain_text) {
        // Include in emails for paid orders (processing = paid, completed = fulfilled)
        $valid_statuses = array('processing', 'completed');
        if ($sent_to_admin || !in_array($order->get_status(), $valid_statuses)) return;

        $membership_products = $this->get_membership_products($order);
        if (empty($membership_products)) return;

        $download_token = $order->get_meta('_wallet_pass_token');
        if (!$download_token) return;

        $info_url = $this->portal_url . '/membership/wallet/pass/info?token=' . $download_token;
        $apple_url = $this->portal_url . '/membership/wallet/pass/download?order=' . $order->get_id() . '&token=' . $download_token . '&platform=apple';

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

    /**
     * Add wallet action to My Account orders
     */
    public function add_wallet_order_action($actions, $order) {
        // Show action for paid orders (processing = paid, completed = fulfilled)
        $valid_statuses = array('processing', 'completed');
        if (!in_array($order->get_status(), $valid_statuses)) return $actions;

        $membership_products = $this->get_membership_products($order);
        if (empty($membership_products)) return $actions;

        $download_token = $order->get_meta('_wallet_pass_token');
        if (!$download_token) return $actions;

        $info_url = $this->portal_url . '/membership/wallet/pass/info?token=' . $download_token;

        $actions['wallet_pass'] = array(
            'url' => $info_url,
            'name' => 'Digital Pass',
        );

        return $actions;
    }

    /**
     * Display wallet status in admin order page
     */
    public function admin_display_wallet_status($order) {
        $membership_products = $this->get_membership_products($order);
        if (empty($membership_products)) return;

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
                    <a href="<?php echo esc_url($this->portal_url . '/membership/wallet/pass/info?token=' . $download_token); ?>"
                       target="_blank" class="button">
                        View Pass Details
                    </a>
                </p>
            <?php else: ?>
                <p>
                    <strong>Status:</strong>
                    <span style="color: #dba617;">⏳ Pending</span>
                </p>
                <p><em>Pass will be created when payment is received.</em></p>
            <?php endif; ?>
        </div>
        <?php
    }
}

// Initialize plugin
ECS_Wallet_Pass::get_instance();
