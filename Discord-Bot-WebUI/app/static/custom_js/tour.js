document.addEventListener('DOMContentLoaded', function () {
    const tourVar = new Shepherd.Tour({
        defaultStepOptions: {
            scrollTo: true,
            cancelIcon: {
                enabled: true
            }
        },
        useModalOverlay: true
    });

    tourVar.addStep({
        title: 'Welcome \uD83D\uDC4B',
        text: "Glad you're here ! This tour will guide you through the main features of the site.",
        attachTo: { element: '.navbar', on: 'bottom' },
        buttons: [
            {
                text: 'Next',
                action: tourVar.next
            },
            {
                text: 'Skip',
                action: function () {
                    // Get the CSRF token from the hidden input field
                    const csrfToken = document.querySelector('input[name="csrf_token"]').value;

                    // Send the fetch request with the CSRF token
                    fetch('/set_tour_complete', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': csrfToken  // Add the CSRF token here
                        },
                        body: JSON.stringify({}) // You can pass any data here if needed
                    })
                        .then(response => {
                            if (response.ok) {
                                tourVar.cancel();
                            } else {
                                console.error('Failed to complete the tour');
                            }
                        })
                        .catch(error => console.error('Error:', error));
                }
            }
        ]
    });

    tourVar.addStep({
        title: 'User Profile',
        text: 'Click here to view your profile, edit settings, or logout.',
        attachTo: { element: '.nav-item.dropdown-user', on: 'bottom' },
        buttons: [
            {
                text: 'Next',
                action: tourVar.next
            },
            {
                text: 'Skip',
                action: function () {
                    // Get the CSRF token from the hidden input field
                    const csrfToken = document.querySelector('input[name="csrf_token"]').value;

                    // Send the fetch request with the CSRF token
                    fetch('/set_tour_complete', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': csrfToken  // Add the CSRF token here
                        },
                        body: JSON.stringify({}) // You can pass any data here if needed
                    })
                        .then(response => {
                            if (response.ok) {
                                tourVar.cancel();
                            } else {
                                console.error('Failed to complete the tour');
                            }
                        })
                        .catch(error => console.error('Error:', error));
                }
            }
        ]
    });

    tourVar.addStep({
        title: 'Announcements! \uD83D\uDCE2',
        text: 'You can see new announcements here.',
        attachTo: { element: '#announcementsCarousel', on: 'top' },
        buttons: [
            {
                text: 'Next',
                action: tourVar.next
            },
            {
                text: 'Skip',
                action: function () {
                    // Get the CSRF token from the hidden input field
                    const csrfToken = document.querySelector('input[name="csrf_token"]').value;

                    // Send the fetch request with the CSRF token
                    fetch('/set_tour_complete', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': csrfToken  // Add the CSRF token here
                        },
                        body: JSON.stringify({}) // You can pass any data here if needed
                    })
                        .then(response => {
                            if (response.ok) {
                                tourVar.cancel();
                            } else {
                                console.error('Failed to complete the tour');
                            }
                        })
                        .catch(error => console.error('Error:', error));
                }
            }
        ]
    });

    tourVar.addStep({
        title: 'Profile',
        text: 'You can view and update your profile here.',
        attachTo: { element: '#playerProfile', on: 'top' },
        buttons: [
            {
                text: 'Next',
                action: tourVar.next
            },
            {
                text: 'Skip',
                action: function () {
                    // Get the CSRF token from the hidden input field
                    const csrfToken = document.querySelector('input[name="csrf_token"]').value;

                    // Send the fetch request with the CSRF token
                    fetch('/set_tour_complete', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': csrfToken  // Add the CSRF token here
                        },
                        body: JSON.stringify({}) // You can pass any data here if needed
                    })
                        .then(response => {
                            if (response.ok) {
                                tourVar.cancel();
                            } else {
                                console.error('Failed to complete the tour');
                            }
                        })
                        .catch(error => console.error('Error:', error));
                }
            }
        ]
    });

    tourVar.addStep({
        title: 'Team Page',
        text: 'You can find your teammates here.',
        attachTo: { element: '#teamOverview', on: 'top' },
        buttons: [
            {
                text: 'Next',
                action: tourVar.next
            },
            {
                text: 'Skip',
                action: function () {
                    // Get the CSRF token from the hidden input field
                    const csrfToken = document.querySelector('input[name="csrf_token"]').value;

                    // Send the fetch request with the CSRF token
                    fetch('/set_tour_complete', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': csrfToken  // Add the CSRF token here
                        },
                        body: JSON.stringify({}) // You can pass any data here if needed
                    })
                        .then(response => {
                            if (response.ok) {
                                tourVar.cancel();
                            } else {
                                console.error('Failed to complete the tour');
                            }
                        })
                        .catch(error => console.error('Error:', error));
                }
            }
        ]
    });

    tourVar.addStep({
        title: 'Matches',
        text: 'You can view and RSVP to your upcomming matches here.',
        attachTo: { element: '#matchOverview', on: 'top' },
        buttons: [
            {
                text: 'Next',
                action: tourVar.next
            },
            {
                text: 'Skip',
                action: function () {
                    // Get the CSRF token from the hidden input field
                    const csrfToken = document.querySelector('input[name="csrf_token"]').value;

                    // Send the fetch request with the CSRF token
                    fetch('/set_tour_complete', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': csrfToken  // Add the CSRF token here
                        },
                        body: JSON.stringify({}) // You can pass any data here if needed
                    })
                        .then(response => {
                            if (response.ok) {
                                tourVar.cancel();
                            } else {
                                console.error('Failed to complete the tour');
                            }
                        })
                        .catch(error => console.error('Error:', error));
                }
            }
        ]
    });

    tourVar.addStep({
        title: 'Teams',
        text: 'You can view other teams here.',
        attachTo: { element: 'a.teams-link', on: 'bottom' },
        buttons: [
            {
                text: 'Finish',
                action: function () {
                    // Get the CSRF token from the hidden input field
                    const csrfToken = document.querySelector('input[name="csrf_token"]').value;

                    // Send the fetch request with the CSRF token
                    fetch('/set_tour_complete', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': csrfToken  // Add the CSRF token here
                        },
                        body: JSON.stringify({}) // You can pass any data here if needed
                    })
                        .then(response => {
                            if (response.ok) {
                                tourVar.cancel();
                            } else {
                                console.error('Failed to complete the tour');
                            }
                        })
                        .catch(error => console.error('Error:', error));
                }
            }
        ]
    });

    // Start the tour immediately for testing
    if (showTour) {
        tourVar.start();
    }
});