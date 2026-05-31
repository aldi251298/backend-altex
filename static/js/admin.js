/**
 * Altex Admin Panel JavaScript
 * Handles HTMX interactions, notifications, and UI enhancements
 */

// ============================================================================
// Initialization
// ============================================================================

document.addEventListener('DOMContentLoaded', function() {
    initializeApp();
});

function initializeApp() {
    // Initialize CSRF token for all HTMX requests
    initializeCSRF();
    
    // Initialize tooltips
    initializeTooltips();
    
    // Initialize confirmation dialogs
    initializeConfirmations();
    
    // Initialize form validation
    initializeFormValidation();
    
    console.log('Altex Admin Panel initialized');
}

// ============================================================================
// CSRF Protection
// ============================================================================

function initializeCSRF() {
    // Add CSRF token to all HTMX requests
    document.body.addEventListener('htmx:beforeRequest', function(evt) {
        const csrfToken = getCookie('csrf_token');
        if (csrfToken) {
            evt.detail.requestConfig.headers['X-CSRF-Token'] = csrfToken;
        }
    });
}

function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) {
        return parts.pop().split(';').shift();
    }
    return null;
}

// ============================================================================
// Toast Notifications
// ============================================================================

function showToast(message, type = 'success', duration = 5000) {
    const container = document.getElementById('toast-container');
    if (!container) return;
    
    const toast = document.createElement('div');
    toast.className = `${getToastBackgroundClass(type)} text-white px-4 py-3 rounded-lg shadow-lg flex items-center space-x-3 animate-slide-in max-w-sm`;
    
    toast.innerHTML = `
        ${getToastIcon(type)}
        <span class="flex-1">${escapeHtml(message)}</span>
        <button onclick="this.parentElement.remove()" class="text-white hover:text-gray-200 transition-colors">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
            </svg>
        </button>
    `;
    
    container.appendChild(toast);
    
    // Auto-remove after duration
    setTimeout(() => {
        if (toast.parentElement) {
            toast.classList.add('opacity-0', 'transition-opacity');
            setTimeout(() => toast.remove(), 300);
        }
    }, duration);
}

function getToastBackgroundClass(type) {
    const classes = {
        'success': 'bg-green-500',
        'error': 'bg-red-500',
        'warning': 'bg-yellow-500',
        'info': 'bg-blue-500'
    };
    return classes[type] || classes['info'];
}

function getToastIcon(type) {
    const icons = {
        'success': '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>',
        'error': '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>',
        'warning': '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>',
        'info': '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>'
    };
    return icons[type] || icons['info'];
}

// ============================================================================
// HTMX Event Handlers
// ============================================================================

// Handle successful responses
document.body.addEventListener('htmx:afterRequest', function(evt) {
    const detail = evt.detail;
    
    // Check for success indicator
    if (detail.successful && detail.xhr.status >= 200 && detail.xhr.status < 300) {
        // Check if response has a redirect
        const redirectHeader = detail.xhr.getResponseHeader('HX-Redirect');
        if (redirectHeader) {
            window.location.href = redirectHeader;
            return;
        }
        
        // Show success toast if response indicates success
        if (detail.target && detail.target.dataset.successMessage) {
            showToast(detail.target.dataset.successMessage, 'success');
        }
    }
});

// Handle errors
document.body.addEventListener('htmx:responseError', function(evt) {
    const detail = evt.detail;
    
    let message = 'An error occurred';
    
    try {
        const response = JSON.parse(detail.xhr.responseText);
        message = response.detail || response.message || message;
    } catch (e) {
        if (detail.xhr.status === 401) {
            message = 'Authentication required';
            window.location.href = '/admin/login';
            return;
        } else if (detail.xhr.status === 403) {
            message = 'Permission denied';
        } else if (detail.xhr.status === 404) {
            message = 'Resource not found';
        } else if (detail.xhr.status >= 500) {
            message = 'Server error occurred';
        }
    }
    
    showToast(message, 'error');
});

// Handle HTMX swaps that redirect
document.body.addEventListener('htmx:beforeSwap', function(evt) {
    if (evt.detail.xhr.status === 200) {
        const redirect = evt.detail.xhr.getResponseHeader('HX-Redirect');
        if (redirect) {
            window.location.href = redirect;
            evt.preventDefault();
        }
    }
});

// ============================================================================
// Loading Indicators
// ============================================================================

document.body.addEventListener('htmx:beforeRequest', function(evt) {
    const indicator = document.getElementById('loading-indicator');
    if (indicator) {
        indicator.style.transform = 'scaleX(0.3)';
        setTimeout(() => {
            indicator.style.transform = 'scaleX(0.6)';
        }, 100);
    }
});

document.body.addEventListener('htmx:afterRequest', function(evt) {
    const indicator = document.getElementById('loading-indicator');
    if (indicator) {
        indicator.style.transform = 'scaleX(1)';
        setTimeout(() => {
            indicator.style.transform = 'scaleX(0)';
        }, 200);
    }
});

// ============================================================================
// Tooltips
// ============================================================================

function initializeTooltips() {
    // Initialize all elements with title attribute as tooltips
    document.querySelectorAll('[title]').forEach(function(el) {
        el.addEventListener('mouseenter', showTooltip);
        el.addEventListener('mouseleave', hideTooltip);
    });
}

function showTooltip(evt) {
    const el = evt.target;
    const title = el.getAttribute('title');
    
    if (!title) return;
    
    // Hide native tooltip
    el.setAttribute('data-tooltip', title);
    el.removeAttribute('title');
    
    // Create tooltip element
    const tooltip = document.createElement('div');
    tooltip.id = 'custom-tooltip';
    tooltip.className = 'fixed z-50 px-2 py-1 text-xs text-white bg-gray-900 rounded shadow-lg dark:bg-gray-700';
    tooltip.textContent = title;
    
    document.body.appendChild(tooltip);
    
    // Position tooltip
    const rect = el.getBoundingClientRect();
    tooltip.style.top = `${rect.top - tooltip.offsetHeight - 5}px`;
    tooltip.style.left = `${rect.left + (rect.width - tooltip.offsetWidth) / 2}px`;
}

function hideTooltip(evt) {
    const el = evt.target;
    
    // Restore title attribute
    const title = el.getAttribute('data-tooltip');
    if (title) {
        el.setAttribute('title', title);
        el.removeAttribute('data-tooltip');
    }
    
    // Remove tooltip element
    const tooltip = document.getElementById('custom-tooltip');
    if (tooltip) {
        tooltip.remove();
    }
}

// ============================================================================
// Confirmation Dialogs
// ============================================================================

function initializeConfirmations() {
    // Note: HTMX has built-in hx-confirm attribute
    // This is for custom confirmations if needed
}

// Custom confirmation for delete actions
function confirmDelete(resourceName, callback) {
    const confirmed = confirm(`Are you sure you want to delete ${resourceName}? This action cannot be undone.`);
    if (confirmed && callback) {
        callback();
    }
    return confirmed;
}

// ============================================================================
// Form Validation
// ============================================================================

function initializeFormValidation() {
    // Add validation styles to forms
    document.querySelectorAll('form').forEach(function(form) {
        form.addEventListener('submit', function(evt) {
            if (!form.checkValidity()) {
                evt.preventDefault();
                highlightInvalidFields(form);
            }
        });
    });
}

function highlightInvalidFields(form) {
    const inputs = form.querySelectorAll('input, select, textarea');
    inputs.forEach(function(input) {
        if (!input.validity.valid) {
            input.classList.add('border-red-500', 'focus:ring-red-500');
            
            // Show validation message
            input.addEventListener('input', function() {
                if (input.validity.valid) {
                    input.classList.remove('border-red-500', 'focus:ring-red-500');
                }
            }, { once: true });
        }
    });
}

// ============================================================================
// Utility Functions
// ============================================================================

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

function throttle(func, limit) {
    let inThrottle;
    return function(...args) {
        if (!inThrottle) {
            func.apply(this, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

// Format file size
function formatSize(bytes) {
    const units = ['B', 'KB', 'MB', 'GB'];
    let size = bytes;
    let unitIndex = 0;
    
    while (size >= 1024 && unitIndex < units.length - 1) {
        size /= 1024;
        unitIndex++;
    }
    
    return `${size.toFixed(1)} ${units[unitIndex]}`;
}

// Format date
function formatDate(timestamp) {
    const date = new Date(timestamp / 1_000_000); // Convert ns to ms
    return date.toLocaleString();
}

// ============================================================================
// Dark Mode Toggle
// ============================================================================

function toggleDarkMode() {
    const html = document.documentElement;
    const isDark = html.classList.contains('dark');
    
    if (isDark) {
        html.classList.remove('dark');
        localStorage.setItem('theme', 'light');
    } else {
        html.classList.add('dark');
        localStorage.setItem('theme', 'dark');
    }
}

// Initialize dark mode from saved preference
function initializeDarkMode() {
    const savedTheme = localStorage.getItem('theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    
    if (savedTheme === 'dark' || (!savedTheme && prefersDark)) {
        document.documentElement.classList.add('dark');
    }
}

// ============================================================================
// Export functions for use in templates
// ============================================================================

window.AltexAdmin = {
    showToast,
    showTooltip,
    hideTooltip,
    confirmDelete,
    toggleDarkMode,
    formatSize,
    formatDate,
    debounce,
    throttle
};
