/**
 * Wallet Pass Scanner
 *
 * QR code scanner for validating digital wallet passes.
 * Uses @AziDev/qrcodescanner library for camera-based scanning.
 */
'use strict';

import { InitSystem } from '../js/init-system.js';

let _initialized = false;

// Audio feedback (base64 encoded short beeps)
const successBeep = new Audio('data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQoGAACBhYqFbF1fdXqMj4ODfXp3d39/f4WHiIiJioqLioqLjIyMjI2MjIyMjIyLi4qKiYiHhYSCf3x5dXFtaWVhXltYVVJPTUpHREJAPj06ODYzMTAvLSsqKCcmJSQjIyIiISEhISEhIiIjIyQlJicpKy0vMTM1Nzk7PkBCREdJS05RVFdaXWBjZmltcHN2eXyAgoWHiYuMjo+QkZGRkZGRkZCPjo2LiYeEgn97eHRxbWlmYl9bWFVRTkpHREE+Ojc0MjAvLSsqKCcmJSQkJCQkJCUlJSYnKCkrLC4wMjQ2ODs9QEJFS01QUlVYW19iZWhrbm51eHp9gIOGiIqMjo+QkJGRkZGQkI+OjYuJh4SCfnp3c3BsaGRgXFhVUU1KRkI/Ozg1MzEvLSwqKSgnJiYmJiYmJicnKCkqKywuLzEzNTc5Oz4AQENGSUxPUlVYW11gY2Zpam1vcnR2eHp8foGDhYeJiouMjY2NjY2NjIuKiYeGhIOBfnt5dnNwbWplYl5bV1RQTUlGQz88OTY0MjAvLSwrKikoKCgoKCgoKSkqKistLi8xMzU3Ojo8P0FFSE1QU1ZZXGBjZmlsbm9wcXFxcXFxcHBvbm1ramhnZWRiYF5cWlhWVFJQT01LSUdFREJAPz08Ozo4NzY1NDMyMTEwMC8vLy4uLi4uLi4uLi8vLzAwMTEyMzQ1Njc4OTs8Pj9BQkRGSElLTE5PUVJUVVdYWlpbXF1eXl9fYGBgYGBgYF9fXl5dXFtaWVhWVVRSUU9OTEtJSEdFREJBPz48Ozo5');
const errorBeep = new Audio('data:audio/wav;base64,UklGRl4GAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YToGAACAgICAgICAgICAgICAgICAgICAgICAgIB/f35+fX18fHt7enp5eXh4d3d2dnV1dHRzc3JycXFwcG9vbm5tbWxsa2tqamlpaGhnZ2ZmZWVkZGNjYmJhYWBgX19eXl1dXFxbW1paWVlYWFdXVlZVVVRUU1NSUlFRUFBPT05OTU1MTEtLSkpJSUhIR0dGRkVFRERDQ0JCQUFAQAAAAAAAAAAAAQECAgMDBAQFBQYGBwcICAkJCgoLCwwMDQ0ODg8PEBARERITFBQVFRYXGBYZGR');

// State
let scanner = null;
let scanStats = { valid: 0, invalid: 0, total: 0 };
let recentBarcodes = new Set();

// DOM Elements
let video, startBtn, stopBtn, manualInput, manualSubmit;
let resultCard, resultBody, scanHistory, eventNameInput, autoCheckinBox, clearHistoryBtn;

/**
 * Initialize scanner
 */
function initScanner() {
    if (typeof QrCodeScanner === 'undefined') {
        console.warn('[WalletScanner] QR Scanner library not loaded');
        startBtn.innerHTML = '<i class="ti ti-camera-off me-1"></i>Camera Unavailable';
        startBtn.classList.replace('btn-primary', 'btn-secondary');
        startBtn.disabled = true;
        return;
    }

    try {
        scanner = new QrCodeScanner(video, handleScan, {
            highlightScanRegion: true,
            highlightCodeOutline: true
        });
    } catch (err) {
        console.error('[WalletScanner] Init error:', err);
    }
}

/**
 * Start camera scanning
 */
async function startScanning() {
    try {
        await scanner.start({ facingMode: 'environment' });
        startBtn.disabled = true;
        stopBtn.disabled = false;
        recentBarcodes.clear();
    } catch (err) {
        console.error('[WalletScanner] Start error:', err);
        if (window.Swal) {
            window.Swal.fire({
                title: 'Camera Error',
                text: 'Could not access camera. Please ensure camera permissions are granted and try again.',
                icon: 'error'
            });
        } else {
            alert('Could not access camera. Please ensure camera permissions are granted and try again.');
        }
    }
}

/**
 * Stop camera scanning
 */
function stopScanning() {
    if (scanner) {
        scanner.stop();
    }
    startBtn.disabled = false;
    stopBtn.disabled = true;
}

/**
 * Handle scanned QR code
 */
function handleScan(result) {
    const barcode = result.data;

    // Prevent duplicate scans within 3 seconds
    if (recentBarcodes.has(barcode)) return;
    recentBarcodes.add(barcode);
    setTimeout(() => recentBarcodes.delete(barcode), 3000);

    validateBarcode(barcode);
}

/**
 * Validate barcode via API
 */
async function validateBarcode(barcode) {
    const eventName = eventNameInput.value.trim();
    const autoCheckin = autoCheckinBox.checked;

    try {
        const response = await fetch('/api/v1/wallet/validate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                barcode: barcode,
                event_name: eventName || null,
                check_in: autoCheckin
            })
        });

        const data = await response.json();

        if (response.ok) {
            displayResult(data);
            addToHistory(data);
            updateStats(data.valid);

            if (data.valid) {
                successBeep.play().catch(() => {});
                resultCard.classList.add('beep-success');
            } else {
                errorBeep.play().catch(() => {});
                resultCard.classList.add('beep-error');
            }
            setTimeout(() => resultCard.classList.remove('beep-success', 'beep-error'), 500);
        } else {
            displayError(data.error || 'Validation failed');
            addToHistory({ valid: false, error: data.error, barcode: barcode });
            updateStats(false);
            errorBeep.play().catch(() => {});
        }
    } catch (err) {
        console.error('[WalletScanner] Validation error:', err);
        displayError('Network error - please check connection');
    }
}

/**
 * Display validation result
 */
function displayResult(data) {
    const pass = data.pass;
    const isValid = data.valid;

    resultCard.classList.remove('valid', 'invalid');
    resultCard.classList.add(isValid ? 'valid' : 'invalid');

    let statusBadge = isValid
        ? '<span class="badge bg-success fs-6" data-badge><i class="ti ti-check me-1"></i>VALID</span>'
        : '<span class="badge bg-danger fs-6" data-badge><i class="ti ti-x me-1"></i>INVALID</span>';

    let alertHtml = '';
    if (!isValid && data.reason) {
        alertHtml = `<div class="alert alert-danger mt-3 mb-0" data-alert><i class="ti ti-alert-circle me-1"></i>${data.reason}</div>`;
    }
    if (data.check_in_recorded) {
        alertHtml += '<div class="alert alert-success mt-3 mb-0" data-alert><i class="ti ti-check me-1"></i>Check-in recorded successfully</div>';
    }

    resultBody.innerHTML = `
        <div class="d-flex justify-content-between align-items-start mb-3">
            <h4 class="mb-0">${pass.member_name}</h4>
            ${statusBadge}
        </div>
        <div class="c-table-wrapper" data-table-responsive>
            <table class="c-table c-table--compact mb-0" data-mobile-table data-table-type="checkins" data-table>
                <tr><td class="text-muted u-w-35-percent">Email</td><td>${pass.member_email || '-'}</td></tr>
                <tr><td class="text-muted">Pass Type</td><td><span class="badge bg-label-primary" data-badge>${pass.pass_type || '-'}</span></td></tr>
                <tr><td class="text-muted">Validity</td><td>${pass.validity || '-'}</td></tr>
                ${pass.team_name ? `<tr><td class="text-muted">Team</td><td>${pass.team_name}</td></tr>` : ''}
                <tr><td class="text-muted">Status</td><td>${pass.status}</td></tr>
            </table>
        </div>
        ${alertHtml}
    `;
}

/**
 * Display error
 */
function displayError(message) {
    resultCard.classList.remove('valid', 'invalid');
    resultCard.classList.add('invalid');
    resultBody.innerHTML = `
        <div class="text-center text-danger py-4">
            <i class="ti ti-alert-triangle mb-2 u-icon-3xl"></i>
            <p class="mb-0 fw-semibold">${message}</p>
        </div>
    `;
}

/**
 * Add to scan history
 */
function addToHistory(data) {
    const historyEmpty = scanHistory.querySelector('.text-muted');
    if (historyEmpty) scanHistory.innerHTML = '';

    const time = new Date().toLocaleTimeString();
    const isValid = data.valid;
    const name = data.pass ? data.pass.member_name : (data.barcode || 'Unknown');

    const item = document.createElement('div');
    item.className = `scan-history-item ${isValid ? 'valid' : 'invalid'}`;
    item.innerHTML = `
        <div class="d-flex justify-content-between align-items-center">
            <div>
                <strong>${name}</strong>
                ${data.pass ? `<br><small class="text-muted">${data.pass.pass_type}</small>` : ''}
            </div>
            <div class="text-end">
                <span class="badge ${isValid ? 'bg-success' : 'bg-danger'}" data-badge>${isValid ? 'Valid' : 'Invalid'}</span>
                <br><small class="text-muted">${time}</small>
            </div>
        </div>
    `;

    scanHistory.insertBefore(item, scanHistory.firstChild);
    while (scanHistory.children.length > 20) scanHistory.removeChild(scanHistory.lastChild);
}

/**
 * Update stats
 */
function updateStats(isValid) {
    scanStats.total++;
    if (isValid) scanStats.valid++;
    else scanStats.invalid++;

    document.getElementById('stat-valid').textContent = scanStats.valid;
    document.getElementById('stat-invalid').textContent = scanStats.invalid;
    document.getElementById('stat-total').textContent = scanStats.total;
}

/**
 * Clear history
 */
function clearHistory() {
    scanHistory.innerHTML = '<div class="text-center text-muted py-4"><small>No scans in this session</small></div>';
    scanStats = { valid: 0, invalid: 0, total: 0 };
    document.getElementById('stat-valid').textContent = '0';
    document.getElementById('stat-invalid').textContent = '0';
    document.getElementById('stat-total').textContent = '0';
    resultCard.classList.remove('valid', 'invalid');
    resultBody.innerHTML = '<div class="text-center text-muted py-5"><i class="ti ti-qrcode mb-2 u-icon-3xl"></i><p class="mb-0">Scan a pass to see validation results</p></div>';
}

/**
 * Initialize module
 */
function init() {
    if (_initialized) return;

    // Get DOM elements
    video = document.getElementById('scanner-video');
    startBtn = document.getElementById('start-scanner');
    stopBtn = document.getElementById('stop-scanner');
    manualInput = document.getElementById('manual-barcode');
    manualSubmit = document.getElementById('manual-submit');
    resultCard = document.getElementById('result-card');
    resultBody = document.getElementById('result-body');
    scanHistory = document.getElementById('scan-history');
    eventNameInput = document.getElementById('event-name');
    autoCheckinBox = document.getElementById('auto-checkin');
    clearHistoryBtn = document.getElementById('clear-history');

    // Check if we're on the scanner page
    if (!video || !startBtn) return;

    _initialized = true;

    // Bind event listeners
    startBtn.addEventListener('click', startScanning);
    stopBtn.addEventListener('click', stopScanning);

    manualSubmit.addEventListener('click', function() {
        const barcode = manualInput.value.trim();
        if (barcode) {
            validateBarcode(barcode);
            manualInput.value = '';
        }
    });

    manualInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') manualSubmit.click();
    });

    clearHistoryBtn.addEventListener('click', clearHistory);

    // Initialize scanner
    initScanner();

    console.log('[WalletScanner] Initialized');
}

// Export functions
export {
    init,
    startScanning,
    stopScanning,
    validateBarcode,
    clearHistory
};

// Register with InitSystem
if (InitSystem && InitSystem.register) {
    InitSystem.register('wallet-scanner', init, {
        priority: 30,
        reinitializable: false,
        description: 'Wallet pass QR scanner'
    });
}

// Fallback initialization
// InitSystem handles initialization

// Backward compatibility
window.WalletScanner = {
    init,
    startScanning,
    stopScanning,
    validateBarcode,
    clearHistory
};
