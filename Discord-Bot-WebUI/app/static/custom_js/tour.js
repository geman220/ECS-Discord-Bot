/**
 * Tour - Shepherd.js guided tour for new users
 * Initializes and runs the onboarding tour
 */
'use strict';

import { InitSystem } from '../js/init-system.js';

let _initialized = false;

// Helper function to create skip action
export function createSkipAction(tourVar) {
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
            if (!response.ok) {
                console.warn('[Tour] set_tour_complete returned', response.status);
            }
            tourVar.cancel();
        })
        .catch(() => {
            tourVar.cancel();
        });
    };
}

export function initTour() {
    if (_initialized) return;

    // Guard: Check if Shepherd is loaded before using it
    if (typeof window.Shepherd === 'undefined') {
        console.warn('[Tour] Shepherd library not loaded, skipping tour initialization');
        return;
    }

    _initialized = true;

    const tourVar = new window.Shepherd.Tour({
        defaultStepOptions: {
            scrollTo: { behavior: 'smooth', block: 'center' },
            cancelIcon: {
                enabled: true
            }
        },
        useModalOverlay: true
    });

    // Candidate steps for the modern dashboard. `element: null` => a centered
    // intro card (no anchor). Every other step is anchored to a real element via
    // a stable `data-tour` hook (or an existing id). Steps whose target is not on
    // the current page are skipped, so the tour never attaches to a missing
    // element and floats scrambled in the middle of the screen.
    const candidateSteps = [
        { title: 'Welcome', text: "Glad you're here! Here's a quick tour of your dashboard.", element: null },
        { title: 'Your Teams', text: 'Your current teams show up here.', element: '[data-tour="teams"]', on: 'bottom' },
        { title: 'Your Next Match', text: "Your next match — RSVP right here so your coach knows you're coming.", element: '[data-tour="next-match"]', on: 'bottom' },
        { title: 'Announcements', text: 'League announcements show up here.', element: '#announcementsCarousel', on: 'bottom' },
        { title: 'Upcoming Matches', text: 'All your upcoming matches, with RSVP and details.', element: '[data-tour="matches"]', on: 'top' }
    ];

    const steps = candidateSteps.filter(s => s.element === null || document.querySelector(s.element));

    steps.forEach((s, idx) => {
        const isLast = idx === steps.length - 1;
        const step = {
            title: s.title,
            text: s.text,
            buttons: isLast
                ? [{ text: 'Finish', action: createSkipAction(tourVar) }]
                : [
                    { text: 'Skip', action: createSkipAction(tourVar), secondary: true },
                    { text: 'Next', action: tourVar.next }
                  ]
        };
        if (s.element) {
            step.attachTo = { element: s.element, on: s.on || 'bottom' };
        }
        tourVar.addStep(step);
    });

    // Start the tour if showTour is defined and truthy (set by template)
    if (typeof showTour !== 'undefined' && showTour) {
        tourVar.start();
    }
}

// Register with window.InitSystem (primary)
if (window.InitSystem.register) {
    window.InitSystem.register('tour', initTour, {
        priority: 25,
        reinitializable: false,
        description: 'Shepherd.js onboarding tour'
    });
}

// Fallback
// window.InitSystem handles initialization

// Backward compatibility
window.initTour = initTour;
window.createSkipAction = createSkipAction;
