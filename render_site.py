#!/usr/bin/env python3
"""The website renderer: screen chrome, navigation, and app/dist/ output.

Deliberately NOT in the PDF's dependency closure. Before the split this code
lived in `build.py`, which is a PDF stamp input, so editing the site's CSS or
its navigation script re-staled all eight reference PDFs and forced a
re-baseline of documents that had not changed. Keeping it in its own module is
what makes a screen-only edit free.

Reaches shared state as `buildcore.NAME` so monkeypatching in tests is visible
here — `REFERENCE_PDF` in particular is patched by
tests/test_build_web_fails_without_pdf.py.
"""
from __future__ import annotations


import html
import json
import re
import shutil
from pathlib import Path

import buildcore
import cfadapter
import chapters
import kitconfig

# Screen-only stylesheet for the website output. NOT in SOURCE_FILES — it
# affects only the web build, never the PDF, so editing it must not bump the
# PDF version stamp or break `make verify`. Ships opt-in: the template has only
# `style-screen.css.example`; `bootstrap.py --with-web` copies it into place.
# Its presence is also the signal that the web layer is enabled (see build_web).
STYLE_SCREEN = buildcore.ROOT / "style-screen.css"
# The website build output (gitignored). `make web` writes the deployable
# site here; Cloudflare Workers Static Assets serves this directory.
WEB_DIR = buildcore.ROOT / "app" / "dist"


# The heading-derived navigation, injected at load on the WEBSITE only.
#
# WHY A SCRIPT. Pandoc closes the Contents section before the body begins, so a
# `position: sticky` TOC inside it has no tall containing block to stick within
# — CSS alone cannot do this. And five of the seven guides have no Contents
# block at all, so the nav has to come from the heading tree rather than from an
# existing list.
#
# WHY THIS IS NOT A DIVERGENCE between the two outputs. The PDF already carries
# navigation: WeasyPrint builds an /Outlines tree over the same headings. This
# restores the website to parity in the medium's own idiom; it adds no CONTENT
# the PDF lacks.
#
# WHAT IT MAY AND MAY NOT DO. It reads headings and MOVES the existing download
# link. It never authors prose — hence no innerHTML and no insertAdjacentHTML
# anywhere below, which is asserted by tests/test_web_nav_and_favicon.py. Without
# JavaScript none of this exists and NOTHING IS LOST, because the download link
# is emitted server-side and merely relocated.
#
# The class names here are a published contract: seven target-owned stylesheets
# select on them, and sync will never touch those files. Renaming one does not
# break a build, it silently unstyles seven live sites.
WEB_NAV_JS = """
(function () {
  // NO PER-HEADING "#" ANCHOR. There was one — a real <a> revealed on hover of
  // every id-carrying h1/h2/h3, so a reader could copy a link to a section. It
  // was removed because it read as a defect rather than an affordance: a stray
  // "#" appearing next to a heading whenever the pointer crossed it, on a page
  // whose job is to be read straight through.
  //
  // NOTHING ABOUT LINKING BREAKS. The ids are emitted server-side by pandoc, not
  // by this script, so `…/chapter/#some-heading` still resolves, every bookmark
  // and cross-reference already in the wild still works, and the sidebar — which
  // is built from those same ids — is unaffected. What is gone is only the
  // visible affordance for DISCOVERING that a heading has an id.
  var headings = [].slice.call(document.querySelectorAll('h1[id], h2[id]'));
  // THE SERVER-RENDERED CHAPTER LIST, located before anything is built because
  // it — not the heading count — decides whether there is a sidebar to build.
  // It is this panel's top level wherever it exists (see "one list" below), and
  // a chapter page whose one chapter happens to carry no id-bearing heading
  // still has every other chapter to offer.
  var chapters = document.querySelector('.guide-chapters');
  if (!headings.length && !chapters) return;

  // --- sticky header, and the download link moved into it -----------------
  var header = document.createElement('header');
  header.className = 'guide-header';

  var toggle = document.createElement('button');
  toggle.className = 'guide-nav-toggle';
  toggle.setAttribute('aria-expanded', 'false');
  toggle.setAttribute('aria-controls', 'guide-nav');
  // An ICON, and the accessible name moves to `aria-label`. The word "Sections"
  // in a bordered box was the widest thing in the header and read as a form
  // control on a page that has no form; the button's whole job is to show and
  // hide a panel on the left, and a picture of that says it in 18px.
  //
  // A PANEL-LEFT icon, not a hamburger. Three stacked bars mean "site menu",
  // which is not what this does — it is the convention every editor and docs
  // site uses for "toggle the left pane", and it is the only one that stays
  // truthful on desktop, where there is no menu to open.
  //
  // Built node by node with createElementNS. Two reasons, and the second is not
  // style: `test_script_adds_navigation_only` forbids every bulk-markup sink by
  // name, and this comment may not spell those names either — the test reads the
  // script as text, so prose about the forbidden API is indistinguishable from a
  // use of it. (The repo has now been bitten by "a delimiter written inside the
  // thing that parses it" four times.) The other reason: an SVG element made
  // with createElement is an unknown HTML element and renders nothing.
  //
  // aria-hidden on the graphic so a screen reader announces the button's label
  // once, not the label plus a shape. `aria-label` is what the earlier
  // `textContent` was doing implicitly — the accessible name is unchanged.
  toggle.setAttribute('aria-label', 'Sections');
  toggle.setAttribute('title', 'Sections');
  var SVGNS = 'http://www.w3.org/2000/svg';
  var icon = document.createElementNS(SVGNS, 'svg');
  icon.setAttribute('viewBox', '0 0 16 16');
  icon.setAttribute('width', '16');
  icon.setAttribute('height', '16');
  icon.setAttribute('aria-hidden', 'true');
  icon.setAttribute('focusable', 'false');
  var frame = document.createElementNS(SVGNS, 'rect');
  frame.setAttribute('x', '1.25'); frame.setAttribute('y', '2.25');
  frame.setAttribute('width', '13.5'); frame.setAttribute('height', '11.5');
  frame.setAttribute('rx', '1.75');
  frame.setAttribute('fill', 'none');
  frame.setAttribute('stroke', 'currentColor');
  frame.setAttribute('stroke-width', '1.4');
  icon.appendChild(frame);
  var pane = document.createElementNS(SVGNS, 'line');
  pane.setAttribute('x1', '6.25'); pane.setAttribute('y1', '2.25');
  pane.setAttribute('x2', '6.25'); pane.setAttribute('y2', '13.75');
  pane.setAttribute('stroke', 'currentColor');
  pane.setAttribute('stroke-width', '1.4');
  icon.appendChild(pane);
  toggle.appendChild(icon);
  header.appendChild(toggle);

  var htitle = document.createElement('span');
  htitle.className = 'guide-header-title';
  htitle.textContent = document.title;
  header.appendChild(htitle);

  // BOTH top controls are MOVED into the sticky header, never re-created — the
  // same rule the chapter list follows further down. Moving both is the point:
  // when only the download moved, the control that survived scrolling was the
  // one a reader needs less, while the view switch scrolled away with the
  // static topbar. Order is deliberate — mode link first, download last, so the
  // rightmost item is the one pressed least.
  var mode = document.querySelector('.guide-mode-link');
  if (mode) header.appendChild(mode);
  var dl = document.querySelector('.download-btn');
  if (dl) header.appendChild(dl);          // MOVED, never re-created
  document.body.insertBefore(header, document.body.firstChild);

  // The mobile drawer is positioned directly beneath the header, so it needs
  // the header's REAL height — which changes when a long title wraps.
  function syncHeaderHeight() {
    document.documentElement.style.setProperty(
      '--guide-header-h', header.offsetHeight + 'px');
    // The header's LIVE BOTTOM EDGE, which is not the same as its height and is
    // what the mobile drawer must hang from.
    //
    // The header is `position: sticky; top: 0`, so it only sits flush with the
    // viewport once the page has scrolled. At scroll 0 it is still in normal
    // flow, pushed down by the body's own top padding — 24px on a phone. The
    // drawer was positioned at `--guide-header-h` (the HEIGHT, 51px) while the
    // header actually ended at 75px, so it opened 24px too high and the header
    // covered its first entry: `elementFromPoint` on that link returned the
    // header, and a tap did nothing. Measured on a 390px viewport before the fix.
    //
    // Recomputed on scroll because the value genuinely changes with scroll —
    // that is the whole defect. rAF-throttled so a scroll handler never does
    // layout work more than once a frame.
    document.documentElement.style.setProperty(
      '--guide-header-bottom', Math.round(header.getBoundingClientRect().bottom) + 'px');
  }
  syncHeaderHeight();
  var syncQueued = false;
  function queueHeaderSync() {
    if (syncQueued) return;
    syncQueued = true;
    window.requestAnimationFrame(function () { syncQueued = false; syncHeaderHeight(); });
  }
  window.addEventListener('resize', queueHeaderSync, { passive: true });
  window.addEventListener('scroll', queueHeaderSync, { passive: true });

  // --- the nav itself ------------------------------------------------------
  // A collision-free id. Pandoc slugifies headings, so a heading called
  // "Guide Nav" would already own #guide-nav — and then heading links, the
  // nav's own aria-controls, and any :target rule would all resolve to the
  // sidebar instead of the heading.
  var navId = 'guide-nav';
  for (var n = 2; document.getElementById(navId); n++) navId = 'guide-nav-' + n;
  toggle.setAttribute('aria-controls', navId);
  var nav = document.createElement('nav');
  nav.id = navId;
  nav.className = 'guide-nav';
  nav.setAttribute('aria-label', 'Sections');
  // --- ONE LIST, and where each of its two levels comes from ----------------
  // THE SIDEBAR IS A SINGLE TREE: parts and chapters at the top, the chapter
  // being read expanded to its own sub-headings. It used to be two flat lists
  // stacked in the same panel, and they could not be merged in the browser
  // because NEITHER SOURCE HAS BOTH FACTS. The chapter list is the document's
  // structure and knows nothing about the page in front of the reader; the
  // heading query is the page and has no idea another chapter exists.
  //
  // Measured before the change, one-page view, entries per guide:
  //
  //   accounting    49 headings vs 43 chapters + 6 parts   the SAME content twice
  //   git           43 headings vs 34 chapters + 8 parts   the same, plus the title
  //   mac-terminal  21 headings vs  7 chapters + 0 parts   14 of them sub-sections
  //
  // Which is why "just drop one of them" was not available: at chapter_level = 2
  // the two lists are near-duplicates, and at chapter_level = 1 the heading list
  // is strictly richer — dropping it would have cost mac-terminal 14 of its 21
  // entries. So the structural half is taken from the server, the page-local
  // half from the DOM, and they are nested rather than stacked.
  //
  // Without a chapter list — a guide whose site is `single` — there is no
  // document structure beyond the page itself, so the headings ARE the top
  // level and this builds what it always built.
  var list;
  // `Object.create(null)`, not `{}`. The keys are heading ids, which an author
  // controls: a chapter called "Constructor" or "To String" resolves through
  // Object.prototype on a plain object and would be mistaken for an entry that
  // exists, nesting the whole of the next chapter under nothing.
  var owners = Object.create(null);
  var tops = [];

  function linkTo(h) {
    var a = document.createElement('a');
    a.href = '#' + h.id;
    // A heading can be image-only, in which case textContent is empty and the
    // link would be unclickable and unnamed. Fall back to the image's alt text,
    // then to the id.
    var label = (h.textContent || '').replace('#', '').trim();
    if (!label) {
      var img = h.querySelector('img[alt]');
      label = (img && img.getAttribute('alt')) || h.id;
    }
    a.textContent = label;
    return a;
  }

  if (chapters) {
    // MOVED INTO THE SIDEBAR, never re-created — the same rule the download
    // button follows, and for the same reason. It is server-rendered at the END
    // of the body, so a reader without JavaScript still gets it, below the guide
    // where a contents list is harmless, and nothing is lost.
    //
    // Re-creating it here is not merely inelegant, it is impossible: this script
    // reads the headings ON THE PAGE, and on a chapter page that is one chapter,
    // so a browser-built chapter list would collapse to a single entry. That is
    // the defect that made the list server-side in the first place.
    nav.insertBefore(chapters, nav.firstChild);
    list = chapters.querySelector('.guide-chapter-list');
    [].slice.call(chapters.querySelectorAll('.guide-chapter-item')).forEach(
      function (li) {
        var id = li.getAttribute('data-anchor');
        if (id) owners[id] = li;
        tops.push(li);
      });
    // A PART OWNS NOTHING AND CLOSES WHAT IS OPEN — the same rule the splitter
    // applies to the document. Its heading is an `h1[id]` like any other, so
    // without this it would be an unrecognised heading sitting between two
    // chapters, and the part title and its blurb would be filed as sub-sections
    // of whichever chapter happened to come before it.
    [].slice.call(chapters.querySelectorAll('.guide-chapter-part')).forEach(
      function (li) {
        var id = li.getAttribute('data-anchor');
        if (id) owners[id] = null;
      });
  } else {
    list = document.createElement('ul');
    list.className = 'guide-nav-list';
    nav.appendChild(list);
    headings.forEach(function (h) {
      if (h.tagName !== 'H1') return;
      var li = document.createElement('li');
      li.className = 'guide-nav-item guide-nav-l1';
      li.appendChild(linkTo(h));
      list.appendChild(li);
      owners[h.id] = li;
      tops.push(li);
    });
  }

  // The second level: the sub-headings of whichever chapters are on THIS page.
  // On a chapter page that is one chapter; on the one-page view it is all of
  // them, and the stylesheet reveals only the one being read.
  //
  // `pairs` is the scroll-spy's index — every heading that has somewhere in the
  // sidebar to light up, paired with it. A part heading is included with no link
  // of its own, so that scrolling into a part divider clears the highlight
  // rather than leaving the previous chapter falsely marked.
  var pairs = [];
  var open = null;
  var sub = null;
  headings.forEach(function (h) {
    if (h.id in owners) {
      open = owners[h.id];
      sub = null;
      pairs.push({ h: h, a: open ? open.querySelector('a') : null, li: open });
      return;
    }
    if (h.tagName === 'H1') {
      // Not a chapter and not a part: the document's own title, or a heading in
      // front matter, or — at chapter_level = 2 — a level-1 heading the author
      // did not mark as a division. It opens nothing, and it CLOSES whatever was
      // open, which is what `chapters.split()` does with a heading at or above
      // the chapter level.
      open = null;
      sub = null;
      // PAIRED WITH NOTHING, exactly as a part heading is, so that scrolling into
      // it clears the highlight. Returning without pairing left the rule
      // inconsistent — a part cleared the mark and an unmarked h1 did not — so a
      // reader in an interlude that belongs to no chapter would still see the
      // chapter above it lit up as though they were in it.
      pairs.push({ h: h, a: null, li: null });
      return;
    }
    if (!open && chapters) return;   // a sub-heading belonging to no chapter
    var li = document.createElement('li');
    li.className = 'guide-nav-item guide-nav-l2';
    var a = linkTo(h);
    li.appendChild(a);
    if (open) {
      if (!sub) {
        sub = document.createElement('ul');
        sub.className = 'guide-nav-sub';
        open.appendChild(sub);
      }
      sub.appendChild(li);
    } else {
      // No chapter list AND no `h1` above this heading. The old builder put such
      // a heading at the top level rather than dropping it, and a document that
      // starts at `##` is otherwise navigable by nothing at all.
      list.appendChild(li);
    }
    pairs.push({ h: h, a: a, li: open });
  });

  // WHAT THE SERVER ALREADY SAID, kept so that scroll-spy can hand it back. On a
  // chapter page the current chapter's entry carries `aria-current="page"` — it
  // IS the page — and `mark()` below borrows the same attribute to announce the
  // section in view. Clearing it unconditionally therefore deleted the server's
  // statement the first time a reader scrolled past the chapter's own heading,
  // and nothing put it back.
  var served = chapters ? chapters.querySelector('a[aria-current]') : null;

  // ONE chapter is expanded at a time, and on a chapter page that is the whole
  // story: only its own headings are on the page, so nothing ever moves it.
  var expanded = null;
  function expand(li) {
    if (li === expanded) return;
    if (expanded) expanded.classList.remove('is-expanded');
    if (li) li.classList.add('is-expanded');
    expanded = li;
  }
  // Set BEFORE the panel enters the document, so a chapter page never paints a
  // collapsed tree and then opens it a frame later. The server-marked chapter is
  // the answer wherever there is one; on the one-page view the reader has not
  // scrolled yet, so the document opens where the document opens.
  expand((served && served.parentNode) || tops[0] || null);

  // --- collapse state, and why it is TWO classes rather than one -------------
  // The two breakpoints are opposite interactions wearing one name, so they get
  // one class each:
  //
  //   `is-open`      MOBILE. An overlay, closed by default, transient. It closes
  //                  itself when a link inside it is clicked, because on a phone
  //                  it covers the page you just chose to navigate to.
  //   `is-collapsed` DESKTOP. A persistent panel, SHOWN by default, hidden only
  //                  because the reader asked. It must NOT auto-close on a link
  //                  click — the whole point is that it stays put while you read.
  //
  // Reusing `is-open` for both would invert the desktop default, so anyone whose
  // JavaScript failed to run would lose the sidebar entirely, and everyone else
  // would see it flash closed-then-open on every page load. `is-collapsed` is
  // strictly additive: absent it, the behaviour is exactly what it is today.
  var COLLAPSE_KEY = 'guide-nav-collapsed';
  // Wrapped: Safari in private mode THROWS on localStorage access rather than
  // returning null, and an exception here would abort the rest of this script —
  // taking the sticky header and the section highlighting with it.
  function readCollapsed() {
    try { return localStorage.getItem(COLLAPSE_KEY) === '1'; } catch (e) { return false; }
  }
  function writeCollapsed(v) {
    try { localStorage.setItem(COLLAPSE_KEY, v ? '1' : '0'); } catch (e) {}
  }
  // Applied BEFORE the node enters the document, so there is no frame in which
  // an expanded sidebar is painted and then collapsed. The whole sidebar is
  // script-built, so this costs nothing and there is no flash to suppress.
  var collapsed = readCollapsed();
  if (collapsed) nav.classList.add('is-collapsed');
  document.documentElement.classList.toggle('guide-nav-is-collapsed', collapsed);

  document.body.insertBefore(nav, header.nextSibling);

  // Which class the button drives depends on the layout it is driving. Read at
  // click time, not cached, because a window can be resized across the boundary
  // and a laptop can be docked to an external display mid-read.
  function isDesktop() {
    return window.matchMedia('(min-width: 1100px)').matches;
  }
  // `aria-expanded` describes THE PANEL AS IT IS NOW, and the two breakpoints
  // disagree about what that means: on desktop the sidebar is showing unless
  // collapsed, on mobile it is hidden until opened. Setting it once from the
  // collapse flag reported `expanded="true"` on a phone while the drawer was
  // shut — announcing an open panel that is not there. Re-derived per breakpoint,
  // and re-derived again when the viewport crosses the boundary.
  function syncExpanded() {
    var showing = isDesktop()
      ? !nav.classList.contains('is-collapsed')
      : nav.classList.contains('is-open');
    toggle.setAttribute('aria-expanded', showing ? 'true' : 'false');
  }
  syncExpanded();
  window.matchMedia('(min-width: 1100px)').addEventListener('change', syncExpanded);
  toggle.addEventListener('click', function () {
    if (isDesktop()) {
      var isCollapsed = nav.classList.toggle('is-collapsed');
      // On the ROOT, so a guide's own stylesheet can reclaim the space the
      // sidebar was reserving. The kit must not restyle `body` itself — the
      // prose measure is guide-owned and a test enforces that boundary — so it
      // publishes the state and the width, and the guide decides the layout.
      document.documentElement.classList.toggle('guide-nav-is-collapsed', isCollapsed);
      syncExpanded();
      writeCollapsed(isCollapsed);
      return;
    }
    var open = nav.classList.toggle('is-open');
    toggle.classList.toggle('is-open', open);
    syncExpanded();
  });
  nav.addEventListener('click', function (e) {
    // Mobile only. Collapsing the desktop panel every time a reader used it
    // would make it useless for the thing it is for.
    if (e.target.tagName === 'A' && !isDesktop()) {
      nav.classList.remove('is-open');
      toggle.classList.remove('is-open');
      syncExpanded();
    }
  });

  // --- mark the section in view, and expand the chapter it is in -----------
  var current = null;
  function mark() {
    var best = null;
    for (var i = 0; i < pairs.length; i++) {
      if (pairs[i].h.getBoundingClientRect().top <= 96) best = pairs[i]; else break;
    }
    // A heading that opens no chapter — a part divider, the document's own title
    // — clears the highlight without collapsing the chapter the reader just
    // finished, because closing the tree under someone mid-scroll reads as the
    // sidebar losing its place.
    if (best && best.li) expand(best.li);
    var a = best ? best.a : null;
    if (a === current) return;
    // `aria-current` ON THE SERVED ENTRY IS NEVER TOUCHED, in either direction.
    // The two states are not alternatives: on a chapter page the server has
    // already said `page` about that entry — it IS the page — and this function
    // says `location` about whatever is in view. Writing `location` over `page`
    // downgrades the stronger statement to the weaker one, and restoring it only
    // when the highlight MOVES AWAY is no fix at all: a chapter with no
    // sub-headings has nowhere for the highlight to move to, so git-guide and
    // accounting-guide — 34 and 43 chapters, zero listed sub-headings between
    // them — would announce `location` for the rest of the reader's visit.
    // `is-current` still moves onto it, so the visible marker is unaffected.
    if (current) {
      current.classList.remove('is-current');
      if (current !== served) current.removeAttribute('aria-current');
    }
    if (a) {
      a.classList.add('is-current');
      if (a !== served) a.setAttribute('aria-current', 'location');
    }
    current = a;
  }
  mark();
  var ticking = false;
  window.addEventListener('scroll', function () {
    if (ticking) return;
    ticking = true;
    window.requestAnimationFrame(function () { mark(); ticking = false; });
  }, { passive: true });
})();
"""


# Kit-owned screen chrome. This is CONCATENATED BEFORE each guide's
# style-screen.css (which is target-owned — `never` in the manifest, so sync
# must not write it). Order is deliberate: kit chrome first means a guide can
# still override any of it from its own stylesheet, and putting these rules
# here instead means adding them to seven separate per-guide stylesheets that
# would then be free to drift apart.
#
# Only `--accent` and `--rule` are referenced, both with literal fallbacks, so
# this degrades gracefully in a guide that has not defined them.
WEB_CHROME_CSS = """
/* ---- What the kit publishes about its own sidebar ------------------------
   `--guide-nav-width` is the panel's width. It is the kit's element, so the kit
   owns the number, and a guide reserving room for it should not hardcode a value
   the kit is free to change.

   `--guide-nav-space` is how much room to RESERVE, which is the same number
   until the reader collapses the panel, and then zero. A guide's own stylesheet
   consumes this to reclaim the space; the panel itself stays 15rem wide the whole
   time, so its contents never reflow mid-transition.

   Declared on `:root`, never on `body`. The prose measure is guide-owned, and
   tests/test_wide_blocks.py::test_prose_measure_is_not_widened enforces that the
   kit emits no `body` selector at all. Publishing a variable respects that line
   exactly: the kit states a fact about its own element, and the guide decides
   what its layout does about it. */
:root { --guide-nav-width: 15rem; --guide-nav-space: var(--guide-nav-width); }
:root.guide-nav-is-collapsed { --guide-nav-space: 0rem; }

/* Once the script moves the download button into the sticky header, this bar
   has nothing in it — and an empty flex row with a bottom border is a stray
   rule across the page. `:empty` hides it only in that case, so a no-JS reader
   still gets the bar exactly as before. */
/* A bare URL is one unbreakable word, and prose has nowhere to put it: left
   alone it pushes the WHOLE PAGE into horizontal scrolling on a phone, which
   no amount of container overflow can contain because the overflow is in the
   text flow itself. Measured in windows-powershell-guide: five Microsoft Learn
   URLs rendered up to 751px wide and took the body to 827px against a 390px
   viewport.

   `anywhere` rather than `break-word` because only `anywhere` also lets the
   browser shrink the element's min-content width, which is what stops the
   overflow rather than merely rewrapping after it. Ordinary prose is
   untouched — it only acts on a word that would otherwise overflow. Kit-level
   because it is a whole CLASS of bug: no guide author should have to remember
   not to paste a long link. */
a, p, li, td, th, dd { overflow-wrap: anywhere; }

/* ---- Navigation chrome (built by WEB_NAV_JS) -----------------------------
   Baseline behaviour lives HERE, in the kit, not in the seven target-owned
   stylesheets: the script emits this DOM for every guide, so shipping the DOM
   without working rules would give each site an unstyled list and a toggle that
   changes classes while nothing opens. Guides restyle on top; they should not
   have to make it work.

   Colours go through var(--accent, …) so a guide's own palette wins where it
   defines one and the chrome is still legible where it does not. */
/* The bar is capped to the PROSE MEASURE, and that is the whole rule — it was
   previously capped to nothing at all, which is not the same as "full width".

   The header is a child of `body`, and every guide's `body` reserves the fixed
   sidebar on the left and a fixed gutter on the right, so the content box GROWS
   with the window while the prose stays capped at `--max-width`. That gave the
   bar a left edge on the text column and a right edge near the window, and
   `.guide-header-title { flex: 1 1 auto }` then pushed the download link out to
   the far one. Measured in accounting-guide, download-link right edge minus
   text right edge: 27px at 1440, 267px at 1920, 587px at 2560 — it grows about
   1px per 2px of window, so it reads as correct on a laptop and as a stray
   button on a wide monitor.

   Capping the bar rather than only its contents also lands the bottom border on
   the text column, which is the rule every guide's sheet already applies to
   `hr` and `.site-footer`: a rule that runs on past the thing it separates
   stops reading as punctuation. The cost is that the sticky bar no longer paints
   across the full content box, so anything WIDER than the measure would scroll
   visibly past it — nothing in this family is, because `.wide-block` is capped
   to the same token.

   `none` as the fallback is the old behaviour exactly, so a guide that never
   defines `--max-width` is left where it was rather than being capped to a
   number the kit invented. */
.guide-header {
  position: sticky; top: 0; z-index: 20;
  display: flex; align-items: center; gap: 0.75rem;
  /* No horizontal padding: the bar's edges now ARE the text column's edges, so
     padding would inset the title and the download link from the one column
     they exist to line up with. */
  padding: 0.5rem 0;
  max-width: var(--max-width, none);
  background: var(--page-bg, #fff);
  border-bottom: 1px solid var(--rule, #e2e2e6);
}
.guide-header-title {
  font-size: 0.9rem; font-weight: 600;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  flex: 1 1 auto;
}
/* The header title is a RUNNING head — it answers "what am I reading?" once the
   document's own <h1> has scrolled away. At scroll 0 it answers nothing: it sits
   directly above an <h1> carrying the identical string, because both come from
   the same TITLE, so the reader's first impression of every site was the name
   printed twice, 60px apart.

   So it is revealed by scrolling — but keyed to THE HEADING ITSELF, not to a
   scroll distance. A fixed distance cannot be right for the family: measured
   from the top of the page to where the `<h1>` is fully behind the sticky bar,
   japan-guide clears at 60px and git-guide — whose title island is a taller
   `.cover` block with an eyebrow line, a two-line heading and a byline — needs
   240px. Any single number is either too early for one guide or too late for
   the rest, and too early is the failure that matters: it puts the running head
   at full opacity while the heading it duplicates is still on screen, which is
   the defect being fixed.

   A view timeline on the `<h1>` measures each guide's own layout instead. The
   inset is `--guide-header-h`, which WEB_NAV_JS already publishes from the
   header's measured height, so `exit 100%` means exactly "the heading has gone
   behind the bar" rather than "the heading has left the viewport" — the two
   differ by the height of the bar, and the bar is what hides it. Measured: the
   reveal now completes at 60px in japan-guide and 240px in git-guide, at each
   guide's own crossing point, at both 390px and 1920px.

   `timeline-scope` is what makes the reference legal at all: a named timeline
   reaches its declaring element's descendants and its FOLLOWING siblings', and
   the header is inserted as the body's FIRST child — a preceding sibling of
   every title island. Hoisting the name to `:root` is what lets the chrome see
   a timeline defined further down the page.

   Written as a scroll-driven animation rather than a class toggled from
   WEB_NAV_JS on purpose: the script is the one thing on the page that may not
   run (and is asserted not to author content), while this is presentation, and
   presentation belongs in the sheet. Every fallback is the pre-existing
   always-visible title, and none of them can fail closed: a browser without
   `animation-timeline` (Firefox today) never matches the @supports; a guide
   whose title island is neither `.title-block` nor `.cover` defines no timeline,
   and an unresolved name is an inactive timeline; a guide that somehow declared
   both would have the name on two elements, which is also inactive. That is
   also why the hidden state lives in the keyframe and not in a plain
   `opacity: 0` declaration — an inactive timeline applies no effect, but a
   declaration would have applied, and the title would have been hidden for
   good. */
@supports (animation-timeline: scroll()) {
  :root { timeline-scope: --guide-title; }
  /* Both island names, because the family uses both: six guides open with
     `.title-block`, git-guide with `.cover`. */
  .title-block h1, .cover h1 {
    view-timeline-name: --guide-title;
    view-timeline-axis: block;
    view-timeline-inset: var(--guide-header-h, 3.2rem) auto;
  }
  .guide-header-title {
    animation: guide-title-reveal linear both;
    animation-timeline: --guide-title;
    animation-range: exit 0% exit 100%;
  }
  @keyframes guide-title-reveal { from { opacity: 0 } to { opacity: 1 } }
}
/* Layout only. The APPEARANCE is `.download-btn`'s own, identical here and in
   the footer — the two controls sit side by side in the header and must read as
   the pair they are, not as a button that happens to be next to a link. */
.guide-header .download-btn { margin: 0; flex: 0 0 auto; font-size: 0.85rem; }
.guide-header .guide-mode-link { flex: 0 0 auto; }
/* PHONE: the RUNNING TITLE yields, not a control.
   An earlier version of this hid the header download instead, on the reasoning
   that the footer carried a second copy. It does not any more — and it never did
   on a chapter page — so hiding it here would leave a phone with no way to reach
   the PDF at all. The title is the right thing to drop: it is a running head
   answering "what am I reading?", and on a narrow screen the document's own
   <h1> is a few pixels below it saying the same thing.

   Measured, because the first arrangement overflowed and nobody noticed: at a
   320px viewport the content box is ~288px, and toggle + view switch + download
   + three gaps came to ~309px — the bar overflowed its own box. Dropping the
   title and tightening the gaps fits both controls at every width down to 320px
   with no overflow. */
@media (max-width: 34rem) {
  .guide-header { gap: 0.5rem; }
  .guide-nav-toggle { padding: 0.3rem 0.45rem; font-size: 0.8rem; }
  .guide-header-title { display: none; }
}
/* An icon button: square, borderless, quiet. The bordered "Sections" box was the
   loudest thing in a header whose other two controls are plain links. */
.guide-nav-toggle {
  flex: 0 0 auto;
  display: inline-flex; align-items: center; justify-content: center;
  width: 1.9rem; height: 1.9rem;
  padding: 0;
  background: transparent;
  color: var(--muted, #555);
  border: 0; border-radius: 4px;
  cursor: pointer;
}
.guide-nav-toggle:hover { background: var(--rule, #e2e2e6); color: var(--accent, #0b5394); }
/* A visible focus ring, because removing the border removed the only thing a
   keyboard user could see. `:focus-visible` so it appears for the keyboard and
   not on every mouse click. */
.guide-nav-toggle:focus-visible {
  outline: 2px solid var(--accent, #0b5394);
  outline-offset: 2px;
}
/* The pane the icon depicts is the one that is showing. Dimmed when collapsed,
   so the button reports state at a glance rather than only through
   `aria-expanded`. */
.guide-nav-toggle svg line { opacity: 1; transition: opacity 0.15s ease; }
:root.guide-nav-is-collapsed .guide-nav-toggle svg line { opacity: 0.25; }

.guide-nav { font-size: 0.85rem; line-height: 1.4; }
.guide-nav ul { list-style: none; margin: 0; padding: 0; }
.guide-nav-list { margin: 0; }
/* The entry itself. It carries no visual rule of its own — the link inside it
   does the work — but the kit ships one anyway, because `.guide-nav-item` is in
   the documented class contract and a contracted name with no rule is a name a
   guide's stylesheet can select and the kit can silently rename. */
.guide-nav-item { margin: 0; padding: 0; }
/* Air between top-level parts, so a long sidebar has visible structure rather
   than one undifferentiated column of links. */
.guide-nav-list > .guide-nav-l1 + .guide-nav-l1 { margin-top: 0.4rem; }
/* A HAIRLINE RAIL down the nested level, which is the one cue that says "these
   belong to the entry above" without adding weight anywhere. The alternative was
   to make chapter entries bold, and that does not survive this family: git has 34
   chapters and accounting 43, so a heavier top level is a wall of bold rather
   than a hierarchy. The rail costs nothing on the guides that have no
   sub-headings at all, because there is no sub-list to draw it on. */
.guide-nav-sub {
  margin-left: 0.85rem;
  border-left: 1px solid var(--rule, #e2e2e6);
}
.guide-nav-l2 > a { font-size: 0.82rem; }
.guide-nav a {
  display: block; padding: 0.2rem 0.4rem;
  color: var(--muted, #555); text-decoration: none;
  border-left: 2px solid transparent;
}
.guide-nav a:hover { color: var(--accent, #0b5394); }
.guide-nav a.is-current {
  color: var(--accent, #0b5394); font-weight: 600;
  border-left-color: currentColor;
}
.guide-nav-l1 > a { font-weight: 600; color: var(--ink, #1a1a1a); }

/* Desktop: a sidebar in the left margin, sticky through the whole document.
   Only where there is genuinely room for it — below this the layout has no
   spare margin and the nav becomes the mobile drawer instead. */
@media (min-width: 1100px) {
  /* The sidebar reserves its own space in each guide's own stylesheet, not
     here: chrome CSS must not restyle `body`, because the prose measure is
     guide-owned (tests/test_wide_blocks.py::test_prose_measure_is_not_widened
     pins that boundary). What belongs here is the breakout cap below, which is
     about `.wide-block` rather than about the measure. */
  .guide-nav {
    position: fixed; top: 4rem; left: 1rem;
    width: var(--guide-nav-width, 15rem); max-height: calc(100vh - 6rem);
    /* The PANEL's width never changes — only `--guide-nav-space` does — so its
       contents do not reflow while it slides away. */
    overflow-y: auto;
    /* Not decoration. `.wide-block` centres itself with a transform, which
       creates a stacking context, so without a z-index here a wide table paints
       OVER the fixed sidebar and its links become unclickable. */
    z-index: 15;
    transition: transform 0.2s ease, opacity 0.2s ease;
  }
  /* The toggle is NOT hidden here any more. It used to be `display: none` at
     this breakpoint, which is what made the sidebar permanent on desktop. */
  .guide-nav.is-collapsed {
    /* Past its own left edge AND past the gutter, so it clears the viewport
       whatever the gutter is currently computed to be. */
    transform: translateX(calc(-100% - var(--guide-gutter, 1rem)));
    opacity: 0;
    /* Not just invisible — unreachable. Without this the collapsed panel stays
       in the tab order, so keyboard focus disappears off-screen into a list the
       reader deliberately dismissed. */
    visibility: hidden;
  }
}
/* Honour a reader who has asked the system for less motion. The panel still
   collapses; it simply stops sliding. */
@media (prefers-reduced-motion: reduce) {
  .guide-nav { transition: none; }
}

/* A jumped-to heading must not land underneath the sticky header. Without this
   every nav link and every copied heading link scrolls its target to viewport
   top 0, where the header covers it — measured at 46px, so many h2s vanished
   entirely. `scroll-margin-top` moves the scroll stop, not the layout. */
h1[id], h2[id], h3[id] { scroll-margin-top: 4.5rem; }

/* Below that, the nav is a drawer the toggle opens. Closed is the default, so
   it costs nothing until asked for. */
@media (max-width: 1099px) {
  /* FIXED, not static. The header is sticky and travels with the reader, but a
     static drawer stays where it was inserted — at the very top of the
     document. Scroll down and press Sections and it opens 6000px above the
     viewport: the button appears to do nothing at all, which is exactly how it
     behaved. Measured before the fix: top -6431px, inViewport false.

     `--guide-header-h` is published by the script from the header's measured
     height, so the drawer sits directly beneath it even when a long title
     wraps to two lines and the header grows. */
  .guide-nav {
    display: none;
    position: fixed;
    top: var(--guide-header-bottom, var(--guide-header-h, 3.2rem));
    left: 0; right: 0;
    z-index: 19;                    /* under the header (20), over the page */
    background: var(--page-bg, #fff);
    border-bottom: 1px solid var(--rule, #e2e2e6);
    box-shadow: 0 6px 12px rgba(0, 0, 0, 0.08);
    max-height: calc(100vh - var(--guide-header-bottom, var(--guide-header-h, 3.2rem)));
    overflow-y: auto;
    padding: 0.5rem 1rem 1rem;
  }
  .guide-nav.is-open { display: block; }
}

/* Nothing here styles a per-heading link element, because WEB_NAV_JS no longer
   creates one — see the note there. The hover-revealed "#" beside every heading
   is gone. Heading ids are untouched, so fragment links still resolve, and the
   `scroll-margin-top` rule above is what keeps them landing clear of the sticky
   header. */

.site-topbar:empty { display: none; }
/* NO `border-bottom`. It used to draw a full-width rule whose entire job was to
   underline one ~110px right-aligned link, and it landed between the sticky
   header's own bottom rule and the page's first `h1` border-top — three
   same-weight lines in 83px before a reader met one word of the guide. It
   separated nothing: once WEB_NAV_JS moves both controls into the header this
   container is empty anyway, and without JavaScript it holds two links that do
   not need a rule under them either. */
.site-topbar {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 1rem;
  margin: 0 0 1rem;
}
/* The chapter page's own `<h1>` is the FIRST thing in the document, so the
   `border-top` that `style-screen.css` puts on every `h1` to separate it from
   the section above has nothing above it to separate. The one-page view already
   has this exemption (`.title-block h1`); the multipage `<h1>` never matched it
   because it is a promoted chapter heading, not a title block. Adjacent-sibling,
   so it stays correct after WEB_NAV_JS empties the topbar — `display: none` does
   not remove a node from the sibling axis. */
.site-topbar + h1 { border-top: none; padding-top: 0; }
/* An authored `---` immediately before a part heading draws a rule 35px above
   the rule that heading already draws for itself. In PRINT the two never meet —
   `h1.part` forces a page break, so the separator ends one page and the heading
   opens the next — which is why this survived: it is invisible in the output the
   author proofreads. On screen both render. The heading's own border yields;
   the authored rule is the author's punctuation and stays. */
hr + h1.part { border-top: none; padding-top: 0; }

/* ---- Parts: the kit ships STRUCTURE, the guide ships appearance -----------
   A part is a division above chapters, marked `{.part}` on a heading. Two
   guides invented it independently — one as `h1.part` via a transform, one as a
   hand-written `<div>` — and both then hit the same defect: the heading that
   FOLLOWS a part draws its own separating rule, so a part opened with two lines
   40px apart. That is what belongs here. Colour, weight and letterspacing stay
   with the guide, exactly as `.callout` does.

   `.part` alone, never `h1.part`: the marker is a class precisely so it can sit
   at whatever depth a guide already uses — `#` beside `#` chapters in one guide,
   `#` above `##` chapters in another. Binding the rules to a level would put
   them back in the trap the class exists to avoid. */
.part { break-after: avoid-page; }
/* The heading under a part yields its rule; the part is the stronger, deliberate
   separation and the one carrying the division's name. Covers both spellings —
   a part followed directly by a chapter heading, and one with a blurb between. */
.part + h1, .part + h2,
.part + p + h1, .part + p + h2 { border-top: none; padding-top: 0; }
/* And an authored `---` immediately before a part is redundant with the part's
   own break. Same reasoning as `hr + h1.part` above, for the class form. */
hr + .part { border-top: none; padding-top: 0; }

/* The part label in the chapter list. Not a link — it has no page — so it is
   styled as what it is: a small heading over the group beneath it. */
.guide-chapter-part {
  margin: 0.9rem 0 0.25rem;
  padding: 0 0.4rem;
  font-size: 0.72rem;
  letter-spacing: 0.09em;
  text-transform: uppercase;
  color: var(--muted, #555);
}
.guide-chapter-part:first-child { margin-top: 0; }

/* NOTHING HIDES THE ONE-PAGE CHAPTER LIST any more, and the absence of that rule
   is load-bearing. There used to be a `display: none` on it once the sidebar
   existed, because the sidebar then carried a SECOND list built from headings
   and the two were near-duplicates on that view. There is one list now and this
   is it — hiding it would empty the sidebar on the landing page of every guide
   in the family. */
/* Selected on the CLASS, not on `.site-topbar .download-btn`, and that is the
   whole point: WEB_NAV_JS MOVES this element out of `.site-topbar` and into the
   sticky header, so a descendant selector styles it only until the script runs.
   Measured before the fix — the same link, same label, in the two places a
   reader meets it: in the header `border: 0px none`, `padding: 0px`,
   `font-weight: 400`, and in the footer a 1px bordered, 6px-radius, 700-weight
   button. The top of the page had a bare blue text link where the bottom had a
   button, and the top one is the one the reader sees first.

   The button being MOVED rather than re-created is deliberate (see WEB_NAV_JS)
   and is not the bug — the bug was styling that only described where it
   started. */
/* ONE appearance, both copies. This used to be a bordered, 6px-radius,
   700-weight button, overridden to a quiet link only once it reached the sticky
   header — which left the reader meeting the same control twice in two costumes:
   a link at the top of the page and a button at the bottom. The button is gone
   from both. A page whose entire job is to be read should not carry a permanent
   call to action; the link is there when it is wanted and silent when it is not.

   Styled on the CLASS, never on `.site-topbar .download-btn`, and that is the
   whole point: WEB_NAV_JS MOVES this element out of the topbar into the header,
   so a descendant selector would describe it only until the script ran. That
   mistake is what let the two copies drift apart in the first place. */
.download-btn {
  display: inline-block;
  /* A link's box is not the body's leading. Inheriting `line-height: 1.65` put
     11px of empty space inside it — free in the footer, 11px of permanent sticky
     chrome at the top of every page. */
  line-height: 1.2;
  color: var(--accent, #0b5394);
  text-decoration: none;
  white-space: nowrap;
}
.download-btn:hover { text-decoration: underline; }
/* There is no `.site-footer .download` rule here any more, and its absence is
   the point: the footer no longer renders a download link, so a rule aligning
   one would describe an element that is never emitted. The whole problem this
   used to solve — two copies of one control, drifting in appearance and in
   position — is solved by there being one copy. */
@media print {
  .site-topbar { display: none; }
}

/* ---- Wide-content breakout ----------------------------------------------
   The prose measure (--max-width, ~46rem) is CORRECT and is not touched here:
   at this font size that is roughly 75-90 characters per line, which is the
   readable measure. Widening body text past it makes the eye lose its place on
   the return sweep.

   Tables are the problem. They were `width: 100%` inside that measure with NO
   overflow escape, so a wide reference table was compressed into the prose
   column and wrapped into stacks — git-guide's widest row carries 179
   characters of text across 50 rows, and accounting's journal tables are
   similar. Code was already fine: the widest code line in the family is 90
   characters and `pre` already scrolls.

   So this is a per-element breakout, not a global widening. `.wide-block`
   centres a wider box on the prose column using the translate pattern rather
   than negative margins, and is capped against the VIEWPORT (not just a rem
   value) so it can never push the page into horizontal scrolling — the classic
   bug with breakout hacks. Inside it, `overflow-x: auto` means anything still
   too wide scrolls in its own box instead of overflowing the page.

   Emitted from the kit rather than added to each guide's style-screen.css,
   which is target-owned: all seven are byte-identical here today, and seven
   hand-copies would be free to drift from the moment they were made. */
.wide-block {
  /* A SCROLL CONTAINER, nothing more. It used to be a breakout: `min-width:
     100%` plus a centring transform, so a table could escape a narrow fixed
     prose column and sit wider than the text.

     That column is gone — the page is fluid and only the PROSE is capped — and
     the same rules then did real damage. `min-width: 100%` forced every table
     to the full window whether or not it had content to fill it, and the extra
     space landed in whichever column could stretch: the cash register rendered
     its three columns at 65px, 1386px, 69px on a 1920px screen. A description
     column eleven times wider than it needs is not a wide table, it is a broken
     one.

     Now the wrapper simply fills the content box and the TABLE decides its own
     width from its content, scrolling here only if it genuinely exceeds the
     space. Left-aligned, not centred, so tables line up with the prose they
     belong to. */
  width: auto;
  max-width: 100%;
  overflow-x: auto;
  /* A scroll container is a focusable region for keyboard users; without this
     they cannot reach it to scroll. tabindex is set on the element by build.py. */
  margin-block: 1.25rem;
}
/* The table's own width rules are deliberately left alone here — a guide that
   caps a table (accounting's journal entries stop at 34rem) means it, and a
   `min-width` from the kit would silently win over that `max-width`. The
   wrapper's `max-content` sizing above already ignores the sheets' percentage
   width when measuring, so the breakout still tracks the table's real width. */
.wide-block > table {
  margin: 0;
}
.wide-block:focus-visible {
  outline: 2px solid var(--accent, #0b5394);
  outline-offset: 2px;
}
/* Never break out in print. The PDF is rendered from style.css, not this file,
   but `make html` produces a browser-printable page from the SCREEN CSS, and a
   translated, viewport-sized box paginates badly. */
@media print {
  .wide-block {
    width: auto;
    margin-left: 0;
    transform: none;
    overflow-x: visible;
  }
}
/* Narrow viewports: the breakout is already viewport-capped, so it collapses to
   the content width on its own. Drop the centring maths to avoid sub-pixel
   drift at small sizes. */
@media (max-width: 48rem) {
  .wide-block {
    width: 100%;
    margin-left: 0;
    transform: none;
  }
  /* Phone only: keep columns from collapsing to unreadable widths — below this
     the table scrolls inside its box instead of squeezing. Deliberately NOT a
     desktop rule: there it is below the prose measure for a wide table (no
     effect) and ABOVE the natural width of a narrow one, which it would then
     stretch — and it beats any max-width the guide set, since min-width wins. */
  .wide-block > table {
    min-width: 32rem;
  }
  /* Same floor for a diagram: below this the labels stop being readable, which
     is the whole reason it is in a scroll container. */
  .wide-block > svg.diagram {
    min-width: 30rem;
  }
}

/* The viewport cap that used to live here is gone with the breakout that needed
   it. While `.wide-block` centred itself with a transform it sat OUTSIDE its
   content box, so nothing but an explicit `100vw` sum could stop it running
   under the sidebar or pushing the page into horizontal scroll. It is an
   ordinary in-flow block now: `max-width: 100%` resolves against the content box,
   which already starts after the sidebar, so the geometry is handled.

   Leaving the cap in place was actively harmful — `min(64rem, …)` pinned every
   wrapper to 1088px on a wide screen, which is a ceiling on the one case the
   scroll container exists to serve: the genuinely wide table that has the room
   to show itself. */

/* ── The one sidebar list ────────────────────────────────────────────────────
   This IS the sidebar: server-rendered at the end of the body and MOVED into the
   panel by WEB_NAV_JS (the same move-never-recreate rule the download button
   follows), which then nests the current chapter's own sub-headings under its
   entry. Two consequences for these rules:

   * They are written for the SIDEBAR, which is where a reader sees them — a
     boxed two-column card was right when this sat in the body and is wrong in a
     15rem column.
   * They must also be survivable in the BODY, because that is where a reader
     without JavaScript gets it. Nothing here assumes the sidebar's width. */
.guide-chapters {
  margin: 0;
  font-size: 0.85rem;
  line-height: 1.4;
}
/* Only while it is still IN the body — which means a reader whose JavaScript did
   not run, since the script's first act with this node is to move it out. There
   it is a contents list at the foot of the guide and wants separating from the
   prose above it; in the panel it is the whole content and a rule around it
   would be underlining nothing. Not `body { … }`: the prose measure is
   guide-owned and the kit does not restyle the element that carries it. */
body > .guide-chapters {
  margin: 2rem 0 0;
  padding-top: 0.9rem;
  border-top: 1px solid var(--rule, #e3e3e3);
}
.guide-chapter-list { list-style: none; margin: 0; padding: 0; }
/* THE PADDING IS ON THE LINK, not on the item, and moving it was a fix rather
   than a tidy-up. While the two lists were separate the item carried
   `padding: 0.2rem 0.4rem` and `.guide-nav a` put the same padding on the anchor
   INSIDE it — different elements, so the two added up and chapter entries sat
   0.8rem in while heading entries sat 0.4rem in. Two lists in one panel on two
   different left edges. One list cannot afford that, and a block-level link is
   also what makes the whole row a click target rather than just the words. */
.guide-chapter-item { margin: 0; padding: 0; }
.guide-chapter-item > a {
  display: block;
  padding: 0.2rem 0.4rem;
  text-decoration: none;
  color: var(--muted, #555);
  border-left: 2px solid transparent;
}
.guide-chapter-item > a:hover { color: var(--accent, #0b5394); }
/* The same marker a sub-heading gets from `.guide-nav a.is-current`, including
   the left rule. The two rules have equal specificity and this one is later, so
   without naming the border here the chapter you are ON would be the one entry
   in the tree marked differently from every other. */
.guide-chapter-item.is-current > a {
  color: var(--accent, #0b5394); font-weight: 600;
  border-left-color: currentColor;
}
/* THE TREE: only the chapter being read shows its sub-headings.
   Every chapter's sub-list is built on the one-page view, because every
   chapter's headings are on that page — showing them all at once is the flat
   88-entry sidebar the `h1, h2` selector exists to avoid. On a chapter page only
   one sub-list can exist at all, and `is-expanded` is on it from the first paint.

   Keyed on the ITEM, not on a `:has()` or a sibling rule, so a browser that
   drops one selector does not decide the sidebar's shape. Without JavaScript no
   sub-list is built in the first place, so nothing here can hide anything a
   reader would otherwise have had. */
.guide-chapter-item > .guide-nav-sub { display: none; }
.guide-chapter-item.is-expanded > .guide-nav-sub { display: block; }

/* ACCENT, not muted, and this is the last of the same drift. `.guide-mode-link`
   was authored for `.site-topbar`, where it was a small secondary annotation and
   grey was right. `.download-btn` was authored as a button, where accent was its
   text and border colour. Both now sit side by side in the sticky header as a
   matched pair of quiet links — and unifying them matched size, weight, border,
   radius and decoration but missed COLOUR, so the pair rendered #555 beside
   #0b5394 at identical size and weight, which reads as an accident because it
   was one.

   Accent is the right side to converge on: in this header the drawer toggle is
   already accent, and body prose links are accent, so a grey control here reads
   as a label rather than something to press. The SIDEBAR keeps muted links on
   purpose — it is a dense list where forty accent-coloured entries would be a
   wall of blue, which is a different problem with a different answer. */
.guide-mode-link {
  font-size: 0.85rem;
  color: var(--accent, #0b5394);
  text-decoration: none;
  white-space: nowrap;
}
.guide-mode-link:hover { color: var(--accent, #0b5394); }

/* SPACE-BETWEEN so "previous" sits left and "next" right — and it still reads
   correctly on the first and last chapters, where there is only one link. */
.guide-pager {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  margin: 3rem 0 1rem;
  padding-top: 1rem;
  border-top: 1px solid var(--rule, #e3e3e3);
  font-size: 0.9rem;
}
.guide-pager a { text-decoration: none; color: var(--accent, #0b5394); }
.guide-pager a:hover { text-decoration: underline; }

"""


# A `<table>` that is NOT already immediately preceded by the breakout wrapper.
# The negative lookbehind makes the transform IDEMPOTENT: applying it twice
# cannot nest wrappers. That matters because the call site is one line in one
# function today, and a future `transforms.py` or a second pass would otherwise
# silently produce nested scroll containers — two focusable regions around one
# table, and a table inside a scroll box inside a scroll box.
_TABLE_OPEN_RE = re.compile(r'(?<!role="region">)<table(\s[^>]*)?>')

# An inline `<svg class="diagram">` gets the same breakout treatment as a table,
# and for the same reason: it is wide content that must not shrink to
# illegibility on a phone. A viewBox-sized SVG obeys `max-width: 100%`
# faithfully, which sounds right and is exactly the problem — a 700x186 drawing
# at a 358px phone measure renders its 13-unit labels at under 7px. Scrolling a
# readable drawing beats fitting an unreadable one.
_SVG_DIAGRAM_OPEN_RE = re.compile(
    r'(?<!role="region">)<svg(?=[^>]*\bclass="[^"]*\bdiagram\b)([^>]*)>'
)


_SVG_TITLE_ID_RE = re.compile(r"<title\b[^>]*\bid=\"([^\"]+)\"", re.I)


def _region_label(element_html: str, tag: str) -> str:
    """The accessible name for a scroll region, as an attribute string.

    `role="region"` with `tabindex="0"` makes the container focusable, and a
    focusable region with no name is announced as just "region" — the keyboard
    user reaches it and is told nothing about what they have landed on. A
    diagram already carries a `<title>`, so point at it; a table has no
    equivalent, so name the region for what it is.
    """
    if tag == "svg":
        m = _SVG_TITLE_ID_RE.search(element_html)
        if m:
            return f' aria-labelledby="{m.group(1)}"'
        return ' aria-label="Diagram, scrollable"'
    return ' aria-label="Table, scrollable"'


def _find_element_end(html: str, tag: str, open_match: "re.Match[str]") -> int | None:
    """Index just past `open_match`'s own closing tag, or None if there isn't one.

    Deliberately paranoid, because it decides where a `</div>` goes and a wrong
    answer produces silently unbalanced markup rather than an error:

    * A self-closing `<svg …/>` has no closing tag and ends at the match.
    * `<!-- … -->` is skipped wholesale. A comment containing `</svg>` is legal
      and would otherwise be mistaken for the real boundary, dropping the
      wrapper's close inside the comment and leaving the container open around
      the rest of the page.
    * Tag matching is case-insensitive; HTML does not care and neither may this.

    Returning None means "no clean boundary found", and the caller then leaves
    the element alone. Not wrapping is always safe; wrapping without a matching
    close is not.
    """
    if open_match.group(0).rstrip().endswith("/>"):
        return None  # self-closing: nothing to wrap around
    open_re = re.compile(rf"<{tag}(?=[\s/>])[^>]*>", re.I)
    close_re = re.compile(rf"</{tag}\s*>", re.I)
    depth = 1
    i = open_match.end()
    while i < len(html):
        c = html.find("<!--", i)
        o = open_re.search(html, i)
        m = close_re.search(html, i)
        if m is None:
            return None  # unbalanced source — leave it alone
        if c != -1 and c < m.start() and (o is None or c < o.start()):
            end = html.find("-->", c + 4)
            i = len(html) if end == -1 else end + 3
            continue
        if o is not None and o.start() < m.start():
            if not o.group(0).rstrip().endswith("/>"):
                depth += 1
            i = o.end()
            continue
        depth -= 1
        i = m.end()
        if depth == 0:
            return i
    return None


def _wrap_each(html: str, kinds) -> str:
    """Wrap each qualifying element in a `.wide-block` scroll container.

    ONE interleaved pass over all element kinds, not one pass per kind, and each
    wrapped element's whole extent is skipped. That is what stops a diagram
    inside a table cell from getting a scroll region of its own — two focusable
    scroll regions nested around one piece of content, which is the same defect
    the idempotence guard exists to prevent. Sequential per-kind passes cannot
    see that nesting, because by then the outer element is already wrapped and
    the inner one looks free-standing.

    The wrapper is emitted ONLY once the element's own closing tag has been
    located (see `_find_element_end`), never optimistically. The blanket
    `html.replace("</tag>", "</tag></div>")` this replaced was wrong in two ways
    that had not yet bitten: it appended a `</div>` for every closing tag in the
    document — including ones whose opening tag the guard had deliberately
    skipped, so a second pass emitted unbalanced markup — and a nested element of
    the same tag closed the wrapper early.
    """
    out: list[str] = []
    pos = 0
    existing = re.compile(r'<div class="wide-block"')
    while True:
        best = None
        for tag, open_re in kinds:
            m = open_re.search(html, pos)
            if m and (best is None or m.start() < best[1].start()):
                best = (tag, m)
        if best is None:
            out.append(html[pos:])
            return "".join(out)
        # An ALREADY-wrapped region is skipped whole. The open-tag lookbehind
        # only recognises an element sitting immediately inside a wrapper, so on
        # a second pass a diagram nested deeper — inside a wrapped table's cell —
        # looked free-standing and got a wrapper of its own. That is the nested
        # focusable scroll region this transform exists to avoid.
        w = existing.search(html, pos)
        if w and w.start() < best[1].start():
            close = _find_element_end(html, "div", re.compile(r"<div\b[^>]*>").match(html, w.start()))
            if close is not None:
                out.append(html[pos:close])
                pos = close
                continue
        tag, m = best
        end = _find_element_end(html, tag, m)
        if end is None:
            # No clean boundary: leave this element exactly as it was.
            out.append(html[pos:m.end()])
            pos = m.end()
            continue
        out.append(html[pos:m.start()])
        out.append(
            f'<div class="wide-block" tabindex="0" role="region"'
            f"{_region_label(html[m.start():end], tag)}>"
        )
        out.append(html[m.start():end])
        out.append("</div>")
        pos = end


def _wrap_wide_blocks(html: str) -> str:
    """Wrap every `<table>` in a scrollable breakout container (screen only).

    Pandoc emits a bare `<table>` with nowhere to hang `overflow-x`, and putting
    it on the table itself requires `display: block`, which discards table layout
    and so defeats the purpose. A wrapper is the only way to get "use more width,
    and scroll if that is still not enough" while keeping real table rendering.

    `tabindex="0"` is not decoration: a horizontally scrolling region is
    unreachable by keyboard without it, so a wide table would be readable with a
    mouse and not otherwise.

    Deliberately NOT applied to `pre`: those already scroll inside the prose
    measure, the widest code line in the family is 90 characters, and pulling
    code blocks out of the text column would break the read-along flow that the
    guides depend on.

    ALSO applied to `<svg class="diagram">`. A viewBox-sized SVG honours
    `max-width: 100%` perfectly, which is precisely why it needs this: honouring
    it at a 358px phone measure shrinks a 700-unit-wide drawing's labels to under
    7px. The same wrapper gives it "as wide as it needs, scroll if that is still
    too wide", so the drawing stays readable instead of staying fitted.
    """
    return _wrap_each(html, (("table", _TABLE_OPEN_RE), ("svg", _SVG_DIAGRAM_OPEN_RE)))


_COLGROUP_RE = re.compile(r"<colgroup>.*?</colgroup>", re.S)
# Pandoc's OTHER width hint, on the table itself: `<table style="width:100%;">`.
# Same artifact, same fix; it needs its own pattern because it is an attribute
# rather than an element. Only `width` is dropped — any other declaration the
# table carries is left alone, and an attribute left empty is removed entirely.
# Both quote styles: pandoc emits double, but a guide transform re-emitting a
# table has no reason to, and a rule that silently applies to one and not the
# other is the kind of difference nobody finds on purpose.
_TABLE_OPEN_STYLE_RE = re.compile(r"""(<table\b[^>]*?)\sstyle=(["'])([^"']*)\2""", re.I)
# `width` ONLY — not `min-width` or `max-width`. Pandoc emits plain `width`, and
# those two are how a guide deliberately CONSTRAINS a table. Stripping them would
# be this function overruling the guide rather than cleaning up after pandoc.
_WIDTH_DECL_RE = re.compile(r"(?:^|;)\s*width\s*:[^;]*", re.I)


def _strip_table_width_attr(match: re.Match) -> str:
    quote = match.group(2)
    kept = _WIDTH_DECL_RE.sub("", match.group(3)).strip().strip(";").strip()
    return f"{match.group(1)} style={quote}{kept}{quote}" if kept else match.group(1)


def _strip_pandoc_colgroups(html: str) -> str:
    """Remove pandoc's table width hints from the SCREEN html.

    For a pipe table, pandoc measures how many dashes each column got in the
    markdown separator row and emits that ratio as inline percentages:

        <colgroup><col style="width: 50%"><col style="width: 50%"></colgroup>

    Three things follow, none of them wanted on screen. Percentage column widths
    resolve against the containing block, so the table fills the window however
    little is in it — that is how a git-guide table whose own max-content is
    994px rendered at 1519px. The ratio then dictates the columns, so a
    six-character column can be handed 40% of the page. And because the widths
    are INLINE they beat any stylesheet, which is why `table { width: auto }`
    looked like it was being ignored.

    The ratio is an artifact of how someone typed the separator row, not a design
    decision — it is not even stable, since reformatting the markdown changes it.
    Dropping it lets the auto table algorithm size each column from its content.

    Pandoc has a second way of saying the same thing, and missing it left one
    git-guide table at 1521px against an 877px max-content after the colgroups
    were gone: `<table style="width:100%;">` on the element itself. Also inline,
    also a hint rather than a decision, so it goes the same way.

    Web only, deliberately. The PDF renders onto a fixed page where a table
    spanning the text block is the right default, and style.css is built around
    that; this is exactly the kind of divergence the per-output split exists for.
    """
    return _TABLE_OPEN_STYLE_RE.sub(_strip_table_width_attr, _COLGROUP_RE.sub("", html))


def render_web_html() -> str:
    """Render the SCREEN HTML: pandoc → web transforms → wrap with
    style-screen.css. Used for the website output only."""
    # Strip BEFORE the guide's transforms, not after. This is cleanup of pandoc's
    # output, so it belongs next to pandoc; running it last meant it also erased
    # anything the guide's own transform had deliberately put on a table, and a
    # guide had no way to opt out of a step that ran after it.
    body = _wrap_wide_blocks(
        buildcore._apply_transforms(_strip_pandoc_colgroups(buildcore._pandoc_body()), "web")
    )
    # On the TRANSFORMED body, for the same reason the PDF renderer checks there:
    # a transform can inject CJK text, and the question is about what actually
    # reaches the page.
    buildcore.check_cjk_annotations(body)
    # Top chrome: the same download affordance as the footer, ABOVE the guide
    # text. Without it the only way to get the PDF is to scroll the entire
    # document — which on the longest guide in this family means ~50 pages of
    # scrolling to reach a link, so most readers never find it at all.
    #
    # `download` (on both this and the footer link) is what makes the button
    # actually download. Cloudflare serves these with `Content-Type:
    # application/pdf` and no `Content-Disposition`, so a plain link makes the
    # browser's built-in viewer take over and render the PDF in a tab instead —
    # which is not what a control labelled "Download as PDF" should do. The
    # attribute is honoured because the PDF is served same-origin with the page.
    # It is deliberately NOT done with a `Content-Disposition: attachment`
    # header, which would also force a download for someone who navigated to the
    # PDF URL directly and legitimately wanted to read it in the browser.
    # On a multipage guide the topbar also carries the switch to the chapter
    # view, and the chapter list is rendered SERVER-SIDE beneath it. WEB_NAV_JS
    # cannot supply that list: it reads the headings of the page it is on, which
    # is right for one page and useless across many.
    _cfg = kitconfig.load(buildcore.ROOT)
    _mode, _chapters_nav = "", ""
    if _cfg.outputs.site == "multipage":
        _chs = chapters.split(buildcore.SRC, chapter_level=_cfg.site.chapter_level)
        _mode = _mode_link(_chs, None)
        _chapters_nav = _chapter_nav(_chs, None)
    # A trailing `---` in guide.md is the PDF's separator between the body and
    # the colophon build.py appends there. The website appends no colophon — the
    # licence lives in the footer below, and that footer draws its own rule — so
    # on this output the authored rule has nothing to separate and lands directly
    # above the footer's, as two lines 51px apart. Measured in accounting-guide,
    # which is the only guide that ends this way today.
    #
    # Dropped HERE rather than styled away, because the duplication is this
    # renderer's own doing: it is the footer that adds the second line. A guide
    # with no trailing rule is untouched and keeps the footer's.
    #
    # THE STRIP RUNS BEFORE THE CHAPTER NAV IS APPENDED, and that ordering is the
    # whole correctness of it: the pattern is END-ANCHORED. Appending anything
    # after the authored body first — as this did — moves the trailing <hr> off
    # the end and the substitution silently matches nothing. It looked fixed
    # because the code was present; it had never once removed a rule.
    body = re.sub(r"(?:\s*<hr\s*/?>)+\s*$", "", body)
    # The chapter list goes AFTER the body, not before it. Rendered above, it sat
    # between the header and the document's own <h1>, so a reader arriving at the
    # guide met a table of contents before they met the guide. WEB_NAV_JS then
    # MOVES this node into the sidebar; server-rendering it here at the end is
    # what a reader without JavaScript gets.
    #
    # ON THIS VIEW ITS ENTRIES ARE IN-PAGE ANCHORS, not chapter URLs, so it no
    # longer doubles as the way INTO chapter mode — the header's view switch is.
    # That is the point rather than a cost: the whole document is on this page,
    # and a contents entry that loaded `/<slug>/` moved a reader who had chosen
    # one page into the other mode without being asked to.
    body = _topbar(_mode, f'{buildcore.OUTPUT_SLUG}.pdf') + body + _chapters_nav
    # Footer chrome: the license/copyright (so the website carries the same terms
    # as the PDF) and the version stamp (which build the live site came from).
    #
    # NO DOWNLOAD LINK HERE. There was one, and it was redundant twice over: the
    # sticky header carries the same control on every page and at every scroll
    # position, and this copy only ever existed on the ONE-PAGE view — the forty
    # chapter pages had no footer download at all, so it was not even the
    # consistent fallback it looked like. Two copies of one control is also what
    # let them drift into two different appearances in the first place. One
    # control, one place, present everywhere.
    body += (
        '<footer class="site-footer">'
        f'<p>{buildcore.COPYRIGHT} · Licensed under '
        f'<a href="{buildcore.LICENSE_CONTENT_URL}">{buildcore.LICENSE_CONTENT_NAME}</a>; '
        f'build tooling under <a href="{buildcore.LICENSE_CODE_URL}">{buildcore.LICENSE_CODE_NAME}</a>.</p>'
        f'<p class="stamp">{buildcore.TITLE} · {buildcore._version_stamp("site")}</p>'
        '</footer>'
    )
    # Navigation-only progressive enhancement, WEB ONLY. Appended after the
    # body so the document is complete before it runs, and so a reader without
    # JavaScript gets exactly the page they get today.
    body += f"<script>{WEB_NAV_JS}</script>"
    css = buildcore.theme_css(
        "screen", WEB_CHROME_CSS + STYLE_SCREEN.read_text(encoding="utf-8"))
    # The SAME guard the PDF path runs. Without it a screen-only override could
    # name a host family and deploy, while the print build rejected it — the
    # guard would be protecting the output nobody visits.
    buildcore.check_overrides(css)
    css = css.replace("__TITLE__", buildcore.TITLE).replace("__VERSION__", buildcore._version_stamp("site"))
    return buildcore._wrap_html(body, css, head_extra=_indexing_head(_cfg, ""))


def _indexing_head(cfg, path: str) -> str:
    """`rel="canonical"` or `noindex`, per `site.canonical`.

    Empty `canonical` means the guide has not declared where it is published, so
    the honest directive is `noindex`: a tree serving the same prose at `/` and
    at every chapter route would otherwise be asking search engines to pick a
    winner per guide, differently, with no input from us.

    With a base URL, each page is canonical for ITSELF. The overlap between `/`
    and the chapter set is real and accepted — `/` has to stay the whole document
    so no shared `#heading` link ever breaks — so this says which URL is the one
    for each piece of content rather than pretending there is no duplication."""
    base = (cfg.site.canonical or "").strip().rstrip("/")
    if not base:
        return '<meta name="robots" content="noindex">'
    if not re.match(r"^https?://[^\s\"'<>]+$", base):
        raise SystemExit(
            f"build.py --web: [site] canonical must be an absolute http(s) base "
            f"URL, got {cfg.site.canonical!r}. It is emitted into every page's "
            f"<head>, so a relative or malformed value would point every "
            f"canonical at the wrong place."
        )
    return f'<link rel="canonical" href="{html.escape(base + "/" + path, quote=True)}">'


def _heading_anchor(header) -> str:
    """The pandoc identifier of a Header block, or `""` when it has none.

    THE SLUG IS NOT THE ID and the two must not be conflated. A route slug is
    derived by `chapters.derive_slug`; the id on the rendered heading is pandoc's,
    and the two grammars disagree — pandoc keeps periods, underscores and hyphens
    and strips everything up to the first LETTER, while `derive_slug` collapses
    every run of non-alphanumerics and strips a leading ordinal only when it is
    punctuated. Measured against the pinned pandoc:

        heading                    id                      slug
        Node.js basics             node.js-basics          node-js-basics
        1984 and dystopia          and-dystopia            1984-and-dystopia
        Chapter 2 -- The Ledger    chapter-2----the-ledger chapter-2-the-ledger

    Guessing either from the other therefore yields a fragment that resolves to
    nothing, on exactly the headings whose punctuation is unusual — and it fails
    silently, because a dead `#fragment` scrolls nowhere rather than erroring.

    So the anchor is READ from the AST the renderer already holds, which is the
    same block that will carry the id in the emitted HTML."""
    if not isinstance(header, dict):
        return ""
    try:
        ident = header["c"][1][0]
    except (KeyError, IndexError, TypeError):
        return ""
    return ident if isinstance(ident, str) else ""


def _chapter_nav(chs, current_slug: str | None) -> str:
    """THE sidebar list, server-rendered — document structure, every page.

    This is the sidebar's TOP LEVEL. `WEB_NAV_JS` moves it into the panel and
    nests the current chapter's own sub-headings beneath its entry; it does not
    build a second list beside it. That was the arrangement this replaced, and
    the two lists could not be reconciled in the browser because neither source
    had both facts: `.guide-chapters` knows every chapter in the DOCUMENT and
    nothing about the page being viewed, while `querySelectorAll('h1[id],
    h2[id]')` knows the page and has no idea other chapters exist.

    Server-rendering the structural half is what settles it. The chapter set
    comes from the AST, so it is complete on a chapter page — where the browser
    can see exactly one chapter — and the ids needed to nest under it come from
    the same blocks.

    THE ENTRIES POINT SOMEWHERE DIFFERENT ON EACH VIEW, which is why the list
    says which view it is on rather than leaving it to be guessed:

    * one-page — every entry is an in-page anchor. The whole document is here, so
      a contents entry that navigated to `/<slug>/` would take a reader who had
      chosen one page and silently move them into chapter mode. Reaching chapter
      mode is what the header's view switch is for.
    * chapter page — entries are chapter URLs, except the current chapter's,
      which is an anchor to the heading already on the page for the same reason.
    """
    items = []
    for c in chs:
        # A PART LABELS THE GROUP BENEATH IT, and is not a link: it has no page,
        # so linking it would either 404 or point at the first chapter while
        # claiming to be the part. A plain `<li>` with no anchor says "heading of
        # a group" to a reader and to assistive technology alike.
        #
        # It carries its heading's id anyway, and that is not for linking: a part
        # heading is an `h1[id]` like any other, so without it the script would
        # meet an unrecognised heading between two chapters and file the part —
        # and its blurb — under whichever chapter happened to precede it. The
        # anchor is what lets the part CLOSE the open chapter, which is the same
        # rule `chapters.split()` applies to the document.
        if c.part is not None:
            part_anchor = _heading_anchor(c.part)
            part_attr = ""
            if part_anchor:
                part_attr = f' data-anchor="{html.escape(part_anchor, quote=True)}"'
            items.append(
                f'<li class="guide-chapter-part" role="presentation"{part_attr}>'
                f'{html.escape(chapters._inline_text(c.part["c"][2]))}</li>'
            )
        here = c.slug == current_slug
        anchor = _heading_anchor(c.header)
        if anchor and (current_slug is None or here):
            # THIS CHAPTER IS ON THIS PAGE, so the entry jumps rather than loads.
            href = "#" + anchor
        elif current_slug:
            href = "../" + c.slug + "/"
        else:
            # No id to jump to — an image-only heading can yield one. The chapter
            # URL still works, so the entry degrades to a page load rather than
            # to a fragment that resolves to nothing.
            href = c.slug + "/"
        cls = "guide-chapter-item is-current" if here else "guide-chapter-item"
        # HOISTED out of the f-string. Written inline it needed a backslash
        # inside a replacement field, which is PEP 701 — Python 3.12+ — while
        # `pixi.toml` declares a 3.11 floor. The lock happens to pin 3.14, so
        # nothing failed; a guide resolving the low end of the declared window
        # would have hit a SyntaxError on IMPORT, in a file the PDF build does
        # not even use. Latent, cheap to remove, and impossible to notice on the
        # machine it was written on.
        current_attr = ' aria-current="page"' if here else ""
        # EMITTED ON EVERY ENTRY, not only the ones whose heading is on this page.
        # The script matches headings against it, and a heading that matches no
        # entry is simply not a chapter — which is the answer it needs for the
        # part headings and the document title alike.
        anchor_attr = ""
        if anchor:
            anchor_attr = f' data-anchor="{html.escape(anchor, quote=True)}"'
        items.append(
            f'<li class="{cls}"{anchor_attr}>'
            f'<a href="{html.escape(href)}"'
            f'{current_attr}>{html.escape(c.title)}</a></li>'
        )
    view = "chapter" if current_slug else "onepage"
    return (f'<nav class="guide-chapters" data-view="{view}" aria-label="Chapters">'
            f'<ol class="guide-chapter-list">{"".join(items)}</ol></nav>')


def _topbar(mode_link: str, pdf_href: str) -> str:
    """The two top controls, server-rendered together in document order.

    ONE container for both, because WEB_NAV_JS moves both of them into the sticky
    header and `.site-topbar:empty` then collapses what is left. Before this they
    were separated by accident, not by design: the download link was moved into
    the header (to stop its styling drifting from the footer's copy) and the mode
    link simply was not part of that change, so of the two controls the one that
    survived scrolling was the one a reader needs LESS — switching one-page and
    chapter views is a decision made while reading, the download is decide-once
    and has a second copy in the footer.

    Emitting them here rather than building them in script keeps the no-JavaScript
    page complete; the move is enhancement, never construction."""
    return ('<div class="site-topbar">'
            f'{mode_link}'
            f'<a class="download-btn" href="{html.escape(pdf_href)}" download>'
            'Download as PDF</a>'
            '</div>')


def _mode_link(chs, current_slug: str | None) -> str:
    """The switch between the two views, as a plain link.

    A link and not a toggle: no client state, works without JavaScript, and both
    views stay one click apart from anywhere. Storing a preference would mean two
    readers seeing different things at one URL, which the canonical story cannot
    describe."""
    if current_slug is None:
        if not chs:
            return ""
        return (f'<a class="guide-mode-link" href="{html.escape(chs[0].slug)}/">'
                'Read by chapter</a>')
    return '<a class="guide-mode-link" href="../">Read as one page</a>'


def _heading_home(chs) -> dict:
    """heading id -> the slug of the chapter containing it.

    EVERY heading, not just chapter-level ones: an in-document link points at
    whatever the author linked to, which is usually a subsection."""
    home = {}

    def walk(node, slug):
        if isinstance(node, dict):
            if node.get("t") == "Header":
                ident = node["c"][1][0]
                if ident:
                    # Pandoc guarantees ids are unique within a document — it
                    # numbers duplicates (`setup`, `setup-1`) — so there is no
                    # last-writer-wins hazard here to guard against.
                    home.setdefault(ident, slug)
            for v in node.values():
                walk(v, slug)
        elif isinstance(node, list):
            for v in node:
                walk(v, slug)

    for ch in chs:
        # RECURSIVE: a heading inside a `<div class="callout">` is nested in the
        # AST and is just as linkable as a top-level one. Scanning only the top
        # level left those targets unmapped, so a link to one stayed a bare
        # `#anchor` and died on any other chapter's page.
        walk(([ch.header] if ch.header else []) + ch.blocks, ch.slug)
    return home


def _clear_chapter_dirs(chs) -> None:
    """Remove previously generated chapter directories before writing.

    A chapter renamed between builds leaves its old route on disk, and the old
    route stays deployable with obsolete content — nothing else would ever
    remove it. Only directories that look like generated chapter output are
    touched: one containing exactly `index.html` and nothing else."""
    keep = {c.slug for c in chs}
    if not WEB_DIR.exists():
        return
    for d in WEB_DIR.iterdir():
        if not d.is_dir() or d.name in keep or d.name in chapters.RESERVED_SLUGS:
            continue
        index = d / "index.html"
        # Ownership is proven by the MARKER this renderer writes, not inferred
        # from the directory looking generated. "Contains only index.html" also
        # describes a page somebody put there by hand, and deleting that would
        # be the build quietly discarding someone's work.
        if index.is_file() and CHAPTER_MARKER in index.read_text(encoding="utf-8"):
            shutil.rmtree(d)


def _write_chapter_pages(cfg) -> None:
    """Emit `/<slug>/index.html` for every chapter.

    Chapters are served from the ROOT — `/meet-git/`, not `/ch/meet-git/` — so
    every asset reference needs one `../`, which `_wrap_html`'s `asset_prefix`
    supplies. Getting that wrong 404s every font on every chapter page while the
    landing page stays perfect, which is exactly the sort of thing that ships."""
    chs = chapters.split(buildcore.SRC, chapter_level=cfg.site.chapter_level)
    if not chs:
        raise SystemExit(
            f"build.py --web: site = \"multipage\" but no chapters were found at "
            f"[site] chapter_level = {cfg.site.chapter_level}. Check the level "
            f"against the guide's real heading structure — git-guide, for one, "
            f"has zero `##` headings."
        )
    css = buildcore.theme_css(
        "screen", WEB_CHROME_CSS + STYLE_SCREEN.read_text(encoding="utf-8"))
    buildcore.check_overrides(css)
    css = css.replace("__TITLE__", buildcore.TITLE).replace(
        "__VERSION__", buildcore._version_stamp("site"))
    api = chapters.document(buildcore.SRC).get("pandoc-api-version")
    # Which chapter owns each heading id, so an in-document `#anchor` link can be
    # rewritten to point at the chapter that actually contains its target. The
    # family has ~100 of these (accounting 41, git 33, japan 26); left alone,
    # every one that crosses a chapter boundary becomes a dead anchor.
    home = _heading_home(chs)

    # Chapter directories are REPLACED, not merged into. A rename leaves the old
    # route on disk otherwise, and it stays deployable with obsolete content —
    # as does every route when a guide flips from multipage back to single.
    _clear_chapter_dirs(chs)

    for i, ch in enumerate(chs):
        # Transforms BEFORE _wrap_wide_blocks, matching the one-page path. A
        # guide transform that creates a table must have it wrapped; reversed,
        # the table renders bare and non-scrollable on chapter pages only.
        # THE PART OPENS THE PAGE, when this chapter is the first of one. A part
        # has no page of its own — it is a grouping, not content — so its heading
        # and blurb ride on the first chapter beneath it, which is where a book
        # puts them. Unattached they belonged to no chapter and to no front
        # matter, and the multipage view dropped them without a word.
        part_blocks = ([ch.part] if ch.part else []) + list(ch.part_blocks)
        header = _promote_to_h1(ch.header)
        body = _wrap_wide_blocks(buildcore._apply_transforms(
            _strip_pandoc_colgroups(
                chapters.blocks_to_html(
                    chapters.rebase(part_blocks
                                    + ([header] if header else [])
                                    + ch.blocks,
                                    ch.slug, home), api)),
            "web"))
        buildcore.check_cjk_annotations(body)
        prev_c = chs[i - 1] if i else None
        next_c = chs[i + 1] if i + 1 < len(chs) else None
        pager = []
        if prev_c:
            pager.append(f'<a class="prev" href="../{html.escape(prev_c.slug)}/">'
                         f'←&nbsp;{html.escape(prev_c.title)}</a>')
        if next_c:
            pager.append(f'<a class="next" href="../{html.escape(next_c.slug)}/">'
                         f'{html.escape(next_c.title)}&nbsp;→</a>')
        # The `---` that separated this chapter from the NEXT one in guide.md ends
        # up trailing the split chapter, where it separates the chapter from its
        # own pager — which already draws a rule. Same end-anchored strip the
        # one-page view runs, and for the same reason: the authored rule is
        # punctuation BETWEEN chapters, and this page has no next chapter on it.
        body = re.sub(r"(?:\s*<hr\s*/?>)+\s*$", "", body)
        page = (
            f'{CHAPTER_MARKER}'
            f'{_topbar(_mode_link(chs, ch.slug), f"../{buildcore.OUTPUT_SLUG}.pdf")}'
            # BELOW the body, not above it. Rendered above, this chapter list
            # sat between the topbar and the chapter's own <h1> — so every
            # chapter page opened with a table of contents instead of with the
            # chapter. It belongs with the pager: both answer "where do I go
            # next", and that question is asked at the END of a chapter.
            f'{body}'
            f'{_chapter_nav(chs, ch.slug)}'
            f'<nav class="guide-pager">{"".join(pager)}</nav>'
            '<footer class="site-footer">'
            f'<p>{buildcore.COPYRIGHT} · Licensed under '
            f'<a href="{buildcore.LICENSE_CONTENT_URL}">{buildcore.LICENSE_CONTENT_NAME}</a>.</p>'
            f'<p class="stamp">{buildcore.TITLE} · {buildcore._version_stamp("site")}</p>'
            '</footer>'
            # The same progressive enhancement the one-page view gets. Without
            # it a chapter page loses the sticky header, the sidebar and the
            # relocation of the two top controls.
            f'<script>{WEB_NAV_JS}</script>'
        )
        out_dir = WEB_DIR / ch.slug
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.html").write_text(
            buildcore._wrap_html(
                page, css,
                title=f"{ch.title} · {buildcore.TITLE}",
                head_extra=_indexing_head(cfg, f"{ch.slug}/"),
                asset_prefix="../"),
            encoding="utf-8")
    print(f"  WEB   ->  {len(chs)} chapter page(s) under {WEB_DIR}")


# Cloudflare Workers Free ceilings that GENERATED output can breach. Build-time
# gates, because every one of them fails at DEPLOY otherwise — after the change
# has already been committed and propagated.
# Written into every generated chapter page. It is how `_clear_chapter_dirs`
# PROVES a route is ours before removing it, rather than inferring ownership
# from the directory happening to contain only an index.html — which also
# describes a page someone added by hand.
CHAPTER_MARKER = "<!-- guide-kit:chapter -->"

CF_MAX_ASSET_FILES = 20_000
CF_MAX_FILE_BYTES = 25 * 1024 * 1024
CF_MAX_HEADER_RULES = 100
CF_MAX_HEADER_LINE = 2_000
CF_MAX_REDIRECTS_STATIC = 2_000
CF_MAX_REDIRECTS_DYNAMIC = 100
CF_MAX_REDIRECTS_TOTAL = 2_100
CF_MAX_REDIRECT_LINE = 1_000


def check_ceilings(web_dir: Path) -> None:
    """Refuse to ship a tree Cloudflare will reject.

    Multipage is what makes these reachable: one file per chapter turns a
    two-file site into an unbounded one, and the file COUNT is the ceiling a
    generator can walk into without anyone noticing.

    `_redirects` is gated even though nothing generates one. Route stability was
    given up, so the kit emits no redirects
    at all — but a guide may hand-write the file, and a limit that only exists
    while nobody uses the feature is not a limit."""
    # `_headers` and `_redirects` are CONTROL files: Cloudflare parses them and
    # does not serve them, so counting them against the asset quota would reject
    # a tree with exactly the permitted number of real assets.
    control = {cfadapter.HEADERS_FILENAME, "_redirects"}
    files = [p for p in web_dir.rglob("*")
             if p.is_file() and not (p.parent == web_dir and p.name in control)]
    if len(files) > CF_MAX_ASSET_FILES:
        raise SystemExit(
            f"build.py --web: {len(files)} static assets exceeds Cloudflare's "
            f"{CF_MAX_ASSET_FILES}-file limit per Worker version."
        )
    for p in files:
        size = p.stat().st_size
        if size > CF_MAX_FILE_BYTES:
            raise SystemExit(
                f"build.py --web: {p.relative_to(web_dir)} is {size:,} bytes, over "
                f"Cloudflare's {CF_MAX_FILE_BYTES:,}-byte per-file limit."
            )

    headers = web_dir / cfadapter.HEADERS_FILENAME
    if headers.exists():
        lines = [l for l in headers.read_text(encoding="utf-8").splitlines() if l.strip()]
        # A RULE is a path line; the indented lines under it are its headers.
        rules = [l for l in lines if not l.startswith((" ", "\t"))]
        if len(rules) > CF_MAX_HEADER_RULES:
            raise SystemExit(
                f"build.py --web: _headers has {len(rules)} rules, over "
                f"Cloudflare's {CF_MAX_HEADER_RULES}."
            )
        for l in lines:
            if len(l) > CF_MAX_HEADER_LINE:
                raise SystemExit(
                    f"build.py --web: a _headers line is {len(l)} chars, over "
                    f"Cloudflare's {CF_MAX_HEADER_LINE}."
                )

    redirects = web_dir / "_redirects"
    if redirects.exists():
        rules = [l.strip() for l in redirects.read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.lstrip().startswith("#")]
        for l in rules:
            if len(l) > CF_MAX_REDIRECT_LINE:
                raise SystemExit(
                    f"build.py --web: a _redirects rule is {len(l)} chars, over "
                    f"Cloudflare's {CF_MAX_REDIRECT_LINE}."
                )
        # Splat or :placeholder makes a rule DYNAMIC, and dynamic rules have a
        # ceiling twenty times lower — so the classification is what decides
        # which limit applies, and getting it wrong passes the wrong gate.
        # A placeholder is `:name` — a colon followed by an identifier — not any
        # colon. `/archive/12:30` is a perfectly ordinary static path, and
        # calling it dynamic tests it against a ceiling twenty times lower.
        dynamic = [l for l in rules
                   if "*" in l.split()[0] or re.search(r":[A-Za-z]\w*", l.split()[0])]
        static = [l for l in rules if l not in dynamic]
        if len(static) > CF_MAX_REDIRECTS_STATIC:
            raise SystemExit(f"build.py --web: {len(static)} static redirects, over "
                             f"Cloudflare's {CF_MAX_REDIRECTS_STATIC}.")
        if len(dynamic) > CF_MAX_REDIRECTS_DYNAMIC:
            raise SystemExit(f"build.py --web: {len(dynamic)} dynamic redirects, over "
                             f"Cloudflare's {CF_MAX_REDIRECTS_DYNAMIC}.")
        if len(rules) > CF_MAX_REDIRECTS_TOTAL:
            raise SystemExit(f"build.py --web: {len(rules)} redirects, over "
                             f"Cloudflare's {CF_MAX_REDIRECTS_TOTAL} total.")


def write_guide_json(cfg, web_dir: Path) -> Path:
    """`/guide.json` — the machine-readable manifest the hub consumes.

    Emitted for EVERY site shape, not just multipage: the hub reads it
    from guides that may still be `single`, and a manifest that only some guides
    publish is one the hub cannot rely on.

    Artifacts are reported only when they EXIST in the output tree. The rule is
    the same one `build_web` enforces for the PDF — a site must not advertise a
    download that 404s — and it is why this is written last, after everything
    else has been placed."""
    pdf = web_dir / f"{cfg.OUTPUT_SLUG}.pdf"
    chs = []
    if cfg.outputs.site == "multipage":
        chs = [{"slug": c.slug, "title": c.title}
               for c in chapters.split(buildcore.SRC,
                                       chapter_level=cfg.site.chapter_level)]
    manifest = {
        "schema": "https://guide-kit.dev/schema/guide.v1.json",
        "slug": cfg.OUTPUT_SLUG,
        "title": cfg.TITLE,
        "description": cfg.DESCRIPTION,
        "site": cfg.outputs.site,
        "canonical": cfg.site.canonical or None,
        "stamp": buildcore._version_stamp("site"),
        # `null`, not an omitted key: the hub's "romance-languages has no PDF"
        # rule is enforced by DATA, so absence has to be expressible.
        "pdf": pdf.name if pdf.exists() else None,
        "chapters": chs,
    }
    out = web_dir / "guide.json"
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    return out


def _publish_assets() -> int:
    """Copy the site's assets into the built tree.

    `build_web()` had NO asset-copy path at all, which is why `CLAUDE.md` warns
    that a `href="assets/…"` would resolve in the PDF (WeasyPrint gets the repo
    root as its base_url) and 404 on the site. Cloudflare serves `app/dist` and
    nothing else, so an asset that is not copied here does not exist.

    Both namespaces the site's closure names, flattened into one `assets/`
    directory so a single `![](assets/x.png)` in `guide.md` resolves in the PDF
    (against the repo root) and on the site (against the built tree). `print/` is
    NOT copied — it is not a site input, and shipping it would put bytes on the
    web that the site's own closure hash does not cover."""
    published = 0
    for source in (kitconfig.ASSET_SHARED_DIR, kitconfig.ASSET_WEB_DIR):
        src_dir = buildcore.ROOT / source
        if not src_dir.is_dir():
            continue
        for src in sorted(src_dir.rglob("*")):
            if not src.is_file() or src.is_symlink():
                continue
            dest = WEB_DIR / "assets" / src.relative_to(src_dir)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            published += 1
    if published:
        print(f"  WEB   ->  {published} asset file(s) under {WEB_DIR / 'assets'}")
    return published


def _publish_fonts() -> int:
    """Copy every face the screen cascade references into app/dist/.

    NOT optional, and not merely tidiness. `fontfaces.css` is part of the screen
    cascade, so the deployed CSS carries `url("fonts/vendor/…")` — and Cloudflare
    serves app/dist and NOTHING ELSE. Without this the site requests each face,
    gets a 404, and falls back to whatever the visitor's machine has: the exact
    host dependence the bundling removed from the PDF, reintroduced on the web by
    a deploy directory that was correct until the stylesheets started naming
    bundled families.

    Copied rather than symlinked because the directory is uploaded, and the URLs
    are resolved relative to the site root so the layout must match the repo's."""
    published = 0
    for face in kitconfig.font_files(buildcore.ROOT):
        rel = face.relative_to(buildcore.ROOT)
        dest = WEB_DIR / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(face, dest)
        published += 1
    faces_css = buildcore.ROOT / "fontfaces.css"
    if faces_css.is_file():
        # The declarations travel too: the site's CSS is inlined, but a future
        # split into a linked stylesheet would need them at the same path.
        shutil.copyfile(faces_css, WEB_DIR / "fontfaces.css")
    print(f"  WEB   ->  {published} font file(s) under {WEB_DIR / kitconfig.FONT_DIR}")
    return published


def _check_wrangler_is_current() -> None:
    """Refuse to build a site whose deploy config disagrees with `guide.toml`.

    `app/wrangler.jsonc` is generated (`make wrangler`) and target-owned, so
    nothing overwrites a stale one. Without this, editing `[deploy] domain` and
    pushing would deploy with the OLD routes block and the old `workers_dev` —
    silently, because every other check would still pass.

    Absent is not an error: a guide with no web layer materialized yet has no
    `app/` at all, and `build_web` no-ops long before this for a PDF-only guide."""
    path = buildcore.ROOT / "app" / cfadapter.WRANGLER_FILENAME
    if not path.exists():
        return
    expected = cfadapter.render_wrangler_jsonc(kitconfig.load())
    if path.read_text(encoding="utf-8") != expected:
        raise SystemExit(
            f"build.py --web: {path.name} is out of date with guide.toml. It is "
            f"generated, not hand-maintained — run `make wrangler` and commit the "
            f"result. Building now would deploy the stale routes/workers_dev."
        )


def check_screen_styling() -> None:
    """Every class the guide AUTHORS and the PRINT sheet styles must be handled
    on screen too.

    WHY THIS EXISTS. `style-screen.css` is materialised from the kit's seed, and
    the seed cannot know a guide's own class names. So a guide that authors its
    own markup gets those classes styled in `style.css` — where it was working on
    the PDF — and nothing on the web. Both outputs build, both tests pass, and
    the website silently renders that markup as plain body text.

    Measured when this was written: git-guide, the most customised of the seven,
    had FIVE such classes across 165 elements — `.cover` (its whole title block,
    collapsed into left-aligned paragraphs), `.part-divider` (eight of them,
    indistinguishable from prose), `.exercise .diff` and `.exercise .exlabel`
    (inline labels running into the sentence beside them) and `.callout.ai`. The
    other six guides had none, which is why nothing ever surfaced it.

    HARD FAILURE, not a warning. "Styled in print, absent from screen" is always
    a decision that has not been made: a class meant to be invisible on the web
    still needs a rule saying so — the kit's own `.page-break { display: none }`
    is exactly that. Leaving it implicit is what produced the defect.

    Checked against the GUIDE'S OWN screen sheet, not against the served
    stylesheet. Including the kit's chrome looked more correct and was measurably
    worse: it found four of the five, silently passing `.cover` because
    WEB_CHROME_CSS names `.cover h1` — as a scroll-timeline hook for the running
    title, not as anything that styles it. A class the kit merely MENTIONS is not
    a class the guide has dressed. If a guide authors a class in its own
    markdown, its own sheet is where the answer belongs; measured across all
    seven guides, the stricter rule reports no false positives.
    """
    if not STYLE_SCREEN.exists() or not buildcore.STYLE.exists():
        return
    markdown = buildcore.SRC.read_text(encoding="utf-8")
    screen = STYLE_SCREEN.read_text(encoding="utf-8")
    print_css = buildcore.STYLE.read_text(encoding="utf-8")

    authored: set[str] = set()
    for m in re.finditer(r'class="([^"]+)"', markdown):
        authored.update(m.group(1).split())

    def styled(css: str, cls: str) -> bool:
        # Word-boundary, so `.diff` does not match `.different` and `.ai` does
        # not match `.aiming`. A substring test reported this clean.
        return re.search(rf"\.{re.escape(cls)}\b", css) is not None

    missing = sorted(c for c in authored
                     if styled(print_css, c) and not styled(screen, c))
    if not missing:
        return
    counts = ", ".join(f"{c} ({markdown.count(c)} uses)" for c in missing)
    raise SystemExit(
        f"build.py --web: {len(missing)} class(es) this guide authors are styled "
        f"in style.css and NOT in style-screen.css, so the website renders them "
        f"as plain body text while the PDF looks right:\n"
        f"  {counts}\n"
        f"  Add a screen rule for each — or an explicit one that hides it "
        f"(`display: none`) if it is print-only furniture. Silence here is not a "
        f"decision, it is the defect."
    )


def build_web() -> None:
    """Build the website into app/dist/: the screen HTML as index.html and a
    copy of the committed reference PDF for download.

    The web layer is opt-in, and opting in is a DECLARATION — `[outputs] site` —
    not the presence of a file. This no-ops cleanly on a guide that declares no
    site: it prints a hint, creates nothing, and exits 0 so `make web` is safe on
    every fork.

    It used to key on `style-screen.css` existing, which answers a different
    question. The stylesheet is target-owned (`never` in the manifest), so
    disabling a site correctly leaves it behind — and this then rendered a site
    the guide had just switched off, failing on the `[artifacts.site]` table that
    was removed along with the declaration."""
    cfg = kitconfig.load(buildcore.ROOT)
    if "site" not in cfg.outputs.declared:
        print('  web layer not declared — set `site` in [outputs] (e.g. "single") '
              "and add an [artifacts.site] table to enable it")
        return
    shape = cfg.outputs.site
    if shape not in kitconfig.IMPLEMENTED_SITE_SHAPES:
        raise SystemExit(
            f'build.py --web: [outputs] site = "{shape}" is a DECLARED shape that this '
            f"renderer does not implement yet (implemented: "
            f"{', '.join(kitconfig.IMPLEMENTED_SITE_SHAPES)}).\n"
            "  Refusing rather than rendering a single-page site under another shape's "
            "name — that is how a config value comes to mean nothing.\n"
            '  Use site = "single", or wait for the shape to land.'
        )
    if not STYLE_SCREEN.exists():
        raise SystemExit(
            "build.py --web: this guide declares a site but has no style-screen.css. "
            "Materialize the web layer with "
            "`adopt.py --target <guide> --output site --enable`."
        )

    # Hard-FAIL on a missing reference PDF BEFORE rendering, so no partial site is
    # written: a site must not deploy with a guaranteed-404 download link
    #. This is the compensating gate for the staleness check's
    # deliberate pass-with-notice on an absent PDF (verify_artifacts.py --staleness): a
    # never-released guide passes `make verify` but cannot build its web layer
    # until its first reference PDF exists.
    if not buildcore.REFERENCE_PDF.exists():
        raise SystemExit(
            f"build.py --web: reference PDF {buildcore.REFERENCE_PDF.name} is missing — the site's "
            "download link would 404. Generate it (`make release` / `make baseline` "
            "+ commit) before building or deploying the web layer."
        )

    # AFTER the reference-PDF gate, deliberately. Both are pre-render checks, but
    # a guide that has never released has no PDF and often no styling yet either;
    # reporting its missing artifact first is the message that tells it what to do
    # next. Running this first meant a brand-new guide was told about its
    # stylesheet while the real blocker was that it had nothing to ship.
    check_screen_styling()

    # The deploy config must match guide.toml BEFORE anything is built. This is
    # the only place the check runs in a TARGET's own CI: the kit's test suite
    # asserts the same thing, but `verify.yml` clones the kit alone, so those
    # cases skip and would enforce nothing where it matters. `make web` runs in
    # every guide's verify.yml AND immediately before `wrangler deploy` in its
    # deploy.yml, which is exactly the path a stale routes block would travel.
    _check_wrangler_is_current()

    WEB_DIR.mkdir(parents=True, exist_ok=True)
    out_index = WEB_DIR / "index.html"
    out_index.write_text(render_web_html(), encoding="utf-8")
    print(f"  WEB   ->  {out_index}")

    if cfg.outputs.site == "multipage":
        _write_chapter_pages(cfg)
    else:
        # A guide that LEFT multipage never reaches _write_chapter_pages, and its
        # old chapter routes would stay on disk and stay deployable. Cleanup is
        # therefore unconditional, with an empty keep-set.
        _clear_chapter_dirs([])

    # Copy the committed reference PDF (what readers download) — NOT a fresh
    # render — so the site links to the verified-by-baseline file.
    shutil.copyfile(buildcore.REFERENCE_PDF, WEB_DIR / buildcore.REFERENCE_PDF.name)
    print(f"  WEB   ->  {WEB_DIR / buildcore.REFERENCE_PDF.name}")

    _publish_fonts()
    _publish_assets()

    # Everything above this line is a PLAIN STATIC DIRECTORY that any host can
    # serve. What follows is the one provider-specific artifact, and it lives in
    # `cfadapter` so "which provider" is an import rather than a fact smeared
    # through the renderer. Its rationale — why a header and not the `download`
    # attribute, and the trade it accepts — moved with it, unchanged.
    headers = cfadapter.write_headers(WEB_DIR, buildcore.REFERENCE_PDF.name)
    print(f"  WEB   ->  {headers}")

    # LAST, so "does this artifact exist" is answered against the finished tree
    # rather than against what the build intended to place there.
    print(f"  WEB   ->  {write_guide_json(cfg, WEB_DIR)}")
    # Also last: the ceilings are properties of the COMPLETE tree, and the file
    # count in particular cannot be known until nothing more will be written.
    check_ceilings(WEB_DIR)


def _promote_to_h1(header):
    """The chapter's own Header block, at level 1, for its own page.

    At `chapter_level = 2` (accounting-guide) a chapter heading is an `<h2>`, and
    on a page that contains only that chapter it should be the `<h1>` — otherwise
    the page has no `h1` at all, which is bad for assistive technology and for
    search. The attr and the inlines are carried over untouched, so the id, the
    classes and any inline markup the author wrote all survive.

    DONE ON THE AST, and that is the fix rather than the style. It used to be two
    string operations on the rendered HTML — an anchored `re.sub` for the opening
    tag, then `body.replace("</h2>", "</h1>", 1)` for the closing one — and they
    could disagree, because only the first was anchored. On a chapter that OPENS
    A PART the body begins with the part's own `<h1 class="part">`, so the
    anchored pattern matched nothing while the unanchored replace went ahead and
    rewrote the chapter heading's closing tag anyway:

        <h2 id="what-accounting-actually-is">1. What accounting actually is</h1>

    Six of accounting-guide's 43 chapter pages shipped that, and it survived
    because browsers quietly discard the stray end tag and the page looks
    correct. Pandoc closes what it opens, so routing the change through the AST
    makes the two tags incapable of disagreeing.
    """
    if not isinstance(header, dict) or header.get("t") != "Header":
        return header
    level, attr, inlines = header["c"]
    if level == 1:
        return header
    # A NEW block rather than a mutation: `Chapter` is shared with the one-page
    # view and with `_heading_home`, and demoting the caller's copy would promote
    # the heading everywhere it is rendered.
    return {"t": "Header", "c": [1, attr, inlines]}
