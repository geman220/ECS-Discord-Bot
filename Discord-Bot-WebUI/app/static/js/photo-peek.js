'use strict';

/**
 * Photo peek — hover (or tap) any element carrying data-peek-src to float a
 * large player photo next to it. Used by the Classic board and balanced draft
 * so "who is that?" is one hover away. Document-level delegation: works for
 * server-rendered and JS-rendered nodes alike.
 */

let peekEl = null;
let currentSrc = null;

function ensure() {
    if (peekEl) return peekEl;
    peekEl = document.createElement('div');
    peekEl.className = 'fixed z-[70] hidden pointer-events-none rounded-xl overflow-hidden shadow-2xl ring-2 ring-white dark:ring-gray-600 bg-gray-100 dark:bg-gray-800';
    peekEl.innerHTML = '<img class="w-44 h-44 object-cover" alt="">'
        + '<div class="peek-name px-2 py-1 text-xs font-semibold text-gray-900 dark:text-white bg-white/90 dark:bg-gray-800/90 truncate"></div>';
    document.body.appendChild(peekEl);
    const img = peekEl.querySelector('img');
    img.addEventListener('error', () => peekEl.classList.add('hidden'));
    return peekEl;
}

function show(target) {
    const src = target.dataset.peekSrc;
    if (!src) return;
    const el = ensure();
    const img = el.querySelector('img');
    if (currentSrc !== src) {
        img.src = src;
        currentSrc = src;
    }
    const nameEl = el.querySelector('.peek-name');
    const name = target.dataset.peekName || target.getAttribute('alt') || '';
    nameEl.textContent = name;
    nameEl.classList.toggle('hidden', !name);

    const rect = target.getBoundingClientRect();
    const size = 176 + 8;
    let x = rect.right + 10;
    if (x + size > window.innerWidth) x = rect.left - size - 10;
    if (x < 4) x = 4;
    let y = Math.max(4, Math.min(rect.top - 40, window.innerHeight - size - 30));
    el.style.left = `${x}px`;
    el.style.top = `${y}px`;
    el.classList.remove('hidden');
}

function hide() {
    peekEl?.classList.add('hidden');
}

document.addEventListener('mouseover', (event) => {
    const target = event.target.closest?.('[data-peek-src]');
    if (target) show(target);
});
document.addEventListener('mouseout', (event) => {
    if (event.target.closest?.('[data-peek-src]')) hide();
});
// Touch: tap toggles the peek (second tap elsewhere hides it).
document.addEventListener('touchstart', (event) => {
    const target = event.target.closest?.('[data-peek-src]');
    if (target) show(target); else hide();
}, { passive: true });
document.addEventListener('scroll', hide, true);
