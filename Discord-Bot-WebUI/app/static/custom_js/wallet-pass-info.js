'use strict';

/**
 * Wallet Pass Info Module
 *
 * Handles wallet pass info page functionality including:
 * - iOS non-Safari browser detection
 * - Copy link to clipboard functionality
 *
 * @version 1.0.0
 */

import { InitSystem } from '../js/init-system.js';

/**
 * Initialize the wallet pass info module
 */
function init() {
    // Only run on pass info pages
    const safariWarning = document.getElementById('safari-warning');
    if (!safariWarning) return;

    // Detect iOS + non-Safari browser and show warning
    detectIOSNonSafari();

    console.log('[WalletPassInfo] Initialized');
}

/**
 * Detect iOS device running non-Safari browser
 */
function detectIOSNonSafari() {
    const ua = navigator.userAgent;
    const isIOS = /iPad|iPhone|iPod/.test(ua) && !window.MSStream;
    const isSafari = /Safari/.test(ua) && !/Chrome|CriOS|FxiOS|EdgiOS|OPiOS/.test(ua);

    if (isIOS && !isSafari) {
        const warning = document.getElementById('safari-warning');
        if (warning) {
            warning.classList.remove('d-none');
        }
    }
}

/**
 * Copy the current page link to clipboard
 */
function copyPageLink() {
    const feedbackEl = document.getElementById('copy-feedback');

    navigator.clipboard.writeText(window.location.href).then(function() {
        showCopyFeedback(feedbackEl);
    }).catch(function() {
        // Fallback for older browsers
        const textArea = document.createElement('textarea');
        textArea.value = window.location.href;
        textArea.style.position = 'fixed';
        textArea.style.left = '-9999px';
        document.body.appendChild(textArea);
        textArea.select();

        try {
            document.execCommand('copy');
            showCopyFeedback(feedbackEl);
        } catch (err) {
            console.error('[WalletPassInfo] Copy failed:', err);
        }

        document.body.removeChild(textArea);
    });
}

/**
 * Show the copy feedback message
 */
function showCopyFeedback(feedbackEl) {
    if (feedbackEl) {
        feedbackEl.classList.remove('d-none');
        setTimeout(function() {
            feedbackEl.classList.add('d-none');
        }, 3000);
    }
}

// Register with EventDelegation system
if (typeof EventDelegation !== 'undefined') {
    EventDelegation.register('copy-link', function(element, event) {
        copyPageLink();
    });
}

// Register with InitSystem
InitSystem.register('wallet-pass-info', init, {
    priority: 30,
    description: 'Wallet pass info module'
});

// Fallback for non-module usage
document.addEventListener('DOMContentLoaded', init);

// Export for use in templates
window.WalletPassInfo = {
    init,
    copyPageLink,
    detectIOSNonSafari
};
