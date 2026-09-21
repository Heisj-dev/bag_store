const galleryTrack = document.querySelector(".gallery-track");
const gallerySlides = document.querySelectorAll(".gallery-slide");
const galleryDots = document.querySelectorAll(".gallery-dot");

let currentSlide = 0;


/* =========================
   UPDATE GALLERY
   ========================= */

function updateGallery() {

    if (!galleryTrack || gallerySlides.length === 0) {
        return;
    }

    galleryTrack.style.transform =
        `translateX(-${currentSlide * 100}%)`;

    galleryDots.forEach(function (dot, index) {
        dot.classList.toggle("active", index === currentSlide);
    });
}


/* =========================
   GO TO SLIDE
   ========================= */

function goToSlide(index) {

    if (gallerySlides.length === 0) {
        return;
    }

    currentSlide = index;

    if (currentSlide >= gallerySlides.length) {
        currentSlide = 0;
    }

    if (currentSlide < 0) {
        currentSlide = gallerySlides.length - 1;
    }

    updateGallery();
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
   KEYBOARD CONTROLS
   ========================= */

document.addEventListener("keydown", function (event) {

    if (!galleryTrack || gallerySlides.length <= 1) {
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
   TOUCH / SWIPE CONTROLS
   ========================= */

let touchStartX = 0;
let touchEndX = 0;

if (galleryTrack) {

    galleryTrack.addEventListener(
        "touchstart",
        function (event) {
            touchStartX = event.touches[0].clientX;
        },
        { passive: true }
    );

    galleryTrack.addEventListener(
        "touchend",
        function (event) {
            touchEndX = event.changedTouches[0].clientX;
            handleSwipe();
        },
        { passive: true }
    );
}

function handleSwipe() {

    const swipeDistance = touchEndX - touchStartX;
    const minimumSwipeDistance = 50;

    if (Math.abs(swipeDistance) < minimumSwipeDistance) {
        return;
    }

    if (swipeDistance < 0) {
        showNextSlide();
    }

    if (swipeDistance > 0) {
        showPreviousSlide();
    }
}


/* =========================
   INITIALIZE
   ========================= */

updateGallery();