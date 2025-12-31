/**
 * Tour - Shepherd.js guided tour for new users
 * Initializes and runs the onboarding tour
 */
// ES Module
'use strict';

let _initialized = false;

  export function init() {
    if (_initialized) return;

    // Guard: Check if Shepherd is loaded before using it
    if (typeof window.Shepherd === 'undefined') {
      console.warn('[Tour] Shepherd library not loaded, skipping tour initialization');
      return;
    }

    _initialized = true;

    const tourVar = new window.Shepherd.Tour({
      defaultStepOptions: {
        scrollTo: true,
        cancelIcon: {
          enabled: true
        }
      },
      useModalOverlay: true
    });

    // Helper function to create skip action
    export function createSkipAction() {
      return function() {
        const csrfToken = document.querySelector('input[name="csrf_token"]')?.value ||
                          document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

        if (!csrfToken) {
          tourVar.cancel();
          return;
        }

        fetch('/set_tour_complete', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
          },
          body: JSON.stringify({})
        })
        .then(response => {
          if (response.ok) {
            tourVar.cancel();
          }
        })
        .catch(() => {
          tourVar.cancel();
        });
      };
    }

    tourVar.addStep({
      title: 'Welcome 👋',
      text: "Glad you're here! This tour will guide you through the main features of the site.",
      attachTo: { element: '.navbar', on: 'bottom' },
      buttons: [
        { text: 'Next', action: tourVar.next },
        { text: 'Skip', action: createSkipAction() }
      ]
    });

    tourVar.addStep({
      title: 'User Profile',
      text: 'Click here to view your profile, edit settings, or logout.',
      attachTo: { element: '.nav-item.dropdown-user', on: 'bottom' },
      buttons: [
        { text: 'Next', action: tourVar.next },
        { text: 'Skip', action: createSkipAction() }
      ]
    });

    tourVar.addStep({
      title: 'Announcements! 📢',
      text: 'You can see new announcements here.',
      attachTo: { element: '#announcementsCarousel', on: 'top' },
      buttons: [
        { text: 'Next', action: tourVar.next },
        { text: 'Skip', action: createSkipAction() }
      ]
    });

    tourVar.addStep({
      title: 'Profile',
      text: 'You can view and update your profile here.',
      attachTo: { element: '#playerProfile', on: 'top' },
      buttons: [
        { text: 'Next', action: tourVar.next },
        { text: 'Skip', action: createSkipAction() }
      ]
    });

    tourVar.addStep({
      title: 'Team Page',
      text: 'You can find your teammates here.',
      attachTo: { element: '#teamOverview', on: 'top' },
      buttons: [
        { text: 'Next', action: tourVar.next },
        { text: 'Skip', action: createSkipAction() }
      ]
    });

    tourVar.addStep({
      title: 'Matches',
      text: 'You can view and RSVP to your upcoming matches here.',
      attachTo: { element: '#matchOverview', on: 'top' },
      buttons: [
        { text: 'Next', action: tourVar.next },
        { text: 'Skip', action: createSkipAction() }
      ]
    });

    tourVar.addStep({
      title: 'Feedback',
      text: 'You can report bugs or give feedback here. We need your feedback to get better!',
      attachTo: { element: 'a.feedback-link', on: 'top' },
      buttons: [
        { text: 'Next', action: tourVar.next },
        { text: 'Skip', action: createSkipAction() }
      ]
    });

    tourVar.addStep({
      title: 'Teams',
      text: 'You can view other teams here.',
      attachTo: { element: 'a.teams-link', on: 'bottom' },
      buttons: [
        { text: 'Finish', action: createSkipAction() }
      ]
    });

    // Start the tour if showTour is defined and truthy (set by template)
    if (typeof showTour !== 'undefined' && showTour) {
      tourVar.start();
    }
  }

  // Register with InitSystem (primary)
  if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
    window.InitSystem.register('tour', init, {
      priority: 25,
      reinitializable: false,
      description: 'Shepherd.js onboarding tour'
    });
  }

  // Fallback
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

// Backward compatibility
window.init = init;

// Backward compatibility
window.createSkipAction = createSkipAction;
