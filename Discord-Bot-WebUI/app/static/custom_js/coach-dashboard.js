/**
 * ============================================================================
 * COACH DASHBOARD JAVASCRIPT
 * ============================================================================
 *
 * Handles all coach dashboard functionality including:
 * - Match reporting form submission
 * - Substitute request workflow
 * - CSRF token management
 *
 * ARCHITECTURAL COMPLIANCE:
 * - Event delegation for dynamic elements
 * - Data-attribute based hooks ([data-action], [data-match-id])
 * - IIFE pattern for encapsulation
 * - No direct element binding by ID where possible
 *
 * ============================================================================
 */
// ES Module
'use strict';

/**
     * Get CSRF token from meta tag
     * @returns {string} CSRF token value
     */
    export function getCsrfToken() {
        const csrfMeta = document.querySelector('meta[name="csrf-token"]');
        return csrfMeta ? csrfMeta.content : '';
    }

    /**
     * Request a substitute for a match
     * Shows SweetAlert2 dialog for input and submits to appropriate endpoint
     *
     * @param {string} matchId - Match ID
     * @param {string} leagueType - 'ECS FC' or 'Premier'/'Classic'
     * @param {string} teamId - Team ID for Pub League matches
     */
    async function requestSub(matchId, leagueType, teamId) {
        // Check if SweetAlert2 is available
        if (typeof window.Swal === 'undefined') {
            console.warn('SweetAlert2 not available for substitute request');
            return;
        }

        const result = await window.Swal.fire({
            title: 'Request Substitute',
            html: `
                <div class="mb-3">
                    <label class="form-label">Number of subs needed:</label>
                    <input type="number" id="subs-needed" class="form-control" value="1" min="1" max="5" data-form-control>
                </div>
                <div class="mb-3">
                    <label class="form-label">Positions needed:</label>
                    <input type="text" id="positions" class="form-control" placeholder="e.g., Forward, Midfielder" data-form-control>
                </div>
                <div class="mb-3">
                    <label class="form-label">Notes (optional):</label>
                    <textarea id="notes" class="form-control" rows="3" placeholder="Any additional information..." data-form-control></textarea>
                </div>
            `,
            showCancelButton: true,
            confirmButtonText: 'Request Sub',
            preConfirm: () => {
                return {
                    substitutes_needed: document.getElementById('subs-needed').value,
                    positions_needed: document.getElementById('positions').value,
                    notes: document.getElementById('notes').value
                };
            }
        });

        if (!result.isConfirmed) return;

        try {
            // Determine endpoint and build FormData based on league type
            let endpoint;
            const formData = new FormData();
            const csrfToken = getCsrfToken();

            formData.append('csrf_token', csrfToken);
            formData.append('substitutes_needed', result.value.substitutes_needed);
            formData.append('positions_needed', result.value.positions_needed);
            formData.append('notes', result.value.notes);

            if (leagueType === 'ECS FC') {
                // ECS FC: endpoint expects integer match_id in URL path
                endpoint = `/ecs-fc/sub-request/${matchId}`;
            } else {
                // Pub League (Premier or Classic): needs match_id and team_id in form data
                endpoint = '/admin/request_sub';
                formData.append('match_id', matchId);
                formData.append('team_id', teamId);
            }

            const response = await fetch(endpoint, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken
                },
                body: formData
            });

            // Both endpoints redirect on success, so any 2xx or 3xx response means success
            if (response.ok || (response.status >= 300 && response.status < 400)) {
                window.Swal.fire({
                    icon: 'success',
                    title: 'Sub Requested!',
                    text: 'Substitute request has been created. Notifications are being sent to available substitutes.',
                    timer: 2000,
                    showConfirmButton: false
                }).then(() => window.location.reload());
            } else {
                throw new Error('Failed to request substitute');
            }
        } catch (error) {
            console.error('Error:', error);
            window.Swal.fire({
                icon: 'error',
                title: 'Error',
                text: error.message || 'Failed to request substitute'
            });
        }
    }

    /**
     * Handle match report form submission
     * @param {HTMLFormElement} form - The form element
     */
    async function handleMatchReportSubmit(form) {
        const matchId = form.dataset.matchId;
        const formData = new FormData(form);

        try {
            const response = await fetch(form.action, {
                method: 'POST',
                body: formData
            });

            const data = await response.json();

            if (data.success) {
                // Close modal
                const modal = window.bootstrap.Modal.getInstance(
                    document.getElementById(`reportMatchModal-${matchId}`)
                );
                if (modal) modal.hide();

                // Show success message and reload
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        icon: 'success',
                        title: 'Match Reported!',
                        timer: 2000,
                        showConfirmButton: false
                    }).then(() => window.location.reload());
                } else {
                    window.location.reload();
                }
            } else {
                throw new Error(data.message || 'Failed to report match');
            }
        } catch (error) {
            console.error('Error:', error);
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: error.message || 'Failed to report match'
                });
            } else {
                alert('Error: ' + error.message);
            }
        }
    }

    /**
     * Initialize event listeners using delegation
     * ROOT CAUSE FIX: All listeners use document-level delegation
     */
    let _initialized = false;
    export function init() {
        // Only initialize once
        if (_initialized) return;
        _initialized = true;

        // Request Sub button delegation
        document.addEventListener('click', function(e) {
            const btn = e.target.closest('[data-action="request-sub"]');
            if (btn) {
                e.preventDefault();
                const matchId = btn.dataset.matchId;
                const leagueType = btn.dataset.leagueType;
                const teamId = btn.dataset.teamId;
                requestSub(matchId, leagueType, teamId);
            }
        });

        // Match report form submission - using document-level delegation
        document.addEventListener('submit', function(e) {
            const form = e.target.closest('.report-match-form');
            if (form) {
                e.preventDefault();
                handleMatchReportSubmit(form);
            }
        });

        console.log('Coach Dashboard initialized');
    }

    // Expose API for external use
    window.CoachDashboard = {
        requestSub,
        getCsrfToken
    };

    // Register with InitSystem (primary)
    if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
        window.InitSystem.register('coach-dashboard', init, {
            priority: 40,
            reinitializable: false,
            description: 'Coach dashboard functionality'
        });
    }

    // Fallback
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

// Backward compatibility
window.getCsrfToken = getCsrfToken;

// Backward compatibility
window.init = init;
