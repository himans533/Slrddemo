# Mobile Responsive Code Examples

Quick reference for implementing responsive features in your code.

## Table of Contents
1. [JavaScript Examples](#javascript-examples)
2. [CSS Examples](#css-examples)
3. [HTML Examples](#html-examples)
4. [Common Patterns](#common-patterns)
5. [Advanced Usage](#advanced-usage)

## JavaScript Examples

### Detecting Device Type

#### Check if Mobile
```javascript
if (isMobileView()) {
    console.log('User is on mobile device');
    // Mobile-specific code here
}
```

#### Check if Tablet
```javascript
if (isTabletView()) {
    console.log('User is on tablet');
    // Tablet-specific code here
}
```

#### Check if Desktop
```javascript
if (isDesktopView()) {
    console.log('User is on desktop');
    // Desktop-specific code here
}
```

#### Get Current Breakpoint
```javascript
const breakpoint = getCurrentBreakpoint();
// Returns: 'xs' (0-480px), 'md' (481-768px), 'lg' (769-1024px), 'xl' (1025px+)

if (breakpoint === 'xs') {
    // Extra small phone
} else if (breakpoint === 'md') {
    // Small phone or tablet
} else if (breakpoint === 'lg') {
    // Tablet
} else {
    // Desktop
}
```

### Mobile Navigation

#### Toggle Mobile Sidebar
```javascript
// Toggle sidebar when menu button clicked
document.getElementById('menuBtn').addEventListener('click', () => {
    toggleMobileSidebar('sidebar');
});
```

#### Initialize Mobile Menu on Page Load
```javascript
document.addEventListener('DOMContentLoaded', () => {
    // Set up mobile menu button
    initMobileMenuButton('mobileMenuBtn', 'sidebar');
    
    // Initialize all responsive features
    initResponsiveBehavior();
});
```

#### Close Sidebar on Navigation
```javascript
document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
        if (isMobileView()) {
            closeMobileSidebar('sidebar');
        }
    });
});
```

### Device Detection

#### Check if Touch Device
```javascript
if (isTouchDevice()) {
    console.log('Device supports touch');
    // Add touch-specific event listeners
    document.addEventListener('touchstart', handleTouch);
} else {
    console.log('Device does not support touch');
    // Use mouse events instead
    document.addEventListener('mousedown', handleMouse);
}
```

#### Get Safe Area Insets (Notch Devices)
```javascript
const safeArea = getSafeAreaInsets();
console.log('Safe area top:', safeArea.top);
console.log('Safe area bottom:', safeArea.bottom);
console.log('Safe area left:', safeArea.left);
console.log('Safe area right:', safeArea.right);

// Use in CSS
document.documentElement.style.setProperty('--safe-top', `${safeArea.top}px`);
document.documentElement.style.setProperty('--safe-bottom', `${safeArea.bottom}px`);
```

### Scroll Control

#### Prevent Body Scroll (for Modals)
```javascript
// When opening modal
preventBodyScroll();

// When closing modal
allowBodyScroll();
```

### Table Responsiveness

#### Convert Table to Responsive Layout
```javascript
// On page load
document.addEventListener('DOMContentLoaded', () => {
    makeTableResponsive('taskTable');
});

// Or on demand
document.getElementById('makeResponsiveBtn').addEventListener('click', () => {
    makeTableResponsive('taskTable');
});
```

### Complete Mobile Menu Implementation

```javascript
document.addEventListener('DOMContentLoaded', () => {
    const menuBtn = document.getElementById('mobileMenuBtn');
    const sidebar = document.getElementById('sidebar');
    
    // Toggle menu
    menuBtn.addEventListener('click', () => {
        toggleMobileSidebar('sidebar');
    });
    
    // Close on item click
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', () => {
            if (isMobileView()) {
                closeMobileSidebar('sidebar');
            }
        });
    });
    
    // Close on window resize to desktop
    window.addEventListener('resize', () => {
        if (isDesktopView()) {
            closeMobileSidebar('sidebar');
        }
    });
    
    // Initialize responsive behavior
    initResponsiveBehavior();
});
```

## CSS Examples

### Basic Media Queries

#### Mobile First (Recommended)
```css
/* Default: Mobile styles */
.container {
    padding: 12px;
    display: grid;
    grid-template-columns: 1fr;
}

/* Tablet and above */
@media (min-width: 769px) {
    .container {
        padding: 20px;
        grid-template-columns: 1fr 1fr;
    }
}

/* Desktop */
@media (min-width: 1025px) {
    .container {
        padding: 24px;
        grid-template-columns: 1fr 1fr 1fr;
    }
}
```

#### Specific Breakpoint Ranges
```css
/* Extra small phones (320px-480px) */
@media (max-width: 480px) {
    .card {
        font-size: 12px;
        padding: 8px;
    }
}

/* Small phones (481px-768px) */
@media (min-width: 481px) and (max-width: 768px) {
    .card {
        font-size: 13px;
        padding: 10px;
    }
}

/* Tablets (769px-1024px) */
@media (min-width: 769px) and (max-width: 1024px) {
    .card {
        font-size: 14px;
        padding: 12px;
    }
}

/* Desktop (1025px+) */
@media (min-width: 1025px) {
    .card {
        font-size: 15px;
        padding: 14px;
    }
}
```

### Responsive Grids

#### Auto-Responsive Grid
```css
.grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
}

/* Mobile override */
@media (max-width: 768px) {
    .grid {
        grid-template-columns: 1fr;
        gap: 12px;
    }
}
```

#### Flexible Grid
```css
.grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: 16px;
}

@media (min-width: 769px) {
    .grid {
        grid-template-columns: repeat(2, 1fr);
    }
}

@media (min-width: 1025px) {
    .grid {
        grid-template-columns: repeat(3, 1fr);
    }
}
```

### Responsive Typography

```css
body {
    font-size: 14px;
    line-height: 1.5;
}

h1 {
    font-size: 1.5rem;
}

h2 {
    font-size: 1.25rem;
}

h3 {
    font-size: 1.1rem;
}

/* Tablet and up */
@media (min-width: 769px) {
    body {
        font-size: 15px;
    }
    
    h1 {
        font-size: 1.75rem;
    }
}

/* Desktop */
@media (min-width: 1025px) {
    body {
        font-size: 16px;
    }
    
    h1 {
        font-size: 2rem;
    }
}
```

### Touch Optimization

```css
/* Minimum touch target size */
button,
a[role="button"],
.btn {
    min-width: 44px;
    min-height: 44px;
    padding: 10px 14px;
}

/* Input fields */
input,
textarea,
select {
    min-height: 44px;
    font-size: 16px; /* Prevents zoom on iOS */
}

/* Remove hover effects on touch devices */
@media (hover: none) {
    .btn:hover {
        transform: none;
        box-shadow: var(--shadow);
    }
    
    .btn:active {
        transform: scale(0.98);
    }
}
```

### Safe Area Support

```css
/* Add padding for notch devices */
@supports (padding: max(0px)) {
    body {
        padding-left: max(12px, env(safe-area-inset-left));
        padding-right: max(12px, env(safe-area-inset-right));
        padding-bottom: max(12px, env(safe-area-inset-bottom));
    }
}

/* Alternative with CSS variables */
:root {
    --safe-top: 0;
    --safe-bottom: 0;
    --safe-left: 0;
    --safe-right: 0;
}

@supports (padding: env(safe-area-inset-top)) {
    :root {
        --safe-top: env(safe-area-inset-top);
        --safe-bottom: env(safe-area-inset-bottom);
        --safe-left: env(safe-area-inset-left);
        --safe-right: env(safe-area-inset-right);
    }
}

body {
    padding-top: var(--safe-top);
    padding-bottom: var(--safe-bottom);
}
```

## HTML Examples

### Responsive Meta Tags

```html
<head>
    <!-- Standard responsive viewport -->
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    
    <!-- With notch support -->
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    
    <!-- With safe max zoom -->
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5">
    
    <!-- Full mobile optimization -->
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover, maximum-scale=5, user-scalable=yes">
    
    <!-- Theme color for mobile browser UI -->
    <meta name="theme-color" content="#0052cc">
    
    <!-- Description for mobile -->
    <meta name="description" content="Your app description">
</head>
```

### Responsive Images

```html
<!-- Basic responsive image -->
<img 
    src="image.png" 
    alt="Description"
    style="width: 100%; height: auto;"
>

<!-- With srcset for different sizes -->
<img 
    src="image-medium.jpg"
    srcset="image-small.jpg 480w,
            image-medium.jpg 768w,
            image-large.jpg 1024w"
    sizes="(max-width: 480px) 100vw,
           (max-width: 768px) 90vw,
           80vw"
    alt="Description"
>

<!-- Picture element for different formats -->
<picture>
    <source media="(max-width: 480px)" srcset="image-small.webp">
    <source media="(max-width: 768px)" srcset="image-medium.webp">
    <img src="image-large.jpg" alt="Description">
</picture>
```

### Show/Hide Based on Device

```html
<!-- Hide on mobile, show on desktop -->
<div class="hide-mobile">Content for desktop only</div>

<!-- Show on mobile, hide on desktop -->
<div class="show-mobile">Content for mobile only</div>

<!-- Alternative with data attributes -->
<div data-show-mobile="false">Desktop only</div>
<div data-show-desktop="false">Mobile only</div>
```

### Responsive Forms

```html
<form class="responsive-form">
    <!-- Single column on mobile -->
    <div class="form-row">
        <div class="form-group">
            <label for="name">Name</label>
            <input type="text" id="name" name="name" required>
        </div>
    </div>
    
    <!-- Two columns on desktop -->
    <div class="form-row" style="display: grid; grid-template-columns: 1fr;">
        <div class="form-group">
            <label for="email">Email</label>
            <input type="email" id="email" name="email" required>
        </div>
        <div class="form-group">
            <label for="phone">Phone</label>
            <input type="tel" id="phone" name="phone">
        </div>
    </div>
    
    <button type="submit" class="btn btn-primary">Submit</button>
</form>

<style>
    @media (min-width: 769px) {
        .form-row {
            grid-template-columns: 1fr 1fr !important;
            gap: 16px;
        }
    }
</style>
```

## Common Patterns

### Mobile Menu Button

```html
<button id="mobileMenuBtn" class="mobile-menu-btn">
    <i class="fas fa-bars"></i>
</button>

<div id="sidebar" class="sidebar">
    <!-- Sidebar content -->
</div>

<script>
    document.addEventListener('DOMContentLoaded', () => {
        initMobileMenuButton('mobileMenuBtn', 'sidebar');
    });
</script>
```

### Responsive Card Grid

```html
<div class="card-grid">
    <div class="card">Card 1</div>
    <div class="card">Card 2</div>
    <div class="card">Card 3</div>
    <div class="card">Card 4</div>
</div>

<style>
    .card-grid {
        display: grid;
        grid-template-columns: 1fr;
        gap: 16px;
    }
    
    @media (min-width: 769px) {
        .card-grid {
            grid-template-columns: repeat(2, 1fr);
        }
    }
    
    @media (min-width: 1025px) {
        .card-grid {
            grid-template-columns: repeat(3, 1fr);
        }
    }
</style>
```

### Responsive Table

```html
<div class="table-responsive">
    <table class="data-table">
        <thead>
            <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Status</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td data-label="Name">John Doe</td>
                <td data-label="Email">john@example.com</td>
                <td data-label="Status">Active</td>
            </tr>
        </tbody>
    </table>
</div>

<script>
    makeTableResponsive('data-table');
</script>
```

## Advanced Usage

### Conditional Logic Based on Device

```javascript
// Initialize differently based on device
if (isMobileView()) {
    // Mobile-specific initialization
    initMobileSidebar();
    disableHoverEffects();
    initTouchGestures();
} else if (isTabletView()) {
    // Tablet-specific initialization
    initTabletLayout();
} else {
    // Desktop-specific initialization
    initDesktopLayout();
    initHoverEffects();
}
```

### Responsive Event Listeners

```javascript
// Listen for resize and adapt
let resizeTimer;
window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
        // Recalculate layout
        if (isMobileView()) {
            // Mobile layout
        } else {
            // Desktop layout
        }
    }, 250); // Debounce
});
```

### Dynamic Responsive Adjustments

```javascript
// Adjust modal size based on device
function openModal(modalId) {
    const modal = document.getElementById(modalId);
    
    if (isMobileView()) {
        modal.style.maxWidth = '95vw';
        modal.style.maxHeight = '90vh';
    } else if (isTabletView()) {
        modal.style.maxWidth = '80vw';
        modal.style.maxHeight = '85vh';
    } else {
        modal.style.maxWidth = '600px';
        modal.style.maxHeight = '90vh';
    }
    
    modal.classList.add('active');
}
```

### Responsive Debugging

```javascript
// Debug current breakpoint
function debugResponsive() {
    console.log('=== RESPONSIVE DEBUG ===');
    console.log('Viewport Width:', window.innerWidth);
    console.log('Viewport Height:', window.innerHeight);
    console.log('Current Breakpoint:', getCurrentBreakpoint());
    console.log('Is Mobile:', isMobileView());
    console.log('Is Tablet:', isTabletView());
    console.log('Is Desktop:', isDesktopView());
    console.log('Is Touch Device:', isTouchDevice());
    console.log('Safe Areas:', getSafeAreaInsets());
}

// Call when needed
window.addEventListener('resize', debugResponsive);
debugResponsive(); // Initial check
```

## Testing Examples

### Test Mobile Breakpoints

```javascript
// Test all breakpoints
const breakpoints = [320, 480, 768, 1024, 1920];

breakpoints.forEach(width => {
    window.resizeTo(width, 768);
    console.log(`Testing at ${width}px: ${getCurrentBreakpoint()}`);
});
```

### Simulate Touch

```javascript
// Simulate touch event
function simulateTouch(element) {
    const touch = new Touch({
        identifier: Date.now(),
        target: element,
        clientX: 0,
        clientY: 0,
        screenX: 0,
        screenY: 0,
        pageX: 0,
        pageY: 0
    });
    
    element.dispatchEvent(new TouchEvent('touchstart', {
        touches: [touch],
        targetTouches: [touch],
        changedTouches: [touch]
    }));
}
```

---

## Quick Reference

| Function | Purpose | Example |
|----------|---------|---------|
| `isMobileView()` | Check if mobile | `if (isMobileView()) { }` |
| `isTabletView()` | Check if tablet | `if (isTabletView()) { }` |
| `isDesktopView()` | Check if desktop | `if (isDesktopView()) { }` |
| `getCurrentBreakpoint()` | Get breakpoint | `const bp = getCurrentBreakpoint()` |
| `toggleMobileSidebar()` | Toggle menu | `toggleMobileSidebar('sidebar')` |
| `closeMobileSidebar()` | Close menu | `closeMobileSidebar('sidebar')` |
| `isTouchDevice()` | Detect touch | `if (isTouchDevice()) { }` |
| `getSafeAreaInsets()` | Get notch insets | `const safeArea = getSafeAreaInsets()` |
| `makeTableResponsive()` | Convert table | `makeTableResponsive('tableId')` |

---

For more information, see the main documentation files or refer to the implemented code in your project.
