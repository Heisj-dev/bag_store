/* Theme preference is local to this browser; no account is required. */
(function () {
    'use strict';
    var key = 'bagsnbeyond-theme';
    var root = document.documentElement;
    var media = window.matchMedia('(prefers-color-scheme: dark)');
    var preference = 'system';
    var storageAvailable = true;
    function valid(value) {
        return value === 'light' || value === 'dark' ? value : 'system';
    }
    try { preference = valid(localStorage.getItem(key)); } catch (_) { storageAvailable = false; }
    function apply() {
        var dark = preference === 'dark' || (preference === 'system' && media.matches);
        root.dataset.theme = dark ? 'dark' : 'light';
        root.style.colorScheme = root.dataset.theme;
        var meta = document.querySelector('meta[name="theme-color"]');
        if (meta) meta.content = dark ? '#000000' : '#f2f1ed';
        document.querySelectorAll('[data-theme-toggle]').forEach(function (button) {
            var label = dark ? 'Switch to light mode' : 'Switch to dark mode';
            button.setAttribute('aria-label', label);
            button.title = label;
        });
        document.querySelectorAll('[data-theme-label]').forEach(function (label) {
            label.textContent = dark ? 'Light mode' : 'Dark mode';
        });
        document.querySelectorAll('[data-theme-choice]').forEach(function (input) {
            input.checked = input.value === preference;
        });
        document.querySelectorAll('[data-theme-status]').forEach(function (status) {
            status.textContent = preference === 'system'
                ? 'Following your device · ' + (dark ? 'Dark' : 'Light')
                : (dark ? 'Dark' : 'Light') + (storageAvailable ? ' · Saved for this browser' : ' · For this visit');
        });
    }
    function choose(value) {
        preference = valid(value);
        try {
            if (preference === 'system') localStorage.removeItem(key);
            else localStorage.setItem(key, preference);
        } catch (_) { storageAvailable = false; }
        apply();
    }
    apply();
    if (media.addEventListener) media.addEventListener('change', apply);
    else media.addListener(apply);
    window.addEventListener('storage', function (event) {
        if (event.key === key || event.key === null) {
            preference = valid(event.newValue);
            apply();
        }
    });
    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('[data-theme-controls]').forEach(function (el) { el.hidden = false; });
        document.querySelectorAll('[data-theme-toggle]').forEach(function (button) {
            button.addEventListener('click', function () {
                choose(root.dataset.theme === 'dark' ? 'light' : 'dark');
            });
        });
        document.querySelectorAll('[data-theme-choice]').forEach(function (input) {
            input.addEventListener('change', function () { if (input.checked) choose(input.value); });
        });
        apply();
    });
}());
