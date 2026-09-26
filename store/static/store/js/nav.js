const menuToggle = document.querySelector(".menu-toggle");
const navDrawer = document.querySelector("#nav-drawer");
const drawerClose = document.querySelector("#drawer-close");
const drawerOverlay = document.querySelector("#drawer-overlay");

const searchToggle = document.querySelector(".search-toggle");
const searchPanel = document.querySelector("#search-panel");

const filterToggle = document.querySelector("#filter-toggle");
const filterPanel = document.querySelector("#filter-panel");


/* =========================
   DRAWER
   ========================= */

function openDrawer() {

    if (!navDrawer || !menuToggle) {
        return;
    }

    navDrawer.classList.add("is-open");
    drawerOverlay.classList.add("is-visible");
    navDrawer.setAttribute("aria-hidden", "false");
    menuToggle.setAttribute("aria-expanded", "true");
}

function closeDrawer() {

    if (!navDrawer || !menuToggle) {
        return;
    }

    navDrawer.classList.remove("is-open");
    drawerOverlay.classList.remove("is-visible");
    navDrawer.setAttribute("aria-hidden", "true");
    menuToggle.setAttribute("aria-expanded", "false");
}

if (menuToggle && navDrawer) {

    menuToggle.addEventListener("click", function () {

        if (navDrawer.classList.contains("is-open")) {
            closeDrawer();
        } else {
            openDrawer();
        }
    });

    if (drawerClose) {
        drawerClose.addEventListener("click", closeDrawer);
    }

    if (drawerOverlay) {
        drawerOverlay.addEventListener("click", closeDrawer);
    }

    navDrawer.querySelectorAll("a, button[type='submit']").forEach(function (el) {
        el.addEventListener("click", closeDrawer);
    });

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") {
            closeDrawer();
        }
    });
}


/* =========================
   DRAWER — SWIPE TO CLOSE
   (mobile: drag the open drawer
   toward the left edge to dismiss
   it, no CLOSE button needed)
   ========================= */

if (navDrawer) {

    // How far (as a fraction of the drawer's width) the user has to
    // drag before we treat it as "close", rather than snapping back open.
    const SWIPE_CLOSE_THRESHOLD = 0.35;

    let startX = 0;
    let startY = 0;
    let currentX = 0;
    let dragging = false;
    let isHorizontalSwipe = null; // decided after the first few pixels of movement

    function endDrag(shouldEvaluate) {

        dragging = false;
        navDrawer.classList.remove("is-dragging");
        navDrawer.style.transform = ""; // hand control back to the CSS class

        if (shouldEvaluate && isHorizontalSwipe) {
            const deltaX = currentX - startX;
            const draggedFraction = Math.abs(deltaX) / navDrawer.offsetWidth;

            if (deltaX < 0 && draggedFraction > SWIPE_CLOSE_THRESHOLD) {
                closeDrawer();
            }
        }
    }

    navDrawer.addEventListener("touchstart", function (event) {

        if (!navDrawer.classList.contains("is-open")) {
            return;
        }

        const touch = event.touches[0];
        startX = touch.clientX;
        startY = touch.clientY;
        currentX = startX;
        dragging = true;
        isHorizontalSwipe = null;

        navDrawer.classList.add("is-dragging");
    }, { passive: true });

    navDrawer.addEventListener("touchmove", function (event) {

        if (!dragging) {
            return;
        }

        const touch = event.touches[0];
        currentX = touch.clientX;

        const deltaX = currentX - startX;
        const deltaY = touch.clientY - startY;

        // Wait for real movement, then decide once: is this a
        // sideways swipe (closing gesture), or a vertical scroll
        // through the category list? Locking this in avoids the
        // drawer fighting with drawer-body's own scroll.
        if (isHorizontalSwipe === null && (Math.abs(deltaX) > 10 || Math.abs(deltaY) > 10)) {
            isHorizontalSwipe = Math.abs(deltaX) > Math.abs(deltaY);
        }

        if (!isHorizontalSwipe) {
            return;
        }

        // Only let the drawer follow the finger toward the left
        // (the direction it closes in) — never past fully open.
        const drag = Math.min(0, deltaX);
        navDrawer.style.transform = "translateX(" + drag + "px)";
    }, { passive: true });

    navDrawer.addEventListener("touchend", function () {
        endDrag(true);
    });

    navDrawer.addEventListener("touchcancel", function () {
        endDrag(false);
    });
}


/* =========================
   SEARCH PANEL
   ========================= */

if (searchToggle && searchPanel) {

    searchToggle.addEventListener("click", function () {

        const isOpen = searchPanel.classList.contains("is-open");

        if (isOpen) {
            searchPanel.classList.remove("is-open");
            searchPanel.setAttribute("aria-hidden", "true");
            searchToggle.setAttribute("aria-expanded", "false");
        } else {
            searchPanel.classList.add("is-open");
            searchPanel.setAttribute("aria-hidden", "false");
            searchToggle.setAttribute("aria-expanded", "true");

            const input = searchPanel.querySelector("input");
            if (input) {
                input.focus();
            }
        }
    });
}


/* =========================
   FILTER PANEL (homepage only —
   these elements won't exist on
   other pages, so this quietly
   does nothing there)
   ========================= */

if (filterToggle && filterPanel) {

    filterToggle.addEventListener("click", function () {

        const isOpen = filterPanel.classList.contains("is-open");

        if (isOpen) {
            filterPanel.classList.remove("is-open");
            filterToggle.setAttribute("aria-expanded", "false");
        } else {
            filterPanel.classList.add("is-open");
            filterToggle.setAttribute("aria-expanded", "true");
        }
    });
}