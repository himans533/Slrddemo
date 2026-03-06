/**
 * Mobile Navigation System
 * Handles responsive sidebar, hamburger menu, and mobile interactions
 */

class MobileNav {
    constructor() {
        this.sidebar = document.querySelector('.sidebar');
        this.mainContent = document.querySelector('.main-content');
        this.topHeader = document.querySelector('.top-header');
        this.toggleBtn = null;
        this.isOpen = false;
        this.touchStartX = 0;
        this.touchEndX = 0;
        
        this.init();
    }

    init() {
        this.createToggleButton();
        this.attachEventListeners();
        this.handleResize();
        window.addEventListener('resize', () => this.handleResize());
    }

    /**
     * Create hamburger menu toggle button
     */
    createToggleButton() {
        // Check if button already exists
        if (document.querySelector('.sidebar-toggle')) {
            this.toggleBtn = document.querySelector('.sidebar-toggle');
            return;
        }

        this.toggleBtn = document.createElement('button');
        this.toggleBtn.className = 'sidebar-toggle show-mobile';
        this.toggleBtn.innerHTML = '<i class="fas fa-bars"></i>';
        this.toggleBtn.setAttribute('aria-label', 'Toggle Navigation Menu');
        this.toggleBtn.setAttribute('aria-expanded', 'false');

        // Insert at the beginning of top header
        if (this.topHeader) {
            this.topHeader.insertBefore(this.toggleBtn, this.topHeader.firstChild);
        }
    }

    /**
     * Attach all event listeners
     */
    attachEventListeners() {
        if (this.toggleBtn) {
            this.toggleBtn.addEventListener('click', () => this.toggleSidebar());
        }

        // Close sidebar when clicking outside on mobile
        document.addEventListener('click', (e) => {
            if (window.innerWidth <= 768) {
                if (this.sidebar && !this.sidebar.contains(e.target) && 
                    !e.target.closest('.sidebar-toggle')) {
                    this.closeSidebar();
                }
            }
        });

        // Close sidebar when clicking on a navigation link
        const navLinks = document.querySelectorAll('.sidebar-nav .nav-item');
        navLinks.forEach(link => {
            link.addEventListener('click', () => {
                if (window.innerWidth <= 768) {
                    this.closeSidebar();
                }
            });
        });

        // Swipe gesture support
        this.sidebar?.addEventListener('touchstart', (e) => {
            this.touchStartX = e.changedTouches[0].screenX;
        });

        this.sidebar?.addEventListener('touchend', (e) => {
            this.touchEndX = e.changedTouches[0].screenX;
            this.handleSwipe();
        });

        // Prevent body scroll when sidebar is open
        this.toggleBtn?.addEventListener('click', () => {
            document.body.style.overflow = this.isOpen ? 'auto' : 'hidden';
        });
    }

    /**
     * Toggle sidebar visibility
     */
    toggleSidebar() {
        if (this.isOpen) {
            this.closeSidebar();
        } else {
            this.openSidebar();
        }
    }

    /**
     * Open sidebar
     */
    openSidebar() {
        if (!this.sidebar) return;
        
        this.sidebar.classList.add('show');
        this.isOpen = true;
        this.toggleBtn?.setAttribute('aria-expanded', 'true');
        document.body.style.overflow = 'hidden';
        
        // Add backdrop overlay
        this.createBackdrop();
    }

    /**
     * Close sidebar
     */
    closeSidebar() {
        if (!this.sidebar) return;
        
        this.sidebar.classList.remove('show');
        this.isOpen = false;
        this.toggleBtn?.setAttribute('aria-expanded', 'false');
        document.body.style.overflow = 'auto';
        
        // Remove backdrop
        const backdrop = document.querySelector('.sidebar-backdrop');
        if (backdrop) backdrop.remove();
    }

    /**
     * Create background overlay for mobile
     */
    createBackdrop() {
        // Check if backdrop already exists
        if (document.querySelector('.sidebar-backdrop')) return;

        const backdrop = document.createElement('div');
        backdrop.className = 'sidebar-backdrop';
        backdrop.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.5);
            z-index: 999;
            display: none;
        `;

        document.body.appendChild(backdrop);

        // Show backdrop on mobile only
        if (window.innerWidth <= 768) {
            backdrop.style.display = 'block';
            backdrop.addEventListener('click', () => this.closeSidebar());
        }
    }

    /**
     * Handle swipe gesture to close sidebar
     */
    handleSwipe() {
        const swipeThreshold = 50;
        const diff = this.touchStartX - this.touchEndX;

        // Swiped left (close sidebar)
        if (diff > swipeThreshold && this.isOpen && window.innerWidth <= 768) {
            this.closeSidebar();
        }
    }

    /**
     * Handle window resize
     */
    handleResize() {
        const width = window.innerWidth;

        if (width > 768) {
            // Desktop view
            if (this.sidebar) {
                this.sidebar.classList.remove('show');
            }
            document.body.style.overflow = 'auto';
            
            if (this.toggleBtn) {
                this.toggleBtn.style.display = 'none';
            }
        } else {
            // Mobile view
            this.closeSidebar();
        }
    }

    /**
     * Get sidebar state
     */
    isOpen() {
        return this.sidebar?.classList.contains('show') || false;
    }
}

/**
 * Modal Responsive Handler
 */
class ResponsiveModal {
    static init() {
        const modals = document.querySelectorAll('[class*="modal"]');
        
        modals.forEach(modal => {
            // Ensure modals are full-width on mobile
            modal.addEventListener('shown.bs.modal', function() {
                if (window.innerWidth <= 768) {
                    this.style.maxWidth = '100%';
                    this.style.width = '100%';
                    this.style.margin = '0';
                }
            });
        });
    }
}

/**
 * Responsive Table Handler
 */
class ResponsiveTable {
    static init() {
        const tables = document.querySelectorAll('table');
        
        tables.forEach(table => {
            if (window.innerWidth <= 768) {
                // Wrap tables in responsive container
                if (!table.parentElement.classList.contains('table-responsive')) {
                    const wrapper = document.createElement('div');
                    wrapper.className = 'table-responsive';
                    table.parentNode.insertBefore(wrapper, table);
                    wrapper.appendChild(table);
                }
            }
        });
    }
}

/**
 * Form Responsive Handler
 */
class ResponsiveForm {
    static init() {
        const forms = document.querySelectorAll('form');
        
        forms.forEach(form => {
            // Ensure buttons are full-width on mobile
            const buttons = form.querySelectorAll('button, input[type="submit"]');
            if (window.innerWidth <= 768) {
                buttons.forEach(btn => {
                    btn.style.width = '100%';
                });
            }
        });
    }
}

/**
 * Responsive Image Handling
 */
class ResponsiveImage {
    static init() {
        const images = document.querySelectorAll('img[data-responsive]');
        
        images.forEach(img => {
            // Set max-width to 100% for responsive images
            img.style.maxWidth = '100%';
            img.style.height = 'auto';
            img.style.display = 'block';
        });
    }
}

/**
 * Initialize all responsive components
 */
document.addEventListener('DOMContentLoaded', function() {
    // Initialize mobile navigation
    window.mobileNav = new MobileNav();
    
    // Initialize responsive modals
    ResponsiveModal.init();
    
    // Initialize responsive tables
    ResponsiveTable.init();
    
    // Initialize responsive forms
    ResponsiveForm.init();
    
    // Initialize responsive images
    ResponsiveImage.init();
});

/**
 * Re-initialize on dynamic content load
 */
function reinitializeResponsive() {
    setTimeout(() => {
        ResponsiveModal.init();
        ResponsiveTable.init();
        ResponsiveForm.init();
        ResponsiveImage.init();
    }, 100);
}

/**
 * Utility: Get viewport width
 */
function getViewportWidth() {
    return window.innerWidth;
}

/**
 * Utility: Check if mobile
 */
function isMobile() {
    return window.innerWidth <= 768;
}

/**
 * Utility: Check if tablet
 */
function isTablet() {
    return window.innerWidth > 768 && window.innerWidth <= 1024;
}

/**
 * Utility: Check if desktop
 */
function isDesktop() {
    return window.innerWidth > 1024;
}

/**
 * Touch-friendly adjustments
 */
class TouchOptimization {
    static init() {
        // Increase touch targets
        const buttons = document.querySelectorAll('button, a, input[type="button"]');
        buttons.forEach(btn => {
            const computed = window.getComputedStyle(btn);
            const height = parseInt(computed.height);
            
            if (height < 44) {
                btn.style.minHeight = '44px';
                btn.style.padding = '10px 12px';
            }
        });

        // Remove hover effects on touch devices
        if ('ontouchstart' in window) {
            document.documentElement.classList.add('touch-device');
        }
    }
}

document.addEventListener('DOMContentLoaded', function() {
    TouchOptimization.init();
});
