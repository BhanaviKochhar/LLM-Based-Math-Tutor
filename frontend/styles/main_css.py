"""frontend/styles/main_css.py -- CSS for the main chat page (PAGE 3)."""
from __future__ import annotations

MAIN_CSS = """
<style>
/* ===========================================================================
   DESIGN TOKENS -- single source of truth for spacing/size/radius so every
   component reads as one coherent system instead of each having its own
   one-off value. Deliberately small (not a full design-system framework):
   just enough that "everything has its own random size" stops being true.
   =========================================================================== */
:root {
    --tt-radius-sm: 10px;
    --tt-radius-md: 14px;
    --tt-radius-lg: 18px;
    --tt-gap-xs: 6px;
    --tt-gap-sm: 10px;
    --tt-gap-md: 16px;
    --tt-gap-lg: 24px;
    --tt-card-pad: 14px;
    --tt-control-h: 44px;
    --tt-font-brand: 21px;
    --tt-font-h1: 16.5px;
    --tt-font-h2: 14.5px;
    --tt-font-body: 15.5px;
    --tt-font-small: 12.5px;
    --tt-font-xs: 11px;
    --tt-max-width: 1560px;
    /* Carries the illustrated-world artwork (sky band up top, grass band at
       the bottom; see _build_header_scene / _build_footer_scene) at about
       half the height of the first pass -- that first pass measured
       noticeably too tall ("occupying too much space vertically"). Every
       other rule that depends on these two tokens (page padding, the
       sticky side columns, the composer's offset) already reads from the
       SAME variable, so changing the value here is the only change needed
       -- no second magic number to keep in sync. */
    --tt-header-h: 60px;
    --tt-footer-h: 46px;
}

/* ===== THE WORLD, continued: same sky-to-grass gradient family as the
   onboarding page, so leaving the name page for the chat still feels like
   stepping through to the same place, not a different app. ===== */
.stApp, [data-testid="stAppViewContainer"], html, body {
    /* The sky-blue portion of the world lives IN the header band itself
       (see .tt-appbar below), which is fixed and always covers this
       gradient's top edge -- so what's actually visible here is the
       continuation of the onboarding gradient just past the sky: pale
       green fading to warm cream, the same "grassy meadow" stretch the
       onboarding card sits on. */
    background: linear-gradient(180deg, #eaf6ec 0%, #fbf3e3 60%, #fdf6e9 100%) !important;
    background-attachment: fixed !important;
}
/* Live-reported, confirmed on a real browser (not reproducible headless --
   an automated check of this page's own doc/body scrollHeight vs viewport
   innerHeight found them exactly equal): on a near-empty chat (just the
   greeting, no turns yet) the PAGE ITSELF still visibly dragged upward on
   a wheel/touchpad scroll, hiding the greeting and the History card's own
   title behind the fixed app bar, then springing back -- real Chromium's
   elastic "rubber-band" bounce, which it will render from even a
   sub-pixel amount of real overflow (100vh/calc() rounding, a reserved
   scrollbar gutter, font-metric differences from this environment's
   headless renderer) and visually exaggerates far past that real
   overflow distance. overscroll-behavior: none on the actual scrolling
   root suppresses that glow/bounce outright; it has no effect on any
   panel's real internal scrolling (chat_scroll etc. keep their own
   overscroll-behavior: contain below, for once content genuinely exceeds
   their height). */
.stApp, [data-testid="stAppViewContainer"], html, body {
    overscroll-behavior: none;
}
/* The ACTUAL element that was scrolling, found via a live DOM walk
   (reported scrollHeight/clientHeight for every overflowing node):
   [data-testid="stMain"] itself -- Streamlit gives it overflow:auto by
   default, as the one scrollable region for all non-fixed app content.
   That's exactly backwards for this layout: the three [History | Chat |
   Progress] panels already do their OWN internal scrolling (chat_scroll
   etc., each with real content-driven overflow once it's actually
   earned), so stMain is never SUPPOSED to need to scroll itself -- live
   measurement found it ~60px taller than its own box purely from
   calc()/box-model slop (padding/gap roundoff), not real content, which
   was enough for a touchpad gesture to drag the page up and hide the
   greeting/History title behind the fixed app bar. overflow:hidden here
   matches [data-testid="stAppViewContainer"]'s own default two lines
   below (already hidden, confirmed live not to clip the fixed composer)
   -- same treatment, same reasoning, one level deeper where the real
   scrollbar actually lived. */
[data-testid="stMain"] {
    overflow: hidden !important;
}
/* Unlike the onboarding page, this page's decorations live INSIDE the
   fixed header/footer bars, which each already clip their own children via
   their own `overflow: hidden` (see .tt-appbar / .tt-footer below) -- so,
   unlike onboarding, stAppViewContainer itself does NOT need an
   overflow:visible override here. Confirmed live that adding one anyway
   does active harm: it un-clips an unrelated oversized Streamlit-internal
   fixed element (reproduced with `st.toast` in play) that stAppViewContainer's
   default overflow:hidden was otherwise correctly hiding, which both painted
   a large stray shape over the composer AND pushed the Badges panel out of
   view. Left at the default (hidden). */

/* Page shell: centred with a capped max-width so a very wide monitor
   (1920px+) doesn't stretch the three-column layout disproportionately;
   top/bottom padding clear the fixed header/footer from shared tokens
   instead of an unrelated magic number. */
.block-container {
    max-width: var(--tt-max-width) !important; margin-left: auto !important; margin-right: auto !important;
    /* The +10px here (was +20px) is the gap below the header before the
       [History | Chat | Progress] row starts -- halved per the same "too
       much empty space" note as the header/footer height themselves. */
    padding: calc(var(--tt-header-h) + 10px) 20px calc(var(--tt-footer-h) + 86px) !important;
}
/* The visible gap above [History | Chat | Progress] was NOT actually
   coming from the padding above (confirmed live by walking the DOM) -- it
   was Streamlit's own 16px flex `gap` on the top-level vertical block,
   multiplied across the several invisible elements stacked ahead of the
   row (the two <style>-only st.markdown calls, the conditional welcome
   banner, the fixed/out-of-flow app bar): 4 gaps x 16px is most of the
   ~90px that was actually measured, dwarfing the explicit padding change
   above. None of those elements have visible in-flow content, so the gap
   between them buys nothing -- zeroed here, scoped to just the ONE
   top-level block (not every stVerticalBlock on the page, which would
   also flatten real spacing inside each column). */
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] { gap: 0 !important; }

[data-testid="stHorizontalBlock"] { align-items: flex-start !important; }
/* ONLY the top-level [History | Chat | Progress] row's side columns are
   sticky -- scoped via :has() to the specific row that contains the
   History panel, not every nested st.columns() row that happens to share
   the same generic stHorizontalBlock testid (a card's head/toggle row, the
   ask bar, a Yes/Cancel confirm row...), which the previous unscoped
   nth-of-type selector would otherwise also match. */
[data-testid="stHorizontalBlock"]:has([class*="st-key-history_panel"]) > [data-testid="column"]:nth-of-type(1),
[data-testid="stHorizontalBlock"]:has([class*="st-key-history_panel"]) > [data-testid="stColumn"]:nth-of-type(1),
[data-testid="stHorizontalBlock"]:has([class*="st-key-history_panel"]) > [data-testid="column"]:nth-of-type(3),
[data-testid="stHorizontalBlock"]:has([class*="st-key-history_panel"]) > [data-testid="stColumn"]:nth-of-type(3) {
    position: sticky !important; top: calc(var(--tt-header-h) + 10px) !important; align-self: flex-start !important;
}
/* The mobile stacking breakpoint used to be an EMERGENT side effect of
   flex-wrap: once [History | Chat | Progress] got too narrow to hold their
   own content, the browser wrapped them to a new line on its own.
   history_scroll/progress_scroll's own internal st.container(height=...)
   boxes quietly broke that: a flex item's AUTOMATIC min-width normally
   floors at its content's natural width (which is what drove the old
   emergent wrap), but a flex item that is ITSELF a scroll container
   (anything with overflow != visible, which is exactly what
   st.container(height=N) renders as) has its automatic minimum redefined
   by the flexbox spec as 0 instead -- confirmed live, the three panels
   just kept shrinking with no floor at all (button/radio labels wrapping
   one word per line) instead of ever wrapping to a new row. Rather than
   re-tune min-width numbers to approximate the old emergent behavior
   (tried first -- fragile and didn't reliably land on the same width
   twice), stacking is now driven explicitly by THIS SAME 700px breakpoint
   every other mobile rule in this file already keys off (the chat_scroll
   height drop, the composer's fixed->sticky switch, the order
   reassignment two rules below) -- nowrap above it, wrap exactly at and
   below it. One definition of "mobile" instead of two that can drift
   apart.

   nowrap alone isn't the whole fix, though -- confirmed live, it stops the
   STACKING regression but not the shrinking one: with no min-width floor
   at all now, the three columns just divide up whatever width is left
   between 701px and the 1024px tablet tier, which produced the exact same
   one-word-per-line wrapping this whole rule exists to prevent, just
   without the stacking. A min-width floor is still needed as a companion
   to nowrap -- just small enough that the three floors plus gaps can
   never exceed the narrowest row width nowrap actually has to cover
   (~669px at 701px viewport, confirmed live), so it can never force an
   overflow the way the earlier, bigger attempt (180/300/180) would have. */
[data-testid="stHorizontalBlock"]:has([class*="st-key-history_panel"]) { flex-wrap: nowrap !important; }
[data-testid="stHorizontalBlock"]:has([class*="st-key-history_panel"]) > [data-testid="column"]:nth-of-type(1),
[data-testid="stHorizontalBlock"]:has([class*="st-key-history_panel"]) > [data-testid="stColumn"]:nth-of-type(1),
[data-testid="stHorizontalBlock"]:has([class*="st-key-history_panel"]) > [data-testid="column"]:nth-of-type(3),
[data-testid="stHorizontalBlock"]:has([class*="st-key-history_panel"]) > [data-testid="stColumn"]:nth-of-type(3) {
    min-width: 140px !important;
}
[data-testid="stHorizontalBlock"]:has([class*="st-key-history_panel"]) > [data-testid="column"]:nth-of-type(2),
[data-testid="stHorizontalBlock"]:has([class*="st-key-history_panel"]) > [data-testid="stColumn"]:nth-of-type(2) {
    min-width: 220px !important;
}

/* Streamlit's default focus ring is red, clashing with this page's blue/
   gold theme -- the onboarding page already overrides this (gold ring) but
   that fix was scoped to its own inline <style>, so the SAME red ring was
   still showing here on the in-session grade picker and the ask box (U-10).
   Mirrors the onboarding page's override so focus looks consistent
   everywhere, not just on the first screen a child sees. */
div[data-testid="stSelectbox"] > div > div:focus-within,
div[data-testid="stTextInput"] > div:focus-within {
    border-color: #f5b301 !important; box-shadow: 0 0 0 3px rgba(245,179,1,0.35) !important;
    /* The glow is a box-shadow on this WRAPPER div, not on the (already
       rounded) input/combobox it wraps -- without its own matching radius
       the glow rendered as a sharp rectangle around a rounded field, a
       visible mismatch on the ask box in particular. */
    border-radius: var(--tt-radius-md) !important;
}

/* These rows (the History/Progress cards' headings + their collapse
   toggles; the ask box + its submit arrow) are always meant to read as one
   inline unit -- at narrow (phone-width) viewports Streamlit's own
   responsive layout stacks ANY st.columns() row vertically, which turned
   each toggle into a giant blank full-width bar below its heading and
   split the ask box from its submit button onto two separate full-width
   rows (U-01). Pin all of them back to a horizontal row with their
   original width ratio at every viewport, instead of depending on
   Streamlit's own breakpoint. */
[class*="st-key-history_panel"] [data-testid="stHorizontalBlock"],
[class*="st-key-progress_panel"] [data-testid="stHorizontalBlock"]:has([class*="st-key-toggle_progress"]),
[data-testid="stForm"] [data-testid="stHorizontalBlock"] {
    flex-direction: row !important; flex-wrap: nowrap !important;
}
[class*="st-key-history_panel"] [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-of-type(1),
[class*="st-key-history_panel"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-of-type(1),
[class*="st-key-progress_panel"] [data-testid="stHorizontalBlock"]:has([class*="st-key-toggle_progress"]) > [data-testid="column"]:nth-of-type(1),
[class*="st-key-progress_panel"] [data-testid="stHorizontalBlock"]:has([class*="st-key-toggle_progress"]) > [data-testid="stColumn"]:nth-of-type(1) {
    flex: 5 1 0 !important; width: auto !important; min-width: 0 !important;
}
[class*="st-key-history_panel"] [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-of-type(2),
[class*="st-key-history_panel"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-of-type(2),
[class*="st-key-progress_panel"] [data-testid="stHorizontalBlock"]:has([class*="st-key-toggle_progress"]) > [data-testid="column"]:nth-of-type(2),
[class*="st-key-progress_panel"] [data-testid="stHorizontalBlock"]:has([class*="st-key-toggle_progress"]) > [data-testid="stColumn"]:nth-of-type(2) {
    flex: 1 1 0 !important; width: auto !important; min-width: 0 !important;
}
[data-testid="stForm"] [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-of-type(1),
[data-testid="stForm"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-of-type(1) {
    flex: 6 1 0 !important; width: auto !important; min-width: 0 !important;
}
[data-testid="stForm"] [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-of-type(2),
[data-testid="stForm"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-of-type(2) {
    flex: 1 1 0 !important; width: auto !important; min-width: 0 !important;
}

/* The History/Progress collapse arrow reads as the right end of the SAME
   title bar now, not a separate white button floating beside it -- zero
   gap between the title and toggle columns, the toggle column gets the
   identical fill/bleed/corner-radius as .tt-card-head (which loses its
   own top-right rounding, since the toggle now owns that corner), and the
   actual <button> inside is painted fully transparent so the column's
   fill shows through it. See further down for the button's own color
   (blue, matching the ask bar's send arrow) and the "no color change on
   click" rules. */
[class*="st-key-history_panel"] [data-testid="stHorizontalBlock"],
[class*="st-key-progress_panel"] [data-testid="stHorizontalBlock"]:has([class*="st-key-toggle_progress"]) {
    gap: 0 !important;
}
[class*="st-key-history_panel"] [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-of-type(2),
[class*="st-key-history_panel"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-of-type(2),
[class*="st-key-progress_panel"] [data-testid="stHorizontalBlock"]:has([class*="st-key-toggle_progress"]) > [data-testid="column"]:nth-of-type(2),
[class*="st-key-progress_panel"] [data-testid="stHorizontalBlock"]:has([class*="st-key-toggle_progress"]) > [data-testid="stColumn"]:nth-of-type(2) {
    background: linear-gradient(180deg,#f5a623,#e08a1e) !important;
    border-radius: 0 var(--tt-radius-md) 0 0 !important;
    margin: calc(-1 * var(--tt-card-pad)) calc(-1 * var(--tt-card-pad)) 0 0 !important;
}

/* Chat/History/Progress scroll boxes fill the real leftover space down to
   the footer instead of stopping at an arbitrary vh fraction -- a flat
   min(56vh,540px) left a large dead gap between the card borders and the
   footer on anything taller than a laptop screen (live-reported: "a lot of
   space towards the bottom"), because the side cards are `position:sticky`
   (not stretched) and the ask bar is `position:fixed` (immune to document
   flow either way), so neither one grows to fill unused height on its own.
   Each box's formula is 100vh minus the header/footer bands (shared
   tokens, so this tracks the 1024px tier's smaller header/footer too)
   minus that column's OWN fixed chrome above/below the box -- confirmed
   live via DOM measurement at 900px and 760px viewport heights:
     History/Progress chrome = title bar + toggle row (67px above) + the
       card's own bottom padding (16px) + the 10px top gap under the appbar
       and a matching 14px gap held above the footer -- 107px total.
     Chat chrome = the "Hi! I'm Math Buddy" greeting block (77px, including
       its own gap) above, and the FIXED ask bar (44px tall, floating
       `--tt-footer-h + 14px` off the bottom) plus a 16px breathing gap
       above it -- 161px total.
   max() keeps a usable floor if this is ever embedded somewhere shorter
   than that chrome allows.

   TWO overrides are needed per box, not one -- confirmed live by walking
   the actual ancestor chain in devtools. st.container(height=N) renders as
   a `stVerticalBlock` with `flex: 1 1 0%` (it WOULD happily grow/shrink to
   fill whatever space its parent gives it) wrapped in a `stLayoutWrapper`
   that instead carries `flex: 0 0 430px` -- a flex-basis with grow/shrink
   both zeroed, which fully determines the box's rendered size and makes
   `height` on the inner block moot no matter what it's set to. Overriding
   only the inner block (the first attempt here) changed nothing live,
   because the OUTER wrapper's fixed flex-basis was still the thing
   actually sizing the box. The outer wrapper's own class is a per-render
   emotion-cache hash with no stable hook, so :has() reaches it indirectly
   via the one child class we DO control. (The doubled attribute selector
   on the inner block is a second, separate fix: Streamlit's height:430px
   rule on that element has the same specificity as a plain `[class*=...]`
   selector, and with both sides `!important` a tie falls back to cascade
   order, which Streamlit's own re-injected-every-rerun rule was winning --
   belt-and-suspenders now that the real fix is the wrapper's flex-basis.) */
[data-testid="stLayoutWrapper"]:has(> [class*="st-key-history_scroll"]),
[data-testid="stLayoutWrapper"]:has(> [class*="st-key-progress_scroll"]) {
    flex: 0 0 max(320px, calc(100vh - var(--tt-header-h) - var(--tt-footer-h) - 107px)) !important;
}
[data-testid="stLayoutWrapper"]:has(> [class*="st-key-chat_scroll"]) {
    flex: 0 0 max(280px, calc(100vh - var(--tt-header-h) - var(--tt-footer-h) - 161px)) !important;
}
[class*="st-key-history_scroll"][class*="st-key-history_scroll"],
[class*="st-key-progress_scroll"][class*="st-key-progress_scroll"] {
    height: max(320px, calc(100vh - var(--tt-header-h) - var(--tt-footer-h) - 107px)) !important;
}
[class*="st-key-chat_scroll"][class*="st-key-chat_scroll"] {
    height: max(280px, calc(100vh - var(--tt-header-h) - var(--tt-footer-h) - 161px)) !important;
}

/* Live-reported: on a near-empty chat (just the greeting, no turns yet),
   mouse-wheel/touchpad scroll over these columns still visibly dragged
   their content up before snapping back -- the browser's elastic
   "rubber-band" overscroll glow on an overflow:auto box, which Chromium
   renders even when scrollHeight == clientHeight and there's nothing to
   actually scroll. overscroll-behavior: contain stops that glow (and
   stops the scroll gesture from chaining to the page behind it) without
   touching the real scrolling these columns need once content genuinely
   exceeds their height. */
[class*="st-key-chat_scroll"], [class*="st-key-history_scroll"], [class*="st-key-progress_scroll"] {
    overscroll-behavior: contain;
}

/* Thin scrollbar that's essentially invisible at rest and appears only
   while the pointer is actually over that column (the closest a pure-CSS,
   no-JS rule can get to "appears while scrolling, disappears otherwise" --
   a true scroll-only trigger needs a scroll-event listener, which felt like
   overkill for a cosmetic nicety). Firefox uses scrollbar-color; WebKit/
   Blink (Chrome, Edge, Safari) use the ::-webkit-scrollbar family. */
[class*="st-key-chat_scroll"], [class*="st-key-history_scroll"], [class*="st-key-progress_scroll"] {
    scrollbar-width: thin; scrollbar-color: transparent transparent;
    transition: scrollbar-color .2s ease;
}
[class*="st-key-chat_scroll"]:hover, [class*="st-key-history_scroll"]:hover, [class*="st-key-progress_scroll"]:hover,
[class*="st-key-chat_scroll"]:focus-within, [class*="st-key-history_scroll"]:focus-within, [class*="st-key-progress_scroll"]:focus-within {
    scrollbar-color: rgba(154,91,18,0.4) transparent;
}
[class*="st-key-chat_scroll"]::-webkit-scrollbar, [class*="st-key-history_scroll"]::-webkit-scrollbar, [class*="st-key-progress_scroll"]::-webkit-scrollbar {
    width: 6px;
}
[class*="st-key-chat_scroll"]::-webkit-scrollbar-thumb, [class*="st-key-history_scroll"]::-webkit-scrollbar-thumb, [class*="st-key-progress_scroll"]::-webkit-scrollbar-thumb {
    background: transparent; border-radius: 999px; transition: background .2s ease;
}
[class*="st-key-chat_scroll"]:hover::-webkit-scrollbar-thumb, [class*="st-key-history_scroll"]:hover::-webkit-scrollbar-thumb, [class*="st-key-progress_scroll"]:hover::-webkit-scrollbar-thumb {
    background: rgba(154,91,18,0.35);
}

/* Sticky "current question" header inside the chat scroll box -- each
   question bubble sticks to the top of the box while its own answer is
   scrolled past, then gets pushed up by the NEXT question once ITS pair
   reaches the top (the standard CSS-only "sticky section header" pattern:
   no JS, it falls out of this for free as long as nothing between the
   sticky element and its scrolling ancestor clips or scrolls on its own).
   Plain <div>, not a link -- it WAS a self-linking <a href="#its-own-id">
   so clicking it jumped back to that pair's top, but live-reported that
   made the question text unselectable: clicking-and-dragging to copy what
   you'd typed triggered the browser's link-click/navigation behavior
   instead of a text selection. Being able to copy the question back out
   matters more than the click-to-jump shortcut. */
.tt-q-sticky {
    position: sticky; top: 0; z-index: 5;
    color: #111 !important;
}

/* ===========================================================================
   RESPONSIVE BREAKPOINTS -- real media queries (not just clamp()), chosen
   from live-verified behavior rather than guessed round numbers:
   1024px  tablet / small laptop -- tighten outer gutters a little.
   700px   Streamlit's OWN column-stacking breakpoint (confirmed live) --
           [History | Chat | Progress] stacks vertically from here down.
   480px   phone -- compact the chrome further.
   =========================================================================== */
@media (max-width: 1024px) {
    .block-container { padding-left: 16px !important; padding-right: 16px !important; }
    :root { --tt-header-h: 50px; --tt-footer-h: 40px; }
    /* Same "desktop-only decoration" convention as the onboarding scene's
       own tt-hide-md -- the header/footer trees and far cloud are the first
       to go once there isn't much width to spare. */
    .tt-hide-md { display: none !important; }
}

@media (max-width: 700px) {
    /* This IS the stacking breakpoint now (see the nowrap rule above) --
       the three panels go from side-by-side to stacked top-to-bottom here.
       Previously that meant History (authored first, so DOM-first) always
       rendered above the chat, burying the actual tutor several screens
       down on a short phone no matter how short History's own content was.
       Reordering visually (not touching DOM/session-state) makes the chat
       the first thing reached, with History and Progress following below
       -- a layout-relationship fix per U-01's lesson, not another padding
       patch. */
    [data-testid="stHorizontalBlock"]:has([class*="st-key-history_panel"]) { flex-wrap: wrap !important; }
    [data-testid="stHorizontalBlock"]:has([class*="st-key-history_panel"]) > [data-testid="column"]:nth-of-type(1),
    [data-testid="stHorizontalBlock"]:has([class*="st-key-history_panel"]) > [data-testid="stColumn"]:nth-of-type(1) { order: 2; }
    [data-testid="stHorizontalBlock"]:has([class*="st-key-history_panel"]) > [data-testid="column"]:nth-of-type(2),
    [data-testid="stHorizontalBlock"]:has([class*="st-key-history_panel"]) > [data-testid="stColumn"]:nth-of-type(2) { order: 1; }
    [data-testid="stHorizontalBlock"]:has([class*="st-key-history_panel"]) > [data-testid="column"]:nth-of-type(3),
    [data-testid="stHorizontalBlock"]:has([class*="st-key-history_panel"]) > [data-testid="stColumn"]:nth-of-type(3) { order: 3; }

    /* Bottom padding only needs to clear the fixed FOOTER now -- the
       composer switches to position:sticky just below (not fixed), so it
       already reserves its own normal-flow space instead of needing the
       page to pad around it. */
    .block-container { padding: calc(var(--tt-header-h) + 6px) 12px calc(var(--tt-footer-h) + 16px) !important; }
    [data-testid="stLayoutWrapper"]:has(> [class*="st-key-chat_scroll"]), [data-testid="stLayoutWrapper"]:has(> [class*="st-key-history_scroll"]), [data-testid="stLayoutWrapper"]:has(> [class*="st-key-progress_scroll"]) { flex: 0 0 min(44vh, 420px) !important; }
    [class*="st-key-chat_scroll"][class*="st-key-chat_scroll"], [class*="st-key-history_scroll"][class*="st-key-history_scroll"], [class*="st-key-progress_scroll"][class*="st-key-progress_scroll"] { height: min(44vh, 420px) !important; }
    .tt-card-head { font-size: var(--tt-font-h2) !important; padding: 9px var(--tt-card-pad) !important; }
    :root { --tt-header-h: 44px; --tt-footer-h: 36px; }
    .tt-hide-sm { display: none !important; }
}

@media (max-width: 480px) {
    /* The composer is sticky (not fixed) below 700px -- see that rule --
       so it already reserves its own normal-flow space; the page only
       needs to clear the one remaining fixed element, the footer. */
    .block-container { padding-bottom: calc(var(--tt-footer-h) + 16px) !important; }
    [data-testid="stLayoutWrapper"]:has(> [class*="st-key-chat_scroll"]), [data-testid="stLayoutWrapper"]:has(> [class*="st-key-history_scroll"]), [data-testid="stLayoutWrapper"]:has(> [class*="st-key-progress_scroll"]) { flex: 0 0 min(38vh, 360px) !important; }
    [class*="st-key-chat_scroll"][class*="st-key-chat_scroll"], [class*="st-key-history_scroll"][class*="st-key-history_scroll"], [class*="st-key-progress_scroll"][class*="st-key-progress_scroll"] { height: min(38vh, 360px) !important; }
    :root { --tt-header-h: 38px; --tt-footer-h: 32px; }
}

/* App bar — fixed across the top. Previously 16px/34px padding + a 26px
   brand made the bar the single biggest visual contributor to the "things
   feel oversized" impression (it set the scale everything else was then
   measured against). Tightened to a clear, compact app-bar height using
   the shared token so .block-container's top offset / the sticky columns'
   top offset above can reference the SAME number instead of a second,
   unrelated magic constant. */
.tt-appbar {
    position: fixed; top: 0; left: 0; right: 0; z-index: 1000;
    /* Grid (not flex space-between) so the brand can sit TRULY centered --
       flex space-between only centers the middle item when both side items
       happen to be equal width, which broke the moment the star pill was
       removed from the right side and left it lighter than the (empty)
       left side. Two equal 1fr edge columns guarantee the center column is
       the bar's actual center regardless of what either side holds. */
    display:grid; grid-template-columns: 1fr auto 1fr; align-items:center;
    /* Sky-band artwork (see _build_header_scene) paints as absolutely-
       positioned children of this SAME element -- position:fixed already
       makes it a positioned ancestor, so no extra wrapper is needed. They
       sit first in the DOM (painted first = underneath) with the brand/
       bar-right content after, same "DOM order, no z-index" trick the
       onboarding card uses to stay above its own scene. overflow:hidden
       keeps the hill silhouette / trees from poking out past the bar's own
       rounded bottom corners. Position:absolute children are taken out of
       flow and don't participate in the grid, so they don't disturb it. */
    overflow: hidden;
    /* Richer/deeper sky than the pale version this started as -- NOT navy,
       just a more saturated, more confident blue the header can own as its
       own color rather than reading as a washed-out tint. */
    background: linear-gradient(180deg, #2f74c9 0%, #5fa3e0 100%);
    margin: 0; border-radius: 0 0 var(--tt-radius-lg) var(--tt-radius-lg);
    min-height: var(--tt-header-h); box-sizing: border-box;
    padding: 6px 20px; box-shadow:0 6px 18px rgba(47,77,128,0.22);
}
.tt-h-sun, .tt-h-cloud, .tt-h-bird, .tt-h-tree, .tt-h-hill { position: absolute; }
.tt-brand { grid-column: 2; justify-self: center; position:relative; font-family:'Baloo 2',sans-serif; font-weight:700; font-size:18px; color:#fff; white-space:nowrap; text-shadow:0 1px 4px rgba(47,77,128,0.35); }
.tt-brand .y { color:#ffd23f; }
.tt-bar-right { grid-column: 3; justify-self: end; position:relative; display:flex; align-items:center; gap:10px; min-width:0; }
.tt-user { color:#fff; font-weight:800; font-size:13px; display:flex; align-items:center; gap:7px; min-width:0; text-shadow:0 1px 4px rgba(47,77,128,0.35); }
/* A long typed name must never stretch/break the header -- truncate with
   an ellipsis rather than wrapping or overflowing (rule 4: "responsive to
   long student names"). */
.tt-user .name { max-width: 150px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.tt-user .av { width:24px;height:24px;border-radius:50%;background:#ffd23f;color:#2f4d80;display:inline-flex;align-items:center;justify-content:center;font-weight:800;font-family:'Baloo 2',sans-serif;font-size:12px;flex-shrink:0; }
/* Log out (logged-in parents only). The bar is plain HTML, so the real
   Streamlit button is pinned into its right end from outside, and the name
   chip moves left to make room for it. */
.tt-bar-right.with-logout { padding-right: 84px; }
[class*="st-key-logout_btn"] {
    position: fixed !important; top: 15px; right: 20px; z-index: 1001; width: auto !important;
}
[class*="st-key-logout_btn"] button {
    min-height: 0 !important; height: 30px; padding: 0 12px !important; border-radius: 999px !important;
    background: rgba(255,255,255,0.16) !important; border: 1.5px solid rgba(255,255,255,0.8) !important;
}
[class*="st-key-logout_btn"] button p { color:#fff !important; font-weight:800 !important; font-size:12px !important; }
[class*="st-key-logout_btn"] button:hover { background: rgba(255,255,255,0.3) !important; }
@media (max-width: 480px) {
    /* Not a horizontal squeeze of the same elements -- the name's
       max-width shrinks too so the bar stays a compact, single-row strip
       instead of visually straining at phone width (rule 4: "do NOT simply
       compress the desktop header horizontally until it breaks"). */
    .tt-appbar { padding: 4px 12px; border-radius: 0 0 14px 14px; }
    .tt-brand { font-size: 15px; }
    .tt-user { font-size: 12px; }
    .tt-user .name { max-width: 72px; }
    .tt-bar-right.with-logout { padding-right: 66px; }
    [class*="st-key-logout_btn"] { top: 6px; right: 10px; }
    [class*="st-key-logout_btn"] button { height: 26px; padding: 0 9px !important; }
    [class*="st-key-logout_btn"] button p { font-size: 11px !important; }
}

/* Cards -- one shared padding/radius token so every bordered surface in the
   app (history, progress, badges, each chat turn) reads as the same kind
   of "card", not a collection of individually-tuned boxes. Shadow lightened
   (was a fairly heavy 22px/0.10 blur) since many cards now sit close
   together and heavy shadows on every one of them was a real contributor
   to the "card within card" bulkiness called out in the visual pass. */
div[data-testid="stVerticalBlockBorderWrapper"] {
    background:#fffaf0 !important; border:1px solid #f3deb0 !important; border-radius:var(--tt-radius-md) !important;
    box-shadow:0 2px 8px rgba(224,138,30,0.08) !important; padding:var(--tt-card-pad) !important;
    margin-bottom:var(--tt-gap-sm) !important;
}
/* Gold "wood plank" tab, the same material language as the onboarding
   world's signposts/math-sign props -- replaces the old flat blue bar. */
.tt-card-head {
    margin:calc(var(--tt-card-pad) * -1) calc(var(--tt-card-pad) * -1) var(--tt-gap-sm) calc(var(--tt-card-pad) * -1) !important;
    padding:10px var(--tt-card-pad) !important;
    border-radius:var(--tt-radius-md) var(--tt-radius-md) 0 0 !important;
    background:linear-gradient(180deg,#f5a623,#e08a1e); color:#fff; font-family:'Baloo 2',sans-serif; font-weight:700; font-size:var(--tt-font-h1);
    /* Pinned to the SAME explicit pixel line-height as the toggle button
       beside it (see [class*="st-key-toggle_history"] button below) --
       both have identical 10px top/bottom padding, but without this they
       each fall back to the browser's default ~1.6x line-height for their
       OWN font-size (16.5px here vs the button's larger 18px/800-weight
       glyph), which doesn't cancel out even as a ratio: 16.5*1.6=26.4 vs
       18*1.6=28.8, a ~2.4px mismatch. That let the taller button's gold
       fill poke out past the title bar's bottom edge (live-reported: "not
       of same height... there's an overflow"). A shared literal px value
       is the only thing guaranteed equal regardless of either element's
       font-size. */
    line-height:20px;
}
/* History/Progress's title bar has a toggle arrow attached to its right
   edge (the column rule above) -- it owns the top-right corner instead, so
   this modifier drops both the bar's own rounding there AND its
   right-bleed (which would otherwise reach a few pixels past where the
   toggle column now begins). Badges' bar has no toggle and keeps the
   plain, fully-rounded .tt-card-head above. */
.tt-card-head.tt-card-head-with-toggle {
    margin-right: 0 !important;
    border-radius: var(--tt-radius-md) 0 0 0 !important;
}

/* ===== SIDE PANELS — cream/gold storybook cards, reliably targeted via
   container key, not :has() ===== */
[class*="st-key-history_panel"],
[class*="st-key-progress_panel"],
[class*="st-key-badges_panel"] {
    background: #fffaf0 !important;
    border-radius: var(--tt-radius-md) !important;
    border: 1px solid #f3deb0 !important;
    box-shadow: 0 4px 14px rgba(224,138,30,0.12) !important;
}
[class*="st-key-history_panel"] div[data-testid="stVerticalBlockBorderWrapper"],
[class*="st-key-progress_panel"] div[data-testid="stVerticalBlockBorderWrapper"],
[class*="st-key-badges_panel"] div[data-testid="stVerticalBlockBorderWrapper"] {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}
/* readable text on the now-cream panels (navy/gold, matching the
   onboarding card's own title/value colors; was white/gold-on-blue) */
.tt-prog-row { color:#2f4d80 !important; }
.tt-prog-row .val { color:#e08a1e !important; }
.tt-badge .lbl { color:#2f4d80 !important; }
[class*="st-key-hist_view"] label,
[class*="st-key-hist_view"] label p,
[class*="st-key-hist_view"] label div { color:#2f4d80 !important; font-weight:700 !important; font-size:13.5px !important; }
.stProgress > div > div { background: #f3deb0 !important; }
.stProgress > div > div > div { background: #f5a623 !important; }

/* History/Progress collapse toggle -- the actual <button> is painted fully
   transparent (its column already carries the gold fill, see above) with a
   blue triangle, the same blue as the ask bar's send arrow (#2f6bea), so it
   reads as a disclosure control on the title bar rather than its own
   widget. Collapsed state has no sibling title bar to attach to (it's the
   only thing left in the card), so it keeps the gold fill and full corner
   radius on the button itself instead of relying on a column background.
   EVERY interactive state (hover/focus/active) is pinned to the exact same
   colors -- only the glyph itself (▾ expanded / ▸ collapsed, swapped
   server-side on click) is meant to communicate anything changed. */
/* Collapsed-state baseline: no sibling title bar, no column gold to show
   through -- the button carries its own gold fill and full corner radius. */
[class*="st-key-toggle_history"] button, [class*="st-key-toggle_progress"] button {
    background: linear-gradient(180deg,#f5a623,#e08a1e) !important;
    border: none !important; box-shadow: none !important;
    color: #2f6bea !important; font-size: 18px !important; font-weight: 800 !important;
    /* line-height matches .tt-card-head's own explicit value exactly (same
       10px padding on both) -- see that rule's comment for why relying on
       each element's own default line-height ratio left the button ~2.4px
       taller than the title bar it sits beside. */
    line-height: 20px !important;
    padding: 10px 10px !important; min-height: 0 !important; border-radius: var(--tt-radius-md) !important;
}
[class*="st-key-toggle_history"] button p, [class*="st-key-toggle_progress"] button p {
    color: #2f6bea !important; font-size: 18px !important; font-weight: 800 !important;
}
/* Expanded-state override: nested inside the title+toggle columns row
   (stable via the existing [data-testid="stHorizontalBlock"] wrapper, not
   a guess at DOM nesting depth) -- the COLUMN carries the gold fill here
   (see above), so the button itself goes transparent and only rounds its
   top-right corner, matching where it sits against the title bar. Scoped
   to WITHIN history_panel/progress_panel specifically -- an unscoped
   [data-testid="stHorizontalBlock"] also matches the page's own outer
   [History | Chat | Progress] row, an ANCESTOR of this button in every
   state including collapsed, which made the "transparent" override win
   even when there was no title-bar column underneath to show through
   (confirmed live: the collapsed button rendered fully invisible instead
   of its intended solid gold pill). */
[class*="st-key-history_panel"] [data-testid="stHorizontalBlock"] [class*="st-key-toggle_history"] button,
[class*="st-key-progress_panel"] [data-testid="stHorizontalBlock"] [class*="st-key-toggle_progress"] button {
    background: transparent !important;
    border-radius: 0 var(--tt-radius-md) 0 0 !important;
}
[class*="st-key-toggle_history"] button:hover, [class*="st-key-toggle_progress"] button:hover,
[class*="st-key-toggle_history"] button:active, [class*="st-key-toggle_progress"] button:active,
[class*="st-key-toggle_history"] button:focus, [class*="st-key-toggle_progress"] button:focus {
    color: #2f6bea !important; box-shadow: none !important; border: none !important;
}
[class*="st-key-toggle_history"] button:hover p, [class*="st-key-toggle_progress"] button:hover p,
[class*="st-key-toggle_history"] button:active p, [class*="st-key-toggle_progress"] button:active p,
[class*="st-key-toggle_history"] button:focus p, [class*="st-key-toggle_progress"] button:focus p {
    color: #2f6bea !important;
}

/* History buttons -- History is a SECONDARY panel (rule 7), so its own
   typography/padding sit a notch below the main chat's, using the shared
   small-text token rather than its own one-off sizes. */
[class*="st-key-newchat"] button {
    font-family:'Nunito',sans-serif !important; font-weight:800 !important; font-size:var(--tt-font-small) !important;
    background:#2f9e5a !important; color:#fff !important; border:none !important; border-radius:var(--tt-radius-sm) !important;
    padding:7px !important; margin-bottom:var(--tt-gap-sm) !important; box-shadow:none !important;
}
[class*="st-key-newchat"] button p { color:#fff !important; font-weight:800 !important; font-size:var(--tt-font-small) !important; }
[class*="st-key-chatopen_"] button {
    font-family:'Nunito',sans-serif !important; font-weight:700 !important; font-size:var(--tt-font-small) !important;
    color:#2f4d80 !important; background:#fff8ec !important; border:1px solid #f3deb0 !important;
    border-radius:var(--tt-radius-sm) !important; padding:7px 10px !important; margin-bottom:var(--tt-gap-xs) !important; box-shadow:none !important;
    justify-content:flex-start !important; text-align:left !important;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}
[class*="st-key-chatopen_"] button p { color:#2f4d80 !important; font-weight:700 !important; font-size:var(--tt-font-small) !important; }
[class*="st-key-chatopen_"] button[kind="primary"] { background:#fff1cf !important; border:2px solid #f5a623 !important; }
[class*="st-key-chatopen_"] button[kind="primary"] p { color:#9a5b12 !important; }

/* current-chat question chips (navy text on warm cream pill) */
.tt-hist-item { font-family:'Nunito',sans-serif; font-weight:700; font-size:var(--tt-font-small); color:#2f4d80;
    background:#fff8ec; border:1px solid #f3deb0; border-radius:var(--tt-radius-sm); padding:7px 10px; margin-bottom:var(--tt-gap-xs);
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.tt-hist-count { display:inline-block; font-size:var(--tt-font-xs); font-weight:800; color:#9a7a3f;
    background:#f3e6c6; border-radius:999px; padding:1px 7px; margin-left:4px; }
.tt-hist-empty { font-family:'Nunito',sans-serif; font-weight:700; font-size:var(--tt-font-small); color:#7a6a52;
    background:rgba(245,166,35,0.08); border:1px dashed #e8c48a; border-radius:var(--tt-radius-sm);
    padding:14px 14px; margin: 4px 2px; text-align:center; }

/* Change-grade (neutral family) -- the Clear chat/Reset learning progress/
   Change name buttons that used to share this family were removed (live
   request: they were account-level actions sitting outside any of the
   three scrolling cards, pushing the Progress column taller than History
   and forcing the whole page to scroll). "Change ▾" is what's left. */
[class*="st-key-change_grade_btn"] button, [class*="st-key-grade_picker_close"] button,
[class*="st-key-grade_confirm_no"] button {
    font-family:'Nunito',sans-serif !important; font-weight:700 !important; font-size:var(--tt-font-small) !important;
    background:#fff !important; border:1px dashed #e8c48a !important; color:#111 !important;
    border-radius:var(--tt-radius-sm) !important; padding:7px !important; box-shadow:none !important;
    transition: background-color .12s ease, border-color .12s ease;
    /* At tablet-ish widths the "Change ▾" button's own column can be too
       narrow for its label, and without this Streamlit breaks the word
       mid-letter ("Cha" / "nge ▾") rather than wrapping or shrinking (U-07).
       Nowrap forces the button to size to its text instead of breaking it;
       the ellipsis is a safety net for the rare case where a column is
       narrower than even the whole label needs (e.g. "Change ▾" in a ~42px
       column at 834px), so the text clips cleanly with "…" instead of
       visibly bleeding past the button's own rounded background. */
    white-space: nowrap !important; overflow: hidden !important; text-overflow: ellipsis !important;
}
[class*="st-key-change_grade_btn"] button p, [class*="st-key-grade_picker_close"] button p,
[class*="st-key-grade_confirm_no"] button p {
    color:#111 !important; font-weight:700 !important; font-size:var(--tt-font-small) !important;
}
[class*="st-key-change_grade_btn"] button:hover, [class*="st-key-grade_picker_close"] button:hover,
[class*="st-key-grade_confirm_no"] button:hover { background:#fff8ec !important; border-color:#d9a35a !important; }
/* Grade change is a non-destructive confirm (no data lost, just ends the
   current problem) -- green/success, not the red used for the destructive
   learning-progress reset above. */
[class*="st-key-grade_confirm_yes"] button {
    font-family:'Nunito',sans-serif !important; font-weight:700 !important; font-size:var(--tt-font-small) !important;
    background:#e6f9ee !important; border:1px solid #a9e6c1 !important; color:#1c7a41 !important;
    border-radius:var(--tt-radius-sm) !important; padding:7px !important; box-shadow:none !important;
}
[class*="st-key-grade_confirm_yes"] button p { color:#1c7a41 !important; font-weight:700 !important; font-size:var(--tt-font-small) !important; }
[class*="st-key-grade_confirm_yes"] button:hover { background:#d8f3e3 !important; }

/* ===== MIDDLE AREA ===== */
.tt-buddy-line { color:#4a5572; font-weight:600; font-size:var(--tt-font-body); }

/* message avatars -- the chat is the PRIMARY experience (rule 5), so this
   block keeps a comfortable, readable body-text size rather than shrinking
   along with the secondary panels; only the one genuinely inconsistent
   value (.tt-q at 17px vs. everything else at 16px) is normalized to the
   shared body-text token. */
.tt-av { display:inline-flex; width:32px; height:32px; border-radius:11px;
    align-items:center; justify-content:center; font-size:17px; margin-right:9px; vertical-align:middle; flex-shrink:0; }
.tt-av.student { background:#ff6f59; }
.tt-av.bot { background:#f5a623; }
.tt-bot-head { display:flex; align-items:center; font-family:'Baloo 2',sans-serif;
    font-weight:800; color:#111; font-size:var(--tt-font-h1); margin:2px 0 8px; }
/* Same icon+name head line as the bot's own .tt-bot-head, so a question
   and its reply read as the same KIND of turn -- the avatar used to live
   inside the question's own card (unlike the bot, whose icon sits above
   its card), which this now matches. */
.tt-q-head { display:flex; align-items:center; font-family:'Baloo 2',sans-serif;
    font-weight:800; color:#111; font-size:var(--tt-font-h1); margin:2px 0 6px; }

.tt-q {
    background:#fff8ec; border:1px solid #f3deb0; border-radius:var(--tt-radius-md); padding:11px 14px;
    font-weight:700; color:#111 !important; font-size:var(--tt-font-body); margin:2px 0 10px;
}
.answer-block.intro {
    background:#fffaf0; border:1px solid #f3deb0; border-left:7px solid #f5a623; border-radius:var(--tt-radius-md);
    padding:14px 16px; white-space:pre-wrap; font-size:var(--tt-font-body); line-height:1.6; color:#111; font-weight:600; margin-bottom:10px;
}
.answer-block {
    background:#f3fbf6; border:1px solid #cfeed9; border-left:7px solid #43c17e; border-radius:var(--tt-radius-md);
    padding:15px 17px; white-space:pre-wrap; font-size:var(--tt-font-body); line-height:1.6; color:#111; font-weight:600;
}
.chat-reply {
    background:#fffaf0; border:1px solid #f3deb0; border-left:6px solid #f5a623; border-radius:var(--tt-radius-md);
    padding:13px 15px; font-size:var(--tt-font-body); line-height:1.55; color:#111; font-weight:600;
}
.hint-tag {
    font-family:'Nunito',sans-serif; font-size:var(--tt-font-body); font-weight:600; color:#111;
    background:#fff4d6; border-left:5px solid #f5b301; border-radius:var(--tt-radius-sm); padding:9px 13px; margin:6px 0;
}
.verify-tag { font-family:'Nunito',sans-serif; font-weight:700; font-size:var(--tt-font-small); color:#1c7a41;
    background:#e8f7ee; border:1px solid #bfe8cf; border-radius:999px; padding:4px 12px; display:inline-block; margin-top:8px; }
.source-tag { font-family:'Nunito',sans-serif; font-size:var(--tt-font-small); color:#7a6a52;
    border-top:1px dashed #e8c48a; margin-top:10px; padding-top:8px; }

/* answer-check gate */
.feedback-correct { font-family:'Baloo 2',sans-serif; font-weight:700; font-size:var(--tt-font-body); color:#1c7a41;
    background:#e6f9ee; border:1px solid #a9e6c1; border-radius:var(--tt-radius-sm); padding:9px 13px; margin:8px 0; }
.feedback-wrong { font-family:'Baloo 2',sans-serif; font-weight:700; font-size:var(--tt-font-body); color:#c0343a;
    background:#fdeaea; border:1px solid #f4bfc2; border-radius:var(--tt-radius-sm); padding:9px 13px; margin:8px 0; }
[class*="st-key-ans_"] input { border:1px solid #f3deb0 !important; border-radius:var(--tt-radius-sm) !important;
    font-weight:700 !important; color:#111 !important; background:#fff !important; }

/* per-question shortcut buttons — spread + warm, sized as the PRIMARY
   action on a turn (consistent with the chat area's own body-text scale),
   with real hover/active feedback instead of only a static resting state. */
.tt-shortcut-hint { color:#7a6a52; font-weight:700; font-size:var(--tt-font-small); margin:10px 2px 6px; }
[class*="st-key-turnbtn_"] button {
    font-family:'Baloo 2',sans-serif !important; font-weight:800 !important; font-size:var(--tt-font-body) !important;
    background:linear-gradient(135deg,#f5b301,#ff6f59) !important; color:#fff !important;
    /* Border/shadow use the same deep navy the onboarding card's own
       headings use (#2f4d80), not the old primary blue -- this is the
       "navy = depth/contrast accent" border that grounds the orange fill
       while staying inside the now-storybook gold/orange/navy/cream/green
       palette. */
    border:2px solid #2f4d80 !important; border-radius:var(--tt-radius-md) !important; padding:10px 8px !important;
    min-height: var(--tt-control-h) !important; box-sizing: border-box !important;
    box-shadow:2px 2px 0 rgba(47,77,128,0.25) !important;
    transition: transform .08s ease, box-shadow .08s ease !important;
}
[class*="st-key-turnbtn_"] button p { color:#fff !important; font-weight:800 !important; }
[class*="st-key-turnbtn_"] button:hover:not(:disabled) { transform: translateY(-1px); box-shadow:3px 4px 0 rgba(47,77,128,0.3) !important; }
[class*="st-key-turnbtn_"] button:active:not(:disabled) { transform: translateY(0); box-shadow:1px 1px 0 rgba(47,77,128,0.25) !important; }
[class*="st-key-turnbtn_"] button:disabled { opacity:0.55 !important; box-shadow:none !important; }

/* Progress rows -- supporting information, one notch below the chat's own
   body-text size (rule 8: "useful, but should not feel oversized"). */
/* flex-wrap lets the value drop to its own line when a row is too narrow
   for label + value side by side (e.g. "Tutor Level" / "Intermediate" at
   tablet widths) instead of the two overlapping/interleaving (U-07). */
.tt-prog-row { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap;
    row-gap:2px; padding:6px 0; font-weight:800; font-size:var(--tt-font-small); }

/* Badges -- supporting gamification, not four large primary elements
   (rule 9): noticeably smaller than before (82px/52px hex -> 66px/42px). */
.tt-badges { display:flex; flex-wrap:wrap; gap:10px; }
.tt-badge { width:66px; text-align:center; }
.tt-badge .hex { width:42px;height:42px;margin:0 auto 4px;border-radius:var(--tt-radius-sm);display:flex;align-items:center;justify-content:center;font-size:18px;color:#fff; }
.tt-badge .lbl { font-size:var(--tt-font-xs); font-weight:800; line-height:1.15; }
.tt-badge.locked .hex { background:#f3deb0; color:#bfa264; }

/* Ask-bar styling lives entirely under the [data-testid="stForm"] block
   below (the real, matching selector for this element -- see that block's
   own comment). This used to also be set here under a second, narrower
   selector that specificity made almost entirely dead weight (the stForm
   rule's height/width/padding always won); consolidated to one source of
   truth instead of two partially-overlapping ones. */

/* Footer — FIXED at the very bottom, full width. Previously 14px/34px
   padding + 16px bold text on a permanently-visible, purely motivational
   strip was one of the larger contributors to "things feel oversized";
   tightened to the shared footer-height token (the composer below
   positions itself relative to this SAME token, so the two can never
   silently drift apart the way the old two unrelated magic numbers
   could). */
.tt-footer {
    position: fixed; left: 0; right: 0; bottom: 0; z-index: 1000;
    display:flex; align-items:center; justify-content:center;
    min-height: var(--tt-footer-h); box-sizing: border-box; overflow: hidden;
    /* Grass/ground gradient built around the SAME green as the "New chat"
       button (#2f9e5a) instead of the onboarding world's lighter/yellower
       hill green, so the one green the app repeats most often (its own
       "add/positive action" color) is the one the footer echoes. The
       flowers/critter from _build_footer_scene paint as absolutely-
       positioned children behind the motivational pill. */
    background:linear-gradient(180deg,#4ab878 0%,#2f9e5a 55%,#238049 100%);
    border-radius:var(--tt-radius-lg) var(--tt-radius-lg) 0 0; padding:5px 20px;
    box-shadow:0 -4px 14px rgba(47,100,40,0.2);
}
.tt-f-flower, .tt-f-critter { position: absolute; }
.tt-footer-pill {
    position: relative; display:inline-flex; align-items:center; gap:5px;
    background:#fffaf0; color:#5a4a30; border:1px solid #f3deb0;
    border-radius:999px; padding:4px 14px; font-weight:700; font-size:var(--tt-font-small);
    box-shadow:0 3px 10px rgba(47,100,40,0.18);
}
/* Fixed ask bar — floats just above the footer, spans full width like a
   real search bar. Was previously selected as [class*="st-key-ask_bar"],
   assuming st.form(key="ask_bar") adds a "st-key-ask_bar" class the way a
   container/widget key does -- it doesn't, in this Streamlit version
   (confirmed live: the rendered form has no such class at all, only
   data-testid="stForm"). That meant this entire block -- the fixed
   positioning, the input/button flex layout, all of it -- silently never
   matched anything, and the ask bar rendered in plain document flow the
   whole time (part of U-01: on a short page the gap was invisible, but it
   could end up buried mid-page or below the fold instead of always being
   reachable). There is exactly one st.form() in this app, so the bare
   data-testid is unambiguous here. */
[data-testid="stForm"] {
    position: fixed !important; left: 0; right: 0;
    bottom: calc(var(--tt-footer-h) + 14px); z-index: 999;
    max-width: 820px; margin: 0 auto; padding: 0 20px;
    /* Streamlit's own stylesheet sizes a form to 100% of its NORMAL flex
       parent's height; once position:fixed takes it out of that flow, the
       containing block for a percentage height becomes the viewport
       itself, so the form silently stretched to the full viewport height
       (confirmed live: height 844px, top -74px off-screen, on an
       844px-tall layout) instead of hugging its one-row content. That
       oversized invisible box was pushing the actual input/button out of
       Playwright's -- and plausibly a real touch browser's -- notion of
       the interactive viewport. */
    height: auto !important;
}
/* The composer is centered on the whole VIEWPORT (position:fixed has no
   notion of "the center column"), but the center column itself is only
   ~55% of the page at the [History | Chat | Progress] ratio (2.4 of 4.4
   parts) -- at full desktop width those happen to roughly line up, but
   between the mobile stacking breakpoint and the page's max-width, a
   flat 820px composer is WIDER than the actual center column and spills
   out underneath the side panels (confirmed live at 768px: the submit
   button sat on top of the Badges card -- a direct "no overlapping
   content" violation). Scaling the cap with viewport width keeps it
   inside the center column's real bounds at every width in between,
   rather than patching this one breakpoint with another fixed number. */
@media (max-width: 1560px) and (min-width: 701px) {
    [data-testid="stForm"] { max-width: 48vw; }
}
/* Below the stacking breakpoint, [History | Chat | Progress] becomes ONE
   long column (reordered so Chat comes first -- see the mobile-reorder
   rule above). A position:fixed composer has no notion of "the chat
   section specifically" -- it stays pinned to the same screen position no
   matter what the page has scrolled to, so once a child scrolls down past
   the chat into History/Progress/Badges, the composer ends up floating on
   top of THEM instead (confirmed live: the submit button sitting on top of
   the Progress card's Class row). The fix is architectural, not another
   offset: switch to position:sticky so the composer only tracks the
   bottom of the viewport while its own containing block (the chat
   section) is still the thing in view, and scrolls away naturally with it
   once the child scrolls on to History/Progress -- exactly the "never
   covers progress/history" requirement, without a single overlap patch. */
@media (max-width: 700px) {
    [data-testid="stForm"] {
        position: sticky !important; left: auto; right: auto;
        bottom: calc(var(--tt-footer-h) + 10px) !important;
        max-width: 100% !important; margin: var(--tt-gap-sm) 0 !important; padding: 0 !important;
    }
}
[data-testid="stForm"] [data-testid="stHorizontalBlock"] {
    display: flex !important;
    align-items: stretch !important;
    gap: var(--tt-gap-sm) !important;
}
[data-testid="stForm"] [data-testid="stTextInput"] {
    margin: 0 !important;
}
[data-testid="stForm"] [data-testid="stTextInput"] > div {
    height: var(--tt-control-h) !important;
}
[data-testid="stForm"] [data-testid="stTextInput"] input {
    font-family:'Nunito',sans-serif !important; font-weight:600 !important; font-size:15.5px !important;
    color:#111 !important; background:#ffffff !important; border:2px solid #f3deb0 !important;
    border-radius:var(--tt-radius-md) !important;
    height: var(--tt-control-h) !important;
    padding:0 18px !important;
    box-sizing: border-box !important;
    box-shadow:0 4px 14px rgba(47,100,40,0.12) !important;
}
[data-testid="stForm"] [data-testid="stTextInput"] input::placeholder { color:#8a95b3 !important; }
[data-testid="stForm"] [class*="st-key-askbtn"] {
    display: flex !important;
    align-items: stretch !important;
}
[data-testid="stForm"] [class*="st-key-askbtn"] button {
    background:#2f6bea !important; color:#fff !important; border:none !important;
    border-radius:var(--tt-radius-md) !important; font-size:17px !important; font-weight:800 !important;
    height: var(--tt-control-h) !important;
    width: var(--tt-control-h) !important;
    min-height: 0 !important;
    padding: 0 !important;
    box-shadow:0 4px 14px rgba(31,87,214,0.2) !important;
    transition: transform .08s ease !important;
}
[data-testid="stForm"] [class*="st-key-askbtn"] button:hover:not(:disabled) { transform: translateY(-1px); }
[data-testid="stForm"] [class*="st-key-askbtn"] button:active:not(:disabled) { transform: translateY(0); }
[data-testid="stForm"] [class*="st-key-askbtn"] button:disabled { opacity:0.5 !important; }
</style>
"""
