document.addEventListener('DOMContentLoaded', function () {
    const enable2FABtn = document.getElementById('enable2FABtn');
    const verify2FAForm = document.getElementById('verify2FAForm');
    const disable2FAForm = document.getElementById('disable2FAForm');

    if (enable2FABtn) {
        enable2FABtn.addEventListener('click', function () {
            fetch('/account/enable-2fa')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('qrCodeContainer').innerHTML = `<img src="data:image/png;base64,${data.qr_code}" alt="QR Code">`;
                    document.getElementById('enable2FAModal').setAttribute('data-secret', data.secret);
                    new bootstrap.Modal(document.getElementById('enable2FAModal')).show();
                });
        });
    }

    if (verify2FAForm) {
        verify2FAForm.addEventListener('submit', function (e) {
            e.preventDefault();
            const code = document.getElementById('twoFactorCode').value;
            const secret = document.getElementById('enable2FAModal').getAttribute('data-secret');
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
});