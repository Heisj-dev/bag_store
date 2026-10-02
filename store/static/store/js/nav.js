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

    document.body.classList.add("nav-open");
}


function closeDrawer() {

    if (!navDrawer || !menuToggle) {
        return;
    }

    navDrawer.classList.remove("is-open");
    drawerOverlay.classList.remove("is-visible");
    navDrawer.setAttribute("aria-hidden", "true");
    menuToggle.setAttribute("aria-expanded", "false");

    document.body.classList.remove("nav-open");
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


    navDrawer
        .querySelectorAll("a, button[type='submit']")
        .forEach(function (el) {

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
   ========================= */

if (navDrawer) {

    const SWIPE_CLOSE_THRESHOLD = 0.35;

    let startX = 0;
    let startY = 0;
    let currentX = 0;
    let dragging = false;
    let isHorizontalSwipe = null;


    function endDrag(shouldEvaluate) {

        dragging = false;

        navDrawer.classList.remove("is-dragging");

        navDrawer.style.transform = "";


        if (shouldEvaluate && isHorizontalSwipe) {

            const deltaX = currentX - startX;

            const draggedFraction =
                Math.abs(deltaX) / navDrawer.offsetWidth;


            if (
                deltaX < 0 &&
                draggedFraction > SWIPE_CLOSE_THRESHOLD
            ) {
                closeDrawer();
            }

        }

    }


    navDrawer.addEventListener(
        "touchstart",
        function (event) {

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

        },
        { passive: true }
    );


    navDrawer.addEventListener(
        "touchmove",
        function (event) {

            if (!dragging) {
                return;
            }

            const touch = event.touches[0];

            currentX = touch.clientX;

            const deltaX = currentX - startX;
            const deltaY = touch.clientY - startY;


            if (
                isHorizontalSwipe === null &&
                (
                    Math.abs(deltaX) > 10 ||
                    Math.abs(deltaY) > 10
                )
            ) {

                isHorizontalSwipe =
                    Math.abs(deltaX) > Math.abs(deltaY);

            }


            if (!isHorizontalSwipe) {
                return;
            }


            const drag = Math.min(0, deltaX);

            navDrawer.style.transform =
                "translateX(" + drag + "px)";

        },
        { passive: true }
    );


    navDrawer.addEventListener(
        "touchend",
        function () {
            endDrag(true);
        }
    );


    navDrawer.addEventListener(
        "touchcancel",
        function () {
            endDrag(false);
        }
    );

}


/* =========================
   SEARCH PANEL
   ========================= */

if (searchToggle && searchPanel) {

    searchToggle.addEventListener("click", function () {

        const isOpen =
            searchPanel.classList.contains("is-open");


        if (isOpen) {

            searchPanel.classList.remove("is-open");

            searchPanel.setAttribute(
                "aria-hidden",
                "true"
            );

            searchToggle.setAttribute(
                "aria-expanded",
                "false"
            );

        } else {

            searchPanel.classList.add("is-open");

            searchPanel.setAttribute(
                "aria-hidden",
                "false"
            );

            searchToggle.setAttribute(
                "aria-expanded",
                "true"
            );


            const input =
                searchPanel.querySelector("input");


            if (input) {
                input.focus();
            }

        }

    });

}


/* =========================
   FILTER PANEL
   ========================= */

if (filterToggle && filterPanel) {

    filterToggle.addEventListener("click", function () {

        const isOpen =
            filterPanel.classList.contains("is-open");


        if (isOpen) {

            filterPanel.classList.remove("is-open");

            filterToggle.setAttribute(
                "aria-expanded",
                "false"
            );

        } else {

            filterPanel.classList.add("is-open");

            filterToggle.setAttribute(
                "aria-expanded",
                "true"
            );

        }

    });

}


/* =========================
   SITE MESSAGES — AUTO DISMISS
   ========================= */

document
    .querySelectorAll(".site-message")
    .forEach(function (message) {

        window.setTimeout(function () {

            message.style.transition =
                "opacity 220ms ease, transform 220ms ease";

            message.style.opacity = "0";

            message.style.transform =
                "translateY(-6px)";


            window.setTimeout(function () {

                message.remove();

            }, 240);

        }, 3000);

    });