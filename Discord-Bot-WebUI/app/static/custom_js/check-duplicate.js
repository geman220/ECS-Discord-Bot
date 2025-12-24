/**
 * Check Duplicate Accounts Handler
 * Manages duplicate account detection and claim/create actions
 */

document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('duplicate-check-form');
    const playerIdField = document.getElementById('player_id');
    const actionField = document.getElementById('action');

    // Handle claim account buttons
    document.querySelectorAll('.claim-account-btn').forEach(button => {
        button.addEventListener('click', function () {
            const playerId = this.getAttribute('data-player-id');
            const playerName = this.getAttribute('data-player-name');
            const playerEmail = this.getAttribute('data-player-email');

            // Show confirmation with SweetAlert
            Swal.fire({
                title: 'Claim This Account?',
                html: `
                    <p class="mb-2">You're claiming the account for:</p>
                    <div class="text-start border rounded p-3 bg-light">
                        <strong>${playerName}</strong><br>
                        <small class="text-muted">${playerEmail}</small>
                    </div>
                    <p class="mt-3 mb-0 small text-muted">
                        We'll send a verification email to <strong>${playerEmail}</strong> to confirm this is your account.
                    </p>
                `,
                icon: 'question',
                showCancelButton: true,
                confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('primary') : 'var(--ecs-primary)',
                cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('secondary') : '#6c757d',
                confirmButtonText: '<i class="ti ti-mail me-1"></i>Send Verification Email',
                cancelButtonText: 'Cancel',
                customClass: {
                    popup: 'text-start'
                }
            }).then((result) => {
                if (result.isConfirmed) {
                    // Set form values and submit
                    playerIdField.value = playerId;
                    actionField.value = 'claim';

                    // Show loading state
                    Swal.fire({
                        title: 'Sending Verification Email...',
                        text: 'Please wait while we process your request.',
                        icon: 'info',
                        allowOutsideClick: false,
                        showConfirmButton: false,
                        didOpen: () => {
                            Swal.showLoading();
                        }
                    });

                    form.submit();
                }
            });
        });
    });

    // Handle create new account button
    const createNewBtn = document.getElementById('create-new-btn');
    if (createNewBtn) {
        createNewBtn.addEventListener('click', function () {
            Swal.fire({
                title: 'Create New Account?',
                text: 'This will create a brand new profile for you. Are you sure none of the existing profiles are yours?',
                icon: 'question',
                showCancelButton: true,
                confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('success') : 'var(--ecs-success)',
                cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('secondary') : '#6c757d',
                confirmButtonText: '<i class="ti ti-user-plus me-1"></i>Yes, Create New Account',
                cancelButtonText: 'Let me check again'
            }).then((result) => {
                if (result.isConfirmed) {
                    // Set form values and submit
                    playerIdField.value = '';
                    actionField.value = 'new';

                    // Show loading state
                    Swal.fire({
                        title: 'Creating Your Account...',
                        text: 'Please wait while we set up your new profile.',
                        icon: 'info',
                        allowOutsideClick: false,
                        showConfirmButton: false,
                        didOpen: () => {
                            Swal.showLoading();
                        }
                    });

                    form.submit();
                }
            });
        });
    }

    // Add hover effects to duplicate cards
    document.querySelectorAll('.duplicate-option').forEach(card => {
        card.addEventListener('mouseenter', function () {
            this.classList.add('card-hover');
        });

        card.addEventListener('mouseleave', function () {
            this.classList.remove('card-hover');
        });
    });
});
