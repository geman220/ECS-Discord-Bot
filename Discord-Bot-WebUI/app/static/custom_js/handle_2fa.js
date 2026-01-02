/**
 * 2FA Enable/Disable Handler
 * Manages 2FA setup modal and form submission
 */
import { InitSystem } from '../js/init-system.js';
import { ModalManager } from '../js/modal-manager.js';

let _initialized = false;

function init() {
    if (_initialized) return;
    _initialized = true;

    const enable2FABtn = document.getElementById('enable2FABtn');
    const verify2FAForm = document.getElementById('verify2FAForm');
    const disable2FAForm = document.getElementById('disable2FAForm');

    if (enable2FABtn) {
        enable2FABtn.addEventListener('click', function () {
            fetch('/account/enable-2fa')
                .then(response => response.json())
                .then(data => {
                    const qrContainer = document.getElementById('qrCodeContainer');
                    const modal = document.getElementById('enable2FAModal');
                    if (qrContainer) {
                        qrContainer.innerHTML = `<img src="data:image/png;base64,${data.qr_code}" alt="QR Code">`;
                    }
                    if (modal) {
                        modal.setAttribute('data-secret', data.secret);
                    }
                    // Use window.ModalManager for safe modal handling
                    window.ModalManager.show('enable2FAModal');
                });
        });
    }

    if (verify2FAForm) {
        verify2FAForm.addEventListener('submit', function (e) {
            e.preventDefault();
            const codeInput = document.getElementById('twoFactorCode');
            const modal = document.getElementById('enable2FAModal');
            if (!codeInput || !modal) return;

            const code = codeInput.value;
            const secret = modal.getAttribute('data-secret');

            fetch('/account/enable-2fa', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ code, secret })
            })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        alert('2FA enabled successfully');
                        location.reload();
                    } else {
                        alert(data.message);
                    }
                });
        });
    }

    if (disable2FAForm) {
        disable2FAForm.addEventListener('submit', function (e) {
            e.preventDefault();
            if (confirm('Are you sure you want to disable 2FA? This will make your account less secure.')) {
                this.submit();
            }
        });
    }
}

// Register with window.InitSystem (primary)
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('handle-2fa', init, {
        priority: 45,
        reinitializable: false,
        description: '2FA enable/disable handler'
    });
}

// Fallback
// window.InitSystem handles initialization
