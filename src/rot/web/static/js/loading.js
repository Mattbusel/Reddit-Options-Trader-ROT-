/**
 * Loading State Management
 *
 * Provides utilities for managing loading states:
 * - Show/hide spinners
 * - Skeleton loader injection
 * - HTMX integration
 * - Button loading states
 */

const Loading = {
    /**
     * Show loading spinner in element
     * @param {string|HTMLElement} target - Element or selector
     * @param {string} size - 'sm', 'md', 'lg'
     * @param {string} variant - 'primary', 'dark', 'light'
     */
    show(target, size = 'md', variant = 'primary') {
        const el = typeof target === 'string' ? document.querySelector(target) : target;
        if (!el) return;

        const sizeClass = size === 'lg' ? 'spinner-lg' : '';
        const variantClass = `spinner-${variant}`;

        const spinner = document.createElement('div');
        spinner.className = `spinner ${sizeClass} ${variantClass}`;
        spinner.setAttribute('data-loading-spinner', 'true');

        el.style.position = 'relative';
        el.appendChild(spinner);
    },

    /**
     * Hide loading spinner from element
     * @param {string|HTMLElement} target - Element or selector
     */
    hide(target) {
        const el = typeof target === 'string' ? document.querySelector(target) : target;
        if (!el) return;

        const spinners = el.querySelectorAll('[data-loading-spinner]');
        spinners.forEach(spinner => spinner.remove());
    },

    /**
     * Show loading overlay on element
     * @param {string|HTMLElement} target - Element or selector
     * @param {boolean} dark - Use dark overlay
     */
    showOverlay(target, dark = false) {
        const el = typeof target === 'string' ? document.querySelector(target) : target;
        if (!el) return;

        const overlay = document.createElement('div');
        overlay.className = dark ? 'loading-overlay loading-overlay-dark' : 'loading-overlay';
        overlay.setAttribute('data-loading-overlay', 'true');

        const spinner = document.createElement('div');
        spinner.className = 'spinner spinner-lg';
        overlay.appendChild(spinner);

        el.style.position = 'relative';
        el.appendChild(overlay);
    },

    /**
     * Hide loading overlay from element
     * @param {string|HTMLElement} target - Element or selector
     */
    hideOverlay(target) {
        const el = typeof target === 'string' ? document.querySelector(target) : target;
        if (!el) return;

        const overlays = el.querySelectorAll('[data-loading-overlay]');
        overlays.forEach(overlay => overlay.remove());
    },

    /**
     * Set button to loading state
     * @param {string|HTMLElement} button - Button element or selector
     * @param {string} loadingText - Optional loading text
     */
    buttonStart(button, loadingText = null) {
        const btn = typeof button === 'string' ? document.querySelector(button) : button;
        if (!btn) return;

        btn.disabled = true;
        btn.setAttribute('data-original-text', btn.innerHTML);
        btn.classList.add('loading');

        if (loadingText) {
            const spinner = document.createElement('span');
            spinner.className = 'spinner';
            btn.innerHTML = '';
            btn.appendChild(spinner);
            btn.appendChild(document.createTextNode(' ' + loadingText));
        }
    },

    /**
     * Remove loading state from button
     * @param {string|HTMLElement} button - Button element or selector
     */
    buttonEnd(button) {
        const btn = typeof button === 'string' ? document.querySelector(button) : button;
        if (!btn) return;

        btn.disabled = false;
        btn.classList.remove('loading');

        const originalText = btn.getAttribute('data-original-text');
        if (originalText) {
            btn.innerHTML = originalText;
            btn.removeAttribute('data-original-text');
        }
    },

    /**
     * Inject skeleton loaders into container
     * @param {string|HTMLElement} target - Container element or selector
     * @param {number} count - Number of skeleton cards to show
     * @param {string} type - 'signal' or 'card'
     */
    showSkeleton(target, count = 3, type = 'signal') {
        const el = typeof target === 'string' ? document.querySelector(target) : target;
        if (!el) return;

        el.innerHTML = '';

        for (let i = 0; i < count; i++) {
            if (type === 'signal') {
                el.appendChild(this._createSignalSkeleton());
            } else {
                el.appendChild(this._createCardSkeleton());
            }
        }
    },

    /**
     * Create signal card skeleton
     * @private
     */
    _createSignalSkeleton() {
        const card = document.createElement('div');
        card.className = 'skeleton-signal-card fade-in';
        card.innerHTML = `
            <div class="skeleton-signal-header">
                <div class="skeleton skeleton-ticker"></div>
                <div class="skeleton skeleton-badge"></div>
            </div>
            <div class="skeleton skeleton-confidence"></div>
            <div class="skeleton skeleton-reasoning"></div>
            <div class="skeleton skeleton-reasoning"></div>
            <div class="skeleton skeleton-reasoning"></div>
        `;
        return card;
    },

    /**
     * Create generic card skeleton
     * @private
     */
    _createCardSkeleton() {
        const card = document.createElement('div');
        card.className = 'skeleton-signal-card fade-in';
        card.innerHTML = `
            <div class="skeleton skeleton-title"></div>
            <div class="skeleton skeleton-text"></div>
            <div class="skeleton skeleton-text"></div>
            <div class="skeleton skeleton-text" style="width: 80%;"></div>
        `;
        return card;
    },

    /**
     * Show empty state message
     * @param {string|HTMLElement} target - Container element
     * @param {string} title - Empty state title
     * @param {string} description - Empty state description
     * @param {string} icon - Optional emoji icon
     */
    showEmpty(target, title, description, icon = '📭') {
        const el = typeof target === 'string' ? document.querySelector(target) : target;
        if (!el) return;

        el.innerHTML = `
            <div class="empty-state fade-in">
                <div class="empty-state-icon">${icon}</div>
                <div class="empty-state-title">${title}</div>
                <div class="empty-state-description">${description}</div>
            </div>
        `;
    }
};

// HTMX Integration
document.addEventListener('DOMContentLoaded', function() {
    // Show skeleton loaders on HTMX requests
    document.body.addEventListener('htmx:beforeRequest', function(evt) {
        const target = evt.detail.target;
        if (target && target.hasAttribute('data-loading-skeleton')) {
            const count = parseInt(target.getAttribute('data-loading-skeleton')) || 3;
            Loading.showSkeleton(target, count);
        }
    });

    // Handle HTMX loading indicators
    document.body.addEventListener('htmx:beforeRequest', function(evt) {
        const elt = evt.detail.elt;
        if (elt.hasAttribute('data-loading-disable')) {
            elt.disabled = true;
        }
    });

    document.body.addEventListener('htmx:afterRequest', function(evt) {
        const elt = evt.detail.elt;
        if (elt.hasAttribute('data-loading-disable')) {
            elt.disabled = false;
        }
    });

    // Add fade-in animation to dynamically loaded content
    document.body.addEventListener('htmx:afterSwap', function(evt) {
        const target = evt.detail.target;
        if (target) {
            target.querySelectorAll('[data-fade-in]').forEach(el => {
                el.classList.add('fade-in');
            });
        }
    });
});

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {
    module.exports = Loading;
}
