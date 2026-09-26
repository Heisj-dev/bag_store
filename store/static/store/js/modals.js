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

    resetContactFormIfNeeded(activeModal);

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


/* =========================
   CONTACT FORM
   (client-side only for now —
   there's no Django view wired up
   to receive this yet, so "sent"
   just confirms the UI flow)
   ========================= */

const contactForm = document.querySelector("#contact-form");
const contactSuccess = document.querySelector("#contact-success");

function showFieldError(fieldId, message) {

    const field = document.querySelector("#" + fieldId);
    const errorEl = document.querySelector("#" + fieldId + "-error");

    if (errorEl) {
        errorEl.textContent = message;
    }

    if (field) {
        const group = field.closest(".form-group");
        if (group) {
            group.classList.add("has-error");
        }
    }
}

function clearFieldError(fieldId) {

    const field = document.querySelector("#" + fieldId);
    const errorEl = document.querySelector("#" + fieldId + "-error");

    if (errorEl) {
        errorEl.textContent = "";
    }

    if (field) {
        const group = field.closest(".form-group");
        if (group) {
            group.classList.remove("has-error");
        }
    }
}

function resetContactForm() {

    if (!contactForm) {
        return;
    }

    contactForm.reset();
    contactForm.hidden = false;

    ["contact-name", "contact-phone", "contact-message"].forEach(clearFieldError);

    if (contactSuccess) {
        contactSuccess.hidden = true;
    }
}

function resetContactFormIfNeeded(modal) {

    if (modal && modal.id === "contact-modal") {
        resetContactForm();
    }
}

if (contactForm) {

    contactForm.addEventListener("submit", function (event) {

        event.preventDefault();

        const name = contactForm.querySelector("#contact-name").value.trim();
        const phone = contactForm.querySelector("#contact-phone").value.trim();
        const message = contactForm.querySelector("#contact-message").value.trim();

        let isValid = true;

        if (name.length < 2) {
            showFieldError("contact-name", "Please enter your name.");
            isValid = false;
        } else {
            clearFieldError("contact-name");
        }

        const phonePattern = /^[0-9+\s-]{7,15}$/;
        if (!phonePattern.test(phone)) {
            showFieldError("contact-phone", "Please enter a valid phone number.");
            isValid = false;
        } else {
            clearFieldError("contact-phone");
        }

        if (message.length < 5) {
            showFieldError("contact-message", "Tell us a little about your inquiry.");
            isValid = false;
        } else {
            clearFieldError("contact-message");
        }

        if (!isValid) {
            return;
        }

        contactForm.hidden = true;

        if (contactSuccess) {
            contactSuccess.hidden = false;
        }
    });
}