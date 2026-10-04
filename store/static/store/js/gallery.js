const galleryTrack = document.querySelector(".gallery-track");
const gallerySlides = document.querySelectorAll(".gallery-slide");
const galleryDots = document.querySelectorAll(".gallery-dot");

let currentSlide = 0;


/* =========================
   HOW THE GALLERY WORKS

   The photos sit side by side inside .gallery-track. The browser itself
   scrolls the track sideways and snaps to one photo at a time (see the
   .gallery-track rules in style.css), so a swipe is handled by the phone,
   not by this script. That is what keeps swiping reliable on iPhone.

   This script only:
     - lights the dot of the photo that is showing, and
     - moves to a photo when a dot, an arrow or a keyboard arrow is used.
   ========================= */


/* =========================
   HELPERS
   ========================= */

function slideWidth() {
    return galleryTrack.clientWidth;
}

function prefersReducedMotion() {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function scrollTrackTo(left, smooth) {

    if (typeof galleryTrack.scrollTo === "function") {
        galleryTrack.scrollTo({
            left: left,
            behavior: smooth ? "smooth" : "auto"
        });
    } else {
        galleryTrack.scrollLeft = left;
    }
}


/* =========================
   DOTS
   ========================= */

function updateDots() {

    galleryDots.forEach(function (dot, index) {
        dot.classList.toggle("active", index === currentSlide);
    });
}


/* =========================
   FOLLOW THE SCROLLING
   (a swipe moves the track: work out which photo is showing)
   ========================= */

let scrollTarget = null;      // where a dot / arrow click is taking the track
let scrollTargetTimer = null;
let scrollQueued = false;

function syncFromScroll() {

    const width = slideWidth();

    if (width === 0) {
        return;
    }

    // While the track glides to a photo chosen with a dot or an arrow,
    // wait until it arrives (the right dot is already lit).
    if (scrollTarget !== null) {

        if (Math.abs(galleryTrack.scrollLeft - scrollTarget) > 2) {
            return;
        }

        scrollTarget = null;
        clearTimeout(scrollTargetTimer);
    }

    let index = Math.round(galleryTrack.scrollLeft / width);
    index = Math.max(0, Math.min(index, gallerySlides.length - 1));

    if (index !== currentSlide) {
        currentSlide = index;
        updateDots();
    }
}

if (galleryTrack) {

    galleryTrack.addEventListener(
        "scroll",
        function () {

            if (scrollQueued) {
                return;
            }

            scrollQueued = true;

            window.requestAnimationFrame(function () {
                scrollQueued = false;
                syncFromScroll();
            });
        },
        { passive: true }
    );
}


/* =========================
   GO TO SLIDE
   ========================= */

function goToSlide(index) {

    if (!galleryTrack || gallerySlides.length === 0) {
        return;
    }

    if (index >= gallerySlides.length) {
        index = 0;
    }

    if (index < 0) {
        index = gallerySlides.length - 1;
    }

    currentSlide = index;
    updateDots();

    scrollTarget = index * slideWidth();

    // Safety: if the glide is interrupted (a finger lands on the photo),
    // stop waiting for it and read the real position instead.
    clearTimeout(scrollTargetTimer);
    scrollTargetTimer = setTimeout(function () {
        scrollTarget = null;
        syncFromScroll();
    }, 1200);

    scrollTrackTo(scrollTarget, !prefersReducedMotion());
}

function showNextSlide() {
    goToSlide(currentSlide + 1);
}

function showPreviousSlide() {
    goToSlide(currentSlide - 1);
}


/* =========================
   DOT CONTROLS
   ========================= */

galleryDots.forEach(function (dot) {

    dot.addEventListener("click", function () {
        goToSlide(parseInt(dot.dataset.index, 10));
    });

});


/* =========================
   ARROW CONTROLS
   (styled in the stylesheet — shown only
   on devices with a mouse; touch devices swipe)
   ========================= */

document.querySelectorAll(".gallery-arrow-prev").forEach(function (button) {
    button.addEventListener("click", showPreviousSlide);
});

document.querySelectorAll(".gallery-arrow-next").forEach(function (button) {
    button.addEventListener("click", showNextSlide);
});


/* =========================
   KEYBOARD CONTROLS
   ========================= */

document.addEventListener("keydown", function (event) {

    if (!galleryTrack || gallerySlides.length <= 1) {
        return;
    }

    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
        return;
    }

    // Arrow keys must keep working inside the search box and other fields.
    const target = event.target;

    if (
        target &&
        (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))
    ) {
        return;
    }

    if (event.key === "ArrowRight") {
        event.preventDefault();
        showNextSlide();
    }

    if (event.key === "ArrowLeft") {
        event.preventDefault();
        showPreviousSlide();
    }

});


/* =========================
   TURNING THE PHONE
   (keep the same photo showing when the width changes.
   The iPhone address bar growing or shrinking changes
   only the height, so it is ignored.)
   ========================= */

let lastWidth = galleryTrack ? slideWidth() : 0;

window.addEventListener("resize", function () {

    if (!galleryTrack) {
        return;
    }

    const width = slideWidth();

    if (width === lastWidth) {
        return;
    }

    lastWidth = width;
    scrollTrackTo(currentSlide * width, false);
});


/* =========================
   INITIALIZE
   ========================= */

updateDots();