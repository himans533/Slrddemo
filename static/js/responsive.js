/* ============================================
   MOBILE RESPONSIVE MENU HANDLER
   ============================================ */

/* Global function to close mobile menu */
function closeMobileMenu() {
    const sidebar = document.querySelector('.sidebar');
    const sidebarOverlay = document.querySelector('.sidebar-overlay');
    if (sidebar) sidebar.classList.remove('mobile-open');
    if (sidebarOverlay) sidebarOverlay.classList.remove('mobile-open');
}

document.addEventListener('DOMContentLoaded', function() {
    // Get elements
    const hamburgerToggle = document.querySelector('.hamburger-toggle');
    const sidebar = document.querySelector('.sidebar');
    const sidebarOverlay = document.querySelector('.sidebar-overlay');
    const navLinks = document.querySelectorAll('.sidebar-nav .nav-item, .sidebar-settings a, .nav-link');

    // Toggle sidebar on hamburger click
    if (hamburgerToggle) {
        hamburgerToggle.addEventListener('click', function() {
            sidebar.classList.toggle('mobile-open');
            sidebarOverlay.classList.toggle('mobile-open');
        });
    }

    // Close sidebar when overlay is clicked
    if (sidebarOverlay) {
        sidebarOverlay.addEventListener('click', function() {
            sidebar.classList.remove('mobile-open');
            sidebarOverlay.classList.remove('mobile-open');
        });
    }

    // Close sidebar when nav link is clicked (mobile only)
    navLinks.forEach(link => {
        link.addEventListener('click', function() {
            // Only close on mobile (when sidebar has transform)
            if (window.getComputedStyle(sidebar).transform !== 'none') {
                sidebar.classList.remove('mobile-open');
                sidebarOverlay.classList.remove('mobile-open');
            }
        });
    });

    // Close sidebar when window is resized past tablet breakpoint
    window.addEventListener('resize', function() {
        if (window.innerWidth >= 768) {
            sidebar.classList.remove('mobile-open');
            sidebarOverlay.classList.remove('mobile-open');
        }
    });

    // Mark active nav item based on current page
    const currentLocation = window.location.href;
    navLinks.forEach(link => {
        if (link.href === currentLocation) {
            link.classList.add('active');
        }
    });
});

/* ============================================
   THEME TOGGLE HANDLER
   ============================================ */

function initThemeToggle() {
    const themeToggle = document.querySelector('.theme-toggle');
    const html = document.documentElement;
    
    if (!themeToggle) return;

    // Get saved theme or default to light
    const savedTheme = localStorage.getItem('theme') || 'light';
    html.setAttribute('data-theme', savedTheme);

    themeToggle.addEventListener('click', function() {
        const currentTheme = html.getAttribute('data-theme');
        const newTheme = currentTheme === 'light' ? 'dark' : 'light';
        
        html.setAttribute('data-theme', newTheme);
        localStorage.setItem('theme', newTheme);
        
        // Update icon
        const icon = themeToggle.querySelector('i');
        if (icon) {
            icon.classList.toggle('fa-moon');
            icon.classList.toggle('fa-sun');
        }
    });

    // Set initial icon
    const icon = themeToggle.querySelector('i');
    if (icon) {
        if (savedTheme === 'dark') {
            icon.classList.add('fa-sun');
        } else {
            icon.classList.add('fa-moon');
        }
    }
}

document.addEventListener('DOMContentLoaded', initThemeToggle);

/* ============================================
   MODAL HANDLER
   ============================================ */

function openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('show');
        document.body.style.overflow = 'hidden';
    }
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('show');
        document.body.style.overflow = 'auto';
    }
}

// Close modal when overlay is clicked
document.addEventListener('click', function(event) {
    if (event.target.classList.contains('modal')) {
        event.target.classList.remove('show');
        document.body.style.overflow = 'auto';
    }
});

// Close modal on close button click
document.addEventListener('click', function(event) {
    if (event.target.classList.contains('modal-close')) {
        const modal = event.target.closest('.modal');
        if (modal) {
            modal.classList.remove('show');
            document.body.style.overflow = 'auto';
        }
    }
});

// Close modal on Escape key
document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
        const modals = document.querySelectorAll('.modal.show');
        modals.forEach(modal => {
            modal.classList.remove('show');
            document.body.style.overflow = 'auto';
        });
    }
});
