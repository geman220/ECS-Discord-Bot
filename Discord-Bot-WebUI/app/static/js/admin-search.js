/**
 * Admin Panel Universal Search
 *
 * Provides real-time search across all admin panel features, settings, and pages.
 * Uses a server-generated JSON index embedded in the page.
 */

import { escapeHtml } from './utils/safe-html.js';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let searchIndex = [];
let normalizedIndex = [];
let activeIndex = -1;
let isOpen = false;
let debounceTimer = null;
const DEBOUNCE_MS = 200;
const MIN_QUERY_LENGTH = 2;
const MAX_RESULTS = 15;

// DOM references (set during init)
let desktopInput = null;
let desktopResults = null;
let desktopClearBtn = null;
let mobileInput = null;
let mobileResults = null;
let mobileClearBtn = null;
let mobileContainer = null;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getActiveInput() {
    if (mobileContainer && !mobileContainer.classList.contains('hidden')) {
        return mobileInput;
    }
    return desktopInput;
}

function getActiveResults() {
    if (mobileContainer && !mobileContainer.classList.contains('hidden')) {
        return mobileResults;
    }
    return desktopResults;
}

function getActiveClearBtn() {
    if (mobileContainer && !mobileContainer.classList.contains('hidden')) {
        return mobileClearBtn;
    }
    return desktopClearBtn;
}

function highlightMatch(text, query) {
    if (!query) return escapeHtml(text);
    const escaped = escapeHtml(text);
    const lowerEscaped = escaped.toLowerCase();
    const lowerQuery = query.toLowerCase();
    const idx = lowerEscaped.indexOf(lowerQuery);
    if (idx === -1) return escaped;
    const before = escaped.slice(0, idx);
    const match = escaped.slice(idx, idx + lowerQuery.length);
    const after = escaped.slice(idx + lowerQuery.length);
    return `${before}<mark class="bg-ecs-green/20 text-inherit rounded px-0.5">${match}</mark>${after}`;
}

// ---------------------------------------------------------------------------
// Search & Scoring
// ---------------------------------------------------------------------------

function scoreItem(item, queryTokens, fullQuery) {
    let score = 0;
    const lowerQuery = fullQuery.toLowerCase();

    // Exact name match
    if (item._name === lowerQuery) {
        score += 100;
    } else if (item._name.startsWith(lowerQuery)) {
        score += 80;
    } else if (item._name.includes(lowerQuery)) {
        score += 60;
    }

    // Keyword matches
    for (const token of queryTokens) {
        for (const kw of item._keywords) {
            if (kw === token) {
                score += 40;
            } else if (kw.includes(token)) {
                score += 25;
            }
        }
    }

    // Description match
    if (item._description && item._description.includes(lowerQuery)) {
        score += 20;
    }

    // Category match
    if (item._category.includes(lowerQuery)) {
        score += 10;
    }

    // Subcategory match
    if (item._subcategory && item._subcategory.includes(lowerQuery)) {
        score += 15;
    }

    return score;
}

function search(query) {
    const input = getActiveInput();
    const clearBtn = getActiveClearBtn();

    if (clearBtn) {
        clearBtn.classList.toggle('hidden', !query);
    }

    if (!query || query.length < MIN_QUERY_LENGTH) {
        closeResults();
        return;
    }

    const lowerQuery = query.toLowerCase().trim();
    const queryTokens = lowerQuery.split(/\s+/).filter(t => t.length > 0);

    const scored = normalizedIndex
        .map(item => ({ item, score: scoreItem(item, queryTokens, lowerQuery) }))
        .filter(s => s.score > 0)
        .sort((a, b) => b.score - a.score)
        .slice(0, MAX_RESULTS);

    renderResults(scored.map(s => s.item), query);
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function renderResults(items, query) {
    const resultsEl = getActiveResults();
    const input = getActiveInput();
    if (!resultsEl) return;

    if (items.length === 0) {
        resultsEl.innerHTML = `
            <div class="px-4 py-6 text-center text-gray-500 dark:text-gray-400">
                <i class="ti ti-search-off text-2xl mb-2 block"></i>
                <p class="text-sm">No matching features found</p>
            </div>`;
        showResults();
        return;
    }

    // Group by category
    const groups = new Map();
    items.forEach((item, i) => {
        const cat = item.category;
        if (!groups.has(cat)) groups.set(cat, []);
        groups.get(cat).push({ ...item, _resultIndex: i });
    });

    let html = '';
    let resultIndex = 0;

    for (const [category, groupItems] of groups) {
        html += `<div class="px-3 py-1.5 text-xs font-semibold text-gray-400 uppercase tracking-wider">${escapeHtml(category)}</div>`;
        for (const item of groupItems) {
            const highlightedName = highlightMatch(item.name, query);
            const desc = item.description ? `<span class="text-xs text-gray-400 dark:text-gray-500 truncate">${escapeHtml(item.description)}</span>` : '';
            html += `
                <a href="${escapeHtml(item.url)}"
                   role="option"
                   id="admin-search-result-${resultIndex}"
                   class="admin-search-result flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                   data-action="admin-search-navigate"
                   data-url="${escapeHtml(item.url)}">
                    <i class="ti ${escapeHtml(item.icon)} text-gray-400 flex-shrink-0"></i>
                    <div class="flex flex-col min-w-0 flex-1">
                        <span class="text-sm text-gray-700 dark:text-gray-200 truncate">${highlightedName}</span>
                        ${desc}
                    </div>
                    ${item.subcategory ? `<span class="text-[10px] text-gray-400 dark:text-gray-500 whitespace-nowrap hidden sm:inline">${escapeHtml(item.subcategory)}</span>` : ''}
                </a>`;
            resultIndex++;
        }
    }

    resultsEl.innerHTML = html;
    activeIndex = -1;
    showResults();
}

// ---------------------------------------------------------------------------
// Results Visibility
// ---------------------------------------------------------------------------

function showResults() {
    const resultsEl = getActiveResults();
    const input = getActiveInput();
    if (!resultsEl) return;
    resultsEl.classList.remove('hidden');
    isOpen = true;
    if (input) input.setAttribute('aria-expanded', 'true');
}

function closeResults() {
    // Close both desktop and mobile results
    [desktopResults, mobileResults].forEach(el => {
        if (el) el.classList.add('hidden');
    });
    [desktopInput, mobileInput].forEach(el => {
        if (el) {
            el.setAttribute('aria-expanded', 'false');
            el.setAttribute('aria-activedescendant', '');
        }
    });
    activeIndex = -1;
    isOpen = false;
}

// ---------------------------------------------------------------------------
// Keyboard Navigation
// ---------------------------------------------------------------------------

function handleKeyboard(element, event) {
    if (!isOpen) {
        if (event.key === 'ArrowDown' || event.key === 'Enter') {
            const val = element.value;
            if (val && val.length >= MIN_QUERY_LENGTH) {
                search(val);
            }
        }
        return;
    }

    const resultsEl = getActiveResults();
    if (!resultsEl) return;

    const items = resultsEl.querySelectorAll('.admin-search-result');
    if (items.length === 0) return;

    switch (event.key) {
        case 'ArrowDown':
            event.preventDefault();
            activeIndex = (activeIndex + 1) % items.length;
            updateActiveHighlight(items);
            break;
        case 'ArrowUp':
            event.preventDefault();
            activeIndex = activeIndex <= 0 ? items.length - 1 : activeIndex - 1;
            updateActiveHighlight(items);
            break;
        case 'Enter':
            event.preventDefault();
            if (activeIndex >= 0 && activeIndex < items.length) {
                const url = items[activeIndex].getAttribute('data-url');
                if (url) window.location.href = url;
            }
            break;
        case 'Escape':
            event.preventDefault();
            closeResults();
            element.blur();
            break;
    }
}

function updateActiveHighlight(items) {
    const input = getActiveInput();
    items.forEach((el, i) => {
        if (i === activeIndex) {
            el.classList.add('bg-gray-100', 'dark:bg-gray-700');
            el.scrollIntoView({ block: 'nearest' });
            if (input) input.setAttribute('aria-activedescendant', el.id);
        } else {
            el.classList.remove('bg-gray-100', 'dark:bg-gray-700');
        }
    });
}

// ---------------------------------------------------------------------------
// Mobile Toggle
// ---------------------------------------------------------------------------

function toggleMobile() {
    if (!mobileContainer) return;
    const isHidden = mobileContainer.classList.contains('hidden');
    mobileContainer.classList.toggle('hidden', !isHidden);
    if (isHidden && mobileInput) {
        mobileInput.focus();
    } else {
        closeResults();
        if (mobileInput) mobileInput.value = '';
        if (mobileClearBtn) mobileClearBtn.classList.add('hidden');
    }
}

// ---------------------------------------------------------------------------
// Clear
// ---------------------------------------------------------------------------

function clearSearch(element) {
    // Determine which input to clear based on which clear button was clicked
    const isMobile = element && element.id === 'admin-search-clear-btn-mobile';
    const input = isMobile ? mobileInput : desktopInput;
    if (input) {
        input.value = '';
        input.focus();
    }
    const clearBtn = isMobile ? mobileClearBtn : desktopClearBtn;
    if (clearBtn) clearBtn.classList.add('hidden');
    closeResults();
}

// ---------------------------------------------------------------------------
// EventDelegation Registration
// ---------------------------------------------------------------------------

if (window.EventDelegation) {
    window.EventDelegation.register('admin-search-filter', (element, event) => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            search(element.value);
        }, DEBOUNCE_MS);
    });

    window.EventDelegation.register('admin-search-keyboard', (element, event) => {
        handleKeyboard(element, event);
    });

    window.EventDelegation.register('admin-search-navigate', (element, event) => {
        // Let the browser handle the <a> href naturally
    });

    window.EventDelegation.register('admin-search-clear', (element, event) => {
        clearSearch(element);
    });

    window.EventDelegation.register('admin-search-toggle-mobile', () => {
        toggleMobile();
    });
}

// ---------------------------------------------------------------------------
// Initialization
// ---------------------------------------------------------------------------

function initAdminSearch() {
    // Load search index from JSON blob
    const indexEl = document.getElementById('admin-search-index');
    if (!indexEl) return;

    try {
        searchIndex = JSON.parse(indexEl.textContent);
    } catch (e) {
        return;
    }

    if (!Array.isArray(searchIndex) || searchIndex.length === 0) return;

    // Pre-compute normalized fields for fast matching
    normalizedIndex = searchIndex.map(item => ({
        ...item,
        _name: (item.name || '').toLowerCase(),
        _category: (item.category || '').toLowerCase(),
        _subcategory: (item.subcategory || '').toLowerCase(),
        _description: (item.description || '').toLowerCase(),
        _keywords: (item.keywords || []).map(k => k.toLowerCase()),
    }));

    // Cache DOM references
    desktopInput = document.getElementById('admin-search-input');
    desktopResults = document.getElementById('admin-search-results');
    desktopClearBtn = document.getElementById('admin-search-clear-btn');
    mobileInput = document.getElementById('admin-search-input-mobile');
    mobileResults = document.getElementById('admin-search-results-mobile');
    mobileClearBtn = document.getElementById('admin-search-clear-btn-mobile');
    mobileContainer = document.getElementById('admin-search-mobile-container');

    // Update Ctrl/Cmd key hint for macOS
    if (navigator.platform && navigator.platform.indexOf('Mac') > -1) {
        const modKeys = document.querySelectorAll('.admin-search-mod-key');
        modKeys.forEach(el => { el.textContent = '\u2318'; });
    }

    // Close results on outside click
    document.addEventListener('click', (e) => {
        const container = document.getElementById('admin-search-container');
        if (
            container && !container.contains(e.target) &&
            mobileContainer && !mobileContainer.contains(e.target) &&
            !e.target.closest('[data-action="admin-search-toggle-mobile"]')
        ) {
            closeResults();
        }
    });

    // Global Ctrl+K / Cmd+K shortcut
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            // On mobile, toggle the mobile search
            if (window.innerWidth < 768 && mobileContainer) {
                if (mobileContainer.classList.contains('hidden')) {
                    toggleMobile();
                } else if (mobileInput) {
                    mobileInput.focus();
                    mobileInput.select();
                }
            } else if (desktopInput) {
                desktopInput.focus();
                desktopInput.select();
            }
        }
    });

    // Re-show results on focus if input has value
    [desktopInput, mobileInput].forEach(input => {
        if (input) {
            input.addEventListener('focus', () => {
                if (input.value && input.value.length >= MIN_QUERY_LENGTH) {
                    search(input.value);
                }
            });
        }
    });
}

// Register with InitSystem
if (window.InitSystem) {
    window.InitSystem.register('admin-search', initAdminSearch, {
        priority: 65,
        reinitializable: true,
        description: 'Universal admin panel search'
    });
}
