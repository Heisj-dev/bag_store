const modalOverlay = document.querySelector("#modal-overlay");
const modalTriggers = document.querySelectorAll("[data-modal-target]");
const modalCloseButtons = document.querySelectorAll("[data-modal-close]");

let activeModal = null;


/* =========================
   MODAL ENGINE
   (shared by SHIPPING & RETURNS,
   TERMS, and CONTACT)
   ========================= */

function openModal(modal) {

    if (!modal || !modalOverlay) {
        return;
    }

    activeModal = modal;

    modal.classList.add("is-open");
    modal.setAttribute("aria-hidden", "false");

    modalOverlay.classList.add("is-visible");
    document.body.classList.add("modal-open");

    const firstField = modal.querySelector("input, textarea, button, a");
    if (firstField) {
        firstField.focus();
    }
}

function closeModal() {

    if (!activeModal) {
        return;
    }

    activeModal.classList.remove("is-open");
    activeModal.setAttribute("aria-hidden", "true");

    modalOverlay.classList.remove("is-visible");
    document.body.classList.remove("modal-open");

    activeModal = null;
}

modalTriggers.forEach(function (trigger) {

    trigger.addEventListener("click", function () {

        const targetId = trigger.getAttribute("data-modal-target");
        const modal = document.getElementById(targetId);
        openModal(modal);
    });
});

modalCloseButtons.forEach(function (button) {
    button.addEventListener("click", closeModal);
});

if (modalOverlay) {
    modalOverlay.addEventListener("click", closeModal);
}

// Escape closes whichever modal is open — same convention as the nav drawer.
document.addEventListener("keydown", function (event) {

    if (event.key === "Escape" && activeModal) {
        closeModal();
    }
});