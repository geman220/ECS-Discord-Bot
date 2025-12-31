/**
 * Waitlist Registration (Authenticated) Page Handler
 * Manages profile modal and verification
 */
// ES Module
'use strict';

let _initialized = false;
    let isEditing = false;

    function init() {
        if (_initialized) return;
        _initialized = true;

        // Auto-focus on join button if not already on waitlist
        const joinButton = document.querySelector('button[type="submit"]');
        if (joinButton) {
            joinButton.focus();
        }

        // Event delegation for actions
        document.addEventListener('click', function(e) {
            const target = e.target.closest('[data-action]');
            if (!target) return;

            const action = target.dataset.action;

            switch(action) {
                case 'show-profile-modal':
                    showProfileModal();
                    break;
                case 'toggle-edit':
                    toggleEdit();
                    break;
                case 'verify-profile':
                    verifyProfile();
                    break;
            }
        });
    }

    // Show profile verification modal
    export function showProfileModal() {
        if (typeof window.ModalManager !== 'undefined') {
            window.ModalManager.show('profileModal');
        }
    }

    // Toggle edit mode
    export function toggleEdit() {
        isEditing = !isEditing;
        const editBtn = document.getElementById('editProfileBtn');
        const form = document.getElementById('profileForm');
        if (!form) return;

        const inputs = form.querySelectorAll('input:not([readonly]), select, textarea');

        if (isEditing) {
            // Enable editing
            inputs.forEach(input => {
                if (input.id !== 'name' && input.id !== 'email') { // Keep name and email readonly
                    input.removeAttribute('readonly');
                    input.removeAttribute('disabled');
                }
            });
            if (editBtn) {
                editBtn.innerHTML = '<i class="ti ti-x me-1"></i>Cancel Edit';
                editBtn.className = 'btn btn-secondary';
            }
        } else {
            // Disable editing
            inputs.forEach(input => {
                if (input.tagName === 'SELECT') {
                    input.setAttribute('disabled', 'disabled');
                } else {
                    input.setAttribute('readonly', 'readonly');
                }
            });
            if (editBtn) {
                editBtn.innerHTML = '<i class="ti ti-edit me-1"></i>Edit Profile';
                editBtn.className = 'btn btn-warning';
            }
        }
    }

    // Verify profile function (now also saves if edited)
    export function verifyProfile() {
        const playerData = window.playerData || {};

        if (!playerData.id) {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    title: 'No Player Profile',
                    text: 'No player profile found. Please contact an administrator.',
                    icon: 'error'
                });
            }
            return;
        }

        let profileData = {};

        // If in edit mode, collect form data
        if (isEditing) {
            const form = document.getElementById('profileForm');
            if (form) {
                const formData = new FormData(form);

                // Convert FormData to object
                for (let [key, value] of formData.entries()) {
                    profileData[key] = value;
                }
            }
        }

        if (typeof window.Swal === 'undefined') return;

        window.Swal.fire({
            title: isEditing ? 'Save & Verify Profile' : 'Verify Profile Information',
            html: `<div class="text-start">
                   <p class="mb-2">Please confirm that your profile information is current and accurate.</p>
                   <p class="mb-2">This includes:</p>
                   <ul class="mb-3">
                       <li>Contact information (email, phone)</li>
                       <li>Player details (jersey size, positions, availability)</li>
                       <li>Personal information (pronouns, notes)</li>
                   </ul>
                   <p class="fw-bold mb-0">By confirming, you ${isEditing ? 'save your changes and' : ''} verify that all information is up to date.</p>
                   </div>`,
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: isEditing ? 'Save & Verify' : 'Yes, my profile is accurate',
            cancelButtonText: 'Cancel',
            confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('success') : '#28a745',
            showLoaderOnConfirm: true,
            preConfirm: () => {
                const url = isEditing ? playerData.updateUrl : playerData.verifyUrl;
                const headers = {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': playerData.csrfToken
                };
                const body = isEditing ? JSON.stringify(profileData) : JSON.stringify({});

                return fetch(url, {
                    method: 'POST',
                    headers: headers,
                    body: body
                })
                .then(response => {
                    if (!response.ok) {
                        throw new Error('Network response was not ok');
                    }
                    return response.json();
                })
                .then(data => {
                    if (data.success) {
                        return data;
                    } else {
                        throw new Error(data.message || 'Operation failed');
                    }
                })
                .catch(error => {
                    window.Swal.showValidationMessage('Error: ' + error.message);
                });
            }
        }).then((result) => {
            if (result.isConfirmed) {
                // Hide the profile modal
                const modalEl = document.getElementById('profileModal');
                if (modalEl && typeof window.bootstrap !== 'undefined') {
                    const modal = window.bootstrap.Modal.getInstance(modalEl);
                    if (modal) {
                        modal.hide();
                    }
                }

                // Show success message
                window.Swal.fire({
                    title: isEditing ? 'Profile Updated & Verified!' : 'Profile Verified!',
                    text: isEditing ? 'Your profile has been updated and verified successfully.' : 'Thank you for confirming your profile information is current.',
                    icon: 'success',
                    confirmButtonText: 'Continue to Waitlist'
                }).then(() => {
                    // Refresh the page to update the profile status
                    window.location.reload();
                });
            }
        });
    }

    // Register with InitSystem (primary)
    if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
        window.InitSystem.register('waitlist-register-authenticated', init, {
            priority: 20,
            reinitializable: false,
            description: 'Waitlist registration for authenticated users'
        });
    }

    // Fallback
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

// Backward compatibility
window.showProfileModal = showProfileModal;

// Backward compatibility
window.toggleEdit = toggleEdit;

// Backward compatibility
window.verifyProfile = verifyProfile;
