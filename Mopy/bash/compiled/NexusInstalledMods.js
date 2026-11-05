// ==UserScript==
// @name         Nexus Installed Mods
// @namespace    http://tampermonkey.net/
// @version      2026-07-18
// @description  Highlight links to an installed mods! Paste comma-separated ids to the top left invisible field on a mod page.
// @author       You
// @match        https://www.nexusmods.com/*
// @icon         https://www.google.com/s2/favicons?sz=64&domain=nexusmods.com
// @grant        none
// ==/UserScript==

(function() {
    'use strict';

    function run() {
        let installed = load_installed_mods_for_game().split(',').map((x) => +x);
        let allLinks = []
        let hostLinks = document.getElementsByTagName('a');
        for (let i = 0, n = hostLinks.length; i < n; ++i) {
            let item = hostLinks.item(i);
            allLinks.push(item);
        }
        let mainRequirements = document.getElementsByTagName('main-file-requirements');
        for (let i = 0, n = mainRequirements.length; i < n; ++i) {
            let item = mainRequirements.item(i);
            let internalLinks = item.shadowRoot.querySelectorAll('a');
            for (let j = 0, m = internalLinks.length; j < m; ++j) {
                let item = internalLinks.item(j);
                allLinks.push(item);
            }
        }
        let manualDownload = document.getElementById('next-shadow-root');
        if (manualDownload) {
            let internalLinks = manualDownload.shadowRoot.querySelectorAll('a');
            for (let j = 0, m = internalLinks.length; j < m; ++j) {
                let item = internalLinks.item(j);
                allLinks.push(item);
            }
        }
        for (let item of allLinks) {
            let href;
            try {
                href = new URL(item.href);
            } catch (error) {
                continue;
            }
            let match = /^\/[^\/]+\/mods\/(\d+)\/?/g.exec(href.pathname);
            if (match && installed.includes(+match[1])) {
                item.style.color = 'darkturquoise';
            }
        }
    }

    function run_on_dom_change() {
        window.nexus_istalled_mods_disabled = true;
        run();
        window.nexus_istalled_mods_disabled = false;
    }

    function on_dom_change() {
        if (window.nexus_istalled_mods_disabled) {
            return;
        }
        if (window.nexus_istalled_mods_timer) {
            clearTimeout(window.nexus_istalled_mods_timer);
        }
        window.nexus_istalled_mods_timer = setTimeout(run_on_dom_change, 1000);
    }

    run_on_dom_change();

    if (window.nexus_istalled_mods_observer) {
        window.nexus_istalled_mods_observer.disconnect();
    }

    window.nexus_istalled_mods_observer = new MutationObserver(on_dom_change);
    window.nexus_istalled_mods_observer.observe(document, {childList: true, subtree: true});
    window.nexus_istalled_mods_game = 'unknown';

    function on_ids_change(event) {
        if (load_installed_mods_for_game() !== event.currentTarget.value) {
            save_installed_mods(event.currentTarget.value);
        }
    }

    function load_installed_mods() {
        try {
            let json = localStorage.getItem('nexus_istalled_mods');
            let data = json && JSON.parse(json);
            return data || {};
        } catch (error) {
            console.error(error);
            return {}
        }
    }

    function load_installed_mods_for_game() {
        let data = load_installed_mods();
        return data[window.nexus_istalled_mods_game] || '';
    }

    function save_installed_mods(mods) {
        let data = load_installed_mods();
        data[window.nexus_istalled_mods_game] = mods;
        localStorage.setItem('nexus_istalled_mods', JSON.stringify(data));
    }

    let gameMatch = /^\/([^\/]+)\/(mods|users).*/g.exec((new URL(location.href)).pathname);

    if (gameMatch) {
        window.nexus_istalled_mods_game = gameMatch[1];
        let ids_element = document.createElement('input');
        ids_element.style.width = '40px';
        ids_element.style.height = '40px';
        ids_element.value = load_installed_mods_for_game();
        ids_element.addEventListener('change', on_dom_change);
        ids_element.addEventListener('change', on_ids_change);
        ids_element.addEventListener('keyup', on_dom_change);
        ids_element.addEventListener('keyup', on_ids_change);
        ids_element.addEventListener('paste', on_dom_change);
        ids_element.addEventListener('paste', on_ids_change);
        let header = document.getElementsByClassName('rj-header-wrap').item(0);
        header.appendChild(ids_element);
    }
})();
