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