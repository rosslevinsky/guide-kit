// Run a built page's own navigation script in a DOM and report what it built.
//
// WHY THIS EXISTS. `WEB_NAV_JS` is the one part of the kit that no Python test
// can execute: it is a string of JavaScript that only means anything once a
// browser has run it over a rendered page. Everything about it used to be pinned
// by searching the SOURCE for literals — which catches deletion and renaming and
// nothing else. A cross-model review found an `aria-current` regression that
// every one of those literal assertions passed straight through, because the
// literal it looked for was present and the logic around it was wrong.
//
// WHY jsdom AND NOT A BROWSER. Measured: chromium is 379 MB extracted against
// jsdom's 11 MB, and `pixi.lock` is a drift-canary trigger path, so adding a
// browser to the pinned environment re-renders every guide's PDF to prove a
// navigation script works. jsdom needs no binaries and no lockfile change.
//
// WHAT THIS CANNOT SEE, stated so nobody reads more into a pass than is there:
// jsdom does no LAYOUT. `getBoundingClientRect()` returns zeros, so the
// scroll-spy's 96px threshold, the drawer's `--guide-header-bottom` and the
// `display: none` on a collapsed sub-list are all invisible here. Those are
// verified by driving a real browser by hand. What this covers is STRUCTURE —
// the heading walk, the nesting, which entry is expanded, and the attributes —
// which is the half that broke.
'use strict';

const fs = require('fs');
const { JSDOM, VirtualConsole } = require('jsdom');

const [file, mode] = process.argv.slice(2);
const desktop = mode !== 'mobile';

const errors = [];
const virtualConsole = new VirtualConsole();
// EVERY script error is collected and reported, and the caller fails on a
// non-empty list. This is not tidiness: the first run of this harness threw on
// `window.matchMedia` PART WAY THROUGH the script, leaving a DOM that was built
// correctly up to the throw and looked entirely healthy. A harness that reports
// only the DOM would have called that a pass.
virtualConsole.on('jsdomError', (e) => errors.push(String((e && e.message) || e)));

const dom = new JSDOM(fs.readFileSync(file, 'utf8'), {
  url: 'https://guide.test/',        // localStorage needs a real origin
  runScripts: 'dangerously',
  pretendToBeVisual: true,           // supplies requestAnimationFrame
  virtualConsole,
  beforeParse(window) {
    // jsdom implements no media queries at all. The kit's script asks exactly
    // one question — `(min-width: 1100px)` — so answering it is what selects the
    // breakpoint under test rather than a fidelity compromise.
    window.matchMedia = (query) => ({
      matches: desktop,
      media: query,
      onchange: null,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
      dispatchEvent() { return false; },
    });
  },
});

const { window } = dom;
const d = window.document;

// No navigation, ever. A chapter entry points at `../<slug>/`, and letting jsdom
// try to follow one raises "Not implemented: navigation" — an error that would
// land in `errors` and fail the run for a reason that has nothing to do with the
// behaviour under test, which is whether the drawer closes itself.
d.addEventListener('click', (e) => e.preventDefault(), true);

const text = (el) => (el.textContent || '').trim().replace(/\s+/g, ' ');

function describe() {
  const nav = d.querySelector('nav.guide-nav');
  if (!nav) return null;
  const entries = [];
  for (const li of nav.querySelectorAll('.guide-chapter-part, .guide-chapter-item')) {
    const part = li.classList.contains('guide-chapter-part');
    const a = li.querySelector(':scope > a');
    entries.push({
      kind: part ? 'part' : 'chapter',
      // A part's label is its own text; a chapter's is its link's, because the
      // item now CONTAINS its sub-list and textContent would swallow it.
      label: part ? text(li) : text(a),
      href: a ? a.getAttribute('href') : null,
      anchor: li.getAttribute('data-anchor'),
      expanded: li.classList.contains('is-expanded'),
      isCurrent: !!(a && a.classList.contains('is-current')),
      ariaCurrent: a ? a.getAttribute('aria-current') : null,
      subs: [...li.querySelectorAll(':scope > .guide-nav-sub > .guide-nav-l2')].map((s) => {
        const sa = s.querySelector('a');
        return {
          label: text(sa),
          href: sa.getAttribute('href'),
          isCurrent: sa.classList.contains('is-current'),
          ariaCurrent: sa.getAttribute('aria-current'),
        };
      }),
    });
  }
  return {
    listCount: nav.querySelectorAll('ul.guide-nav-list, ol.guide-chapter-list').length,
    headingDerivedTopLevel: nav.querySelectorAll('.guide-nav-l1').length,
    entries,
    deadAnchors: [...nav.querySelectorAll('a')]
      .map((a) => a.getAttribute('href'))
      .filter((h) => h && h.startsWith('#') && !d.getElementById(h.slice(1))),
  };
}

const out = { mode: desktop ? 'desktop' : 'mobile', errors, sidebar: describe() };

if (out.sidebar) {
  const nav = d.querySelector('nav.guide-nav');
  const toggle = d.querySelector('.guide-nav-toggle');
  // MOVED, not copied, and in the right order. `outside` is what proves the
  // move: a re-created control would satisfy "it is in the header" while the
  // server's original still sat in the topbar, which is the failure the
  // move-never-recreate rule exists to prevent. Order matters because the two
  // controls drifted apart once already — the download was relocated to fix its
  // styling and the view switch was simply left behind.
  const controls = [...d.querySelectorAll('.guide-header > .download-btn, .guide-header > .guide-mode-link')]
    .map((el) => (el.classList.contains('download-btn') ? 'download' : 'mode'));
  out.header = {
    built: !!d.querySelector('header.guide-header'),
    download: !!d.querySelector('.guide-header .download-btn'),
    mode: !!d.querySelector('.guide-header .guide-mode-link'),
    order: controls,
    outside: d.querySelectorAll('.download-btn, .guide-mode-link').length
      - d.querySelectorAll('.guide-header .download-btn, .guide-header .guide-mode-link').length,
  };
  // The chapter list must have LEFT the body — it is moved, and a copy still
  // sitting where it was rendered would mean it was re-created instead.
  out.chapterListStillInBody = !!d.querySelector('body > .guide-chapters');
  out.initial = {
    open: nav.classList.contains('is-open'),
    collapsed: nav.classList.contains('is-collapsed'),
    rootCollapsed: d.documentElement.classList.contains('guide-nav-is-collapsed'),
    ariaExpanded: toggle.getAttribute('aria-expanded'),
  };
  toggle.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
  out.afterToggle = {
    open: nav.classList.contains('is-open'),
    collapsed: nav.classList.contains('is-collapsed'),
    rootCollapsed: d.documentElement.classList.contains('guide-nav-is-collapsed'),
    ariaExpanded: toggle.getAttribute('aria-expanded'),
    stored: window.localStorage.getItem('guide-nav-collapsed'),
  };
  const link = nav.querySelector('a');
  if (link) link.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
  out.afterLinkClick = {
    open: nav.classList.contains('is-open'),
    collapsed: nav.classList.contains('is-collapsed'),
  };
}

process.stdout.write(JSON.stringify(out, null, 1) + '\n');
