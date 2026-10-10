"""frontend/views/name_page.py -- PAGE 1: onboarding (name + class)."""
from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from frontend.assets.onboarding_scene import (
    _ICON_CAP_SVG,
    _ICON_PERSON_SVG,
    _MASCOT_SVG,
    _build_onboarding_scene,
)
from frontend.state import change_grade, ss
from frontend.styles.scene_css import SCENE_CSS


# ===========================================================================
# PAGE 1 — NAME
# ===========================================================================
def _name_page_submit(name_field_value: str, grade_value: int | None) -> bool:
    """Whether "Let's go" may proceed: both a non-blank name AND a chosen
    class are required. render_name_page calls this on every rerun (not
    just at submit time) to decide the button's disabled= state -- a child
    can no longer submit with either field empty at all, so there is
    nothing left to warn about after the fact (see that function for why
    this can't live inside an st.form, which was tried first)."""
    return bool(name_field_value.strip()) and grade_value is not None


def render_name_page():
    st.markdown(SCENE_CSS, unsafe_allow_html=True)
    st.markdown(
        """
        <style>
        /* ===== THE WORLD: sky + horizon, replacing the old flat navy ===== */
        .stApp, [data-testid="stAppViewContainer"], html, body {
            background: linear-gradient(180deg, #6fb3ed 0%, #a9d8f5 32%, #e7f6ea 64%, #fce8c8 100%) !important;
            background-attachment: fixed !important;
            overflow-x: hidden !important;
        }
        /* Every scene piece is position:fixed, deliberately WITHOUT its own
           z-index -- the scene markup is injected before the card's own
           title/input content in the DOM, so with every element left at
           the default z-index:auto, normal paint order (later DOM wins)
           already puts the real card content above the decorations with
           no extra bookkeeping. (An explicit z-index was tried first and
           rejected: it forces .block-container into its own stacking
           context, and a scene element with a HIGHER explicit z-index
           than the card's plain-text children would then paint ABOVE
           them within that context -- DOM order sidesteps the whole
           question.) Separately: Streamlit's own
           [data-testid="stAppViewContainer"] wrapper sets
           overflow:hidden, which clips a fixed-position descendant to
           ITS box in every real browser (fixed only escapes the
           ancestor's LAYOUT sizing, not its paint/clip region) --
           confirmed live, the scene had correct computed positions but
           rendered completely invisible until this override. */
        [data-testid="stAppViewContainer"], .stApp { overflow: visible !important; }

        /* ===== THE HERO: Math Buddy, welcoming the child into the world ===== */
        .tt-mascot-wrap {
            position: fixed; left: calc(50% - 350px); top: 32vh;
            width: 150px; pointer-events: none; text-align: center;
        }
        .tt-speech {
            display: inline-block; background: #ffffff; color: #3b2a2a;
            font-family: 'Baloo 2', sans-serif; font-weight: 700; font-size: 15px;
            border-radius: 16px; padding: 8px 14px; margin-bottom: 6px;
            box-shadow: 0 6px 14px rgba(0,0,0,0.16); position: relative;
        }
        .tt-speech::after {
            content: ""; position: absolute; bottom: -7px; left: 38px;
            border-width: 8px 7px 0 7px; border-style: solid;
            border-color: #ffffff transparent transparent transparent;
        }

        /* Vertically centers the card in the viewport on desktop/tablet
           (it previously sat pinned near the top with a large empty area
           below it). flexbox centering still lets the card scroll
           normally if its own content is ever taller than the viewport
           (e.g. a very short window), so this never traps anything. */
        [data-testid="stMain"] {
            display: flex !important; flex-direction: column !important;
            justify-content: center !important; min-height: 100vh !important;
        }
        /* ===== THE CARD: one object IN the world, not a form floating in
           empty space -- warm cream instead of a dark translucent panel,
           so it reads as a storybook page rather than a UI modal. Top
           padding trimmed well below the sides/bottom (was flat 30px, a
           lot of unused air above a title that could be reading right
           away) -- the title below is also bigger now, which fills that
           reclaimed room rather than leaving it empty. ===== */
        .block-container {
            max-width: 480px !important; margin: 0 auto !important;
            background: #fffaf0 !important;
            border: 1px solid #f3deb0 !important;
            border-radius: 28px !important; padding: 18px 34px 30px !important;
            box-shadow: 0 22px 46px rgba(70,45,15,0.22) !important;
            position: relative !important; z-index: 10 !important;
        }
        /* A tiny decorative sparkle tucked in the card's own corner -- math
           belongs to this world too, even on the "UI" object (rule 8). */
        .block-container::before {
            content: "✦"; position: absolute; top: 14px; right: 20px;
            font-size: 20px; color: #f5b301; opacity: 0.8;
        }
        .tt-title {
            font-family: 'Baloo 2', sans-serif !important; font-weight: 800 !important;
            font-size: 36px !important; line-height: 1.08 !important;
            text-align: center !important; color: #2f4d80 !important; margin: 0 0 4px 0 !important;
        }
        .tt-title .accent { color: #e08a1e !important; }
        .tt-sub {
            text-align: center !important; font-family: 'Nunito', sans-serif !important;
            font-weight: 700 !important; font-size: 15px !important;
            color: #7a6a52 !important; margin: 2px 0 14px 0 !important;
        }
        .tt-field-label {
            font-family: 'Baloo 2', sans-serif !important; font-weight: 700 !important;
            font-size: 14.5px !important; color: #5a4a30 !important; margin: 0 0 6px 2px !important;
            display: flex !important; align-items: center !important; gap: 6px !important;
        }
        .tt-field-label svg { width: 17px; height: 17px; flex-shrink: 0; }

        @media (max-width: 1100px) {
            .tt-mascot-wrap { left: 4%; width: 120px; top: 28vh; }
            /* The mascot moves to the left edge at this width, which put
               it directly behind this one cloud (confirmed live: the
               speech bubble and the cloud overlapped). Move the cloud
               clear rather than hide it -- it's still a desktop/tablet
               width, there's room. */
            .tt-cloud-near-mascot { left: 38% !important; top: 5% !important; }
        }
        /* Below Streamlit's own column-stacking breakpoint there is no
           room beside the card for a fixed mascot without it either
           overlapping the form or being pushed off-screen -- rule 3/11
           explicitly ask for a RECOMPOSED mobile scene, not a shrunk
           desktop one, so the mascot moves into normal document flow
           ABOVE the card instead of floating beside it. */
        @media (max-width: 700px) {
            .tt-mascot-wrap {
                position: static !important; width: 92px; margin: 0 auto 6px; top:auto; left:auto;
            }
            .block-container { padding: 16px 20px 24px !important; max-width: 94vw !important; }
            .tt-title { font-size: 28px !important; }
            .tt-hide-sm { display: none !important; }
        }
        @media (max-width: 1024px) { .tt-hide-md { display: none !important; } }
        @media (max-width: 480px) {
            .block-container { padding: 14px 16px 20px !important; }
            .tt-title { font-size: 24px !important; }
        }
        /* A SHORT viewport (an older/small phone in portrait, or any phone
           in landscape) is a separate problem from a NARROW one -- the
           form's total height, not its width, is what risks forcing
           scrolling before the child ever reaches "Let's go" (rule 11:
           "should still be accessible without excessive scrolling").
           Shrinks the mascot and every vertical gap specifically when
           height is tight, independent of width. */
        @media (max-height: 700px) {
            .tt-mascot-wrap { width: 64px; margin-bottom: 2px; }
            .tt-speech { font-size: 13px; padding: 6px 11px; }
            .block-container { padding-top: 12px !important; padding-bottom: 14px !important; }
            .tt-title { font-size: 22px !important; margin-bottom: 2px !important; }
            .tt-sub { font-size: 13px !important; margin-bottom: 8px !important; }
            .tt-field-label { margin: 0 0 3px 2px !important; }
        }
        /* A restored (not maximized) browser window keeps its full desktop
           WIDTH but often loses enough HEIGHT to chrome/taskbar to trip the
           max-height:700px shrink above -- confirmed live: that rule
           shrinks the mascot from 150px to 64px wide without moving its
           `left` anchor, which was tuned assuming the 150px width, so the
           mascot's right edge (meant to tuck slightly UNDER the card's left
           edge) pulls back 86px and opens a visible gap instead -- reading
           as the mascot having drifted away from the card, not just gotten
           smaller. Re-anchored here to the SAME right edge as the normal
           150px-wide/left:calc(50% - 350px) desktop position, but only
           above the 1100px width breakpoint -- below it the mascot is
           already in its own left-edge-of-viewport layout (left: 4%, not
           card-relative), where this gap can't occur and re-anchoring would
           be wrong. */
        @media (min-width: 1101px) and (max-height: 700px) {
            .tt-mascot-wrap { left: calc(50% - 264px); }
        }
        /* A genuinely tiny/old phone in portrait (≤600px tall) -- drop the
           mascot from the flow entirely rather than squeeze it further;
           the card itself is still the whole point, and at this height
           every remaining pixel matters more than the hero graphic does. */
        @media (max-height: 600px) {
            .tt-mascot-wrap { display: none !important; }
            .tt-sub { margin-bottom: 6px !important; }
        }

        /* ===== THE TWO FIELDS: stacked, full-width, and -- the live
           request -- pixel-identical to each other (same height, border,
           radius, font, shadow). Previously the name field sat in a 3:1
           split next to the button while the class dropdown was its own
           full-width row below, so the two never had a chance to match;
           both are full rows now, with the button moved below them, which
           is what makes matching them directly possible. ===== */
        div[data-testid="stTextInput"] input,
        div[data-testid="stSelectbox"] > div > div {
            box-sizing: border-box !important;
            font-family: 'Nunito', sans-serif !important; font-weight: 700 !important;
            font-size: 16px !important; color: #2f4d80 !important;
            border: 3px solid #f5b301 !important; border-radius: 12px !important;
            background: #ffffff !important; box-shadow: 0 4px 14px rgba(0,0,0,0.10) !important;
            height: 52px !important; min-height: 52px !important;
        }
        div[data-testid="stTextInput"] input { padding: 0 16px !important; }
        div[data-testid="stTextInput"] input::placeholder { color: #9aa7c2 !important; }
        [data-testid="stHorizontalBlock"] { align-items: center !important; }
        /* The selected value is rendered by this Streamlit version as an
           actual <input> inside a react-aria-ComboBox (a searchable
           dropdown, not nested <div>s) -- form controls do NOT inherit
           `color` from an ancestor the way plain text does, so without an
           explicit rule here the input was left at the browser's own
           default text color instead of this page's navy, regardless of
           the (harmless but non-matching) `> div > div > div` rule a
           Streamlit upgrade had quietly turned into a no-op. Set directly,
           and -webkit-text-fill-color too since that's what wins over
           `color` in some WebKit/Blink states (e.g. autofill). */
        div[data-testid="stSelectbox"] input {
            color: #2f4d80 !important; -webkit-text-fill-color: #2f4d80 !important;
            opacity: 1 !important; padding-left: 13px !important;
        }
        div[data-testid="stSelectbox"] svg { fill: #2f4d80 !important; }
        /* Streamlit's default focus ring is red, clashing with the gold/blue
           theme; swap it for the same gold used on the border everywhere
           else on this page. */
        div[data-testid="stSelectbox"] > div > div:focus-within,
        div[data-testid="stTextInput"] > div:focus-within {
            border-color: #f5b301 !important; box-shadow: 0 0 0 3px rgba(245,179,1,0.35) !important;
            border-radius: 12px !important;
        }
        /* The options list renders in a portal outside .block-container (a
           div, not a ul -- role="listbox"/"option" on plain divs), so it
           needs its own (global) rule to match the same card style. */
        div[data-testid="stSelectboxVirtualDropdown"] {
            font-family: 'Nunito', sans-serif !important;
            border: 3px solid #f5b301 !important; border-radius: 12px !important;
            overflow: hidden !important; box-shadow: 0 14px 30px rgba(0,0,0,0.22) !important;
            /* Capped so 5 short options never need more vertical room than
               this -- a shorter requested height makes the browser's
               auto-flip-to-fit logic far less likely to decide it has to
               open upward in the first place. */
            max-height: 210px !important;
        }
        div[data-testid="stSelectboxVirtualDropdown"] div[role="listbox"] {
            max-height: 210px !important; overflow-y: auto !important;
        }
        div[data-testid="stSelectboxVirtualDropdown"] div[role="option"] {
            font-weight: 700 !important; color: #2f4d80 !important; background: #ffffff !important;
            font-size: 15px !important;
        }
        div[data-testid="stSelectboxVirtualDropdown"] div[role="option"]:hover {
            background: #fff4d6 !important;
        }

        /* ===== THE CTA: moved to the bottom (below both now-matching
           fields), bigger than before -- it's the only button on the
           page, and "Welcome" + two tidy fields now lead down to it. ===== */
        [class*="st-key-go_btn"] button {
            font-family: 'Baloo 2', sans-serif !important; font-weight: 800 !important;
            font-size: 18px !important; width: 100% !important; border: none !important;
            border-radius: 14px !important; padding: 16px !important; margin-top: 6px !important;
            background: linear-gradient(180deg, #f5a623 0%, #e08a1e 100%) !important; color: #ffffff !important;
            box-shadow: 0 6px 16px rgba(224,138,30,0.4) !important;
            transition: transform .08s ease, box-shadow .12s ease, background .12s ease !important;
        }
        [class*="st-key-go_btn"] button p { color:#fff !important; font-size:18px !important; font-weight:800 !important; }
        [class*="st-key-go_btn"] button:hover:not(:disabled) {
            background: linear-gradient(180deg, #ffb94d 0%, #f5a623 100%) !important;
            box-shadow: 0 8px 20px rgba(224,138,30,0.5) !important; transform: translateY(-1px);
        }
        [class*="st-key-go_btn"] button:active:not(:disabled) { transform: translateY(0); }
        /* Disabled -- a plain blue (not Streamlit's own default hover-grey,
           which read as an unstyled/broken button), distinct from the
           gold "ready to tap" fill so the two states still read apart. */
        [class*="st-key-go_btn"] button:disabled {
            background: #2f6bea !important; color: #ffffff !important;
            box-shadow: none !important; cursor: not-allowed !important; opacity: 1 !important;
        }
        [class*="st-key-go_btn"] button:disabled p { color: #ffffff !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # The illustrated world -- entirely decorative, entirely behind the
    # card (see the negative z-index rules above). One combined injection
    # keeps this to a single DOM write instead of two dozen separate
    # st.markdown calls.
    st.markdown(_build_onboarding_scene(), unsafe_allow_html=True)
    st.markdown(
        f'<div class="tt-mascot-wrap">'
        f'<div class="tt-speech">Hi there! 👋</div>'
        f'<div>{_MASCOT_SVG}</div></div>',
        unsafe_allow_html=True,
    )

    st.markdown('<p class="tt-title">Welcome, <span class="accent">Tiny&nbsp;Thinker!</span></p>', unsafe_allow_html=True)
    st.markdown('<p class="tt-sub">Let\'s get ready for your math adventure! ✨</p>', unsafe_allow_html=True)

    # Plain widgets, NOT wrapped in an st.form: a form only pushes widget
    # values into the script on submit, which would make `disabled=` below
    # permanently stale (it needs this run's live name_field/grade_field to
    # decide whether THIS click should even be allowed) -- see "no
    # auto-selected class, disable Let's go until both fields are filled"
    # in the stabilization notes. Enter-to-submit (which a form would have
    # given for free) is wired by hand instead, via the tiny script below.
    st.markdown(f'<p class="tt-field-label">{_ICON_PERSON_SVG}What\'s your name?</p>', unsafe_allow_html=True)
    st.text_input("Your name", key="name_field",
                  placeholder="Type your name here…", label_visibility="collapsed")

    st.markdown(
        f'<p class="tt-field-label" style="margin-top:14px;">{_ICON_CAP_SVG}Which class are you in?</p>',
        unsafe_allow_html=True,
    )
    # index=None + a placeholder -- previously defaulted to Class 3 selected,
    # so a child could submit having never actually chosen a class. Starting
    # genuinely empty is what makes "disable Let's go until a class is
    # picked" (below) a real requirement instead of a no-op.
    grade_choice = st.selectbox(
        "Class", options=[1, 2, 3, 4, 5], index=None,
        format_func=lambda g: f"Class {g}", key="grade_field",
        placeholder="Select your class…", label_visibility="collapsed",
    )

    can_proceed = _name_page_submit(ss.get("name_field", ""), grade_choice)
    go_clicked = st.button(
        "Let's go →" if can_proceed else "Let's go",
        key="go_btn", use_container_width=True, disabled=not can_proceed,
    )

    # Pressing Enter in the name field reruns the script (committing the
    # text) but, with a bare st.button (not st.form_submit_button), does
    # NOT also count as a click -- the same gap the main chat page's ask
    # bar has its own fix for, but that fix is form-based and forms are
    # exactly what this page can't use (see above). Wired by hand instead:
    # find the name input, forward Enter to a synthetic click on the real
    # button element (a no-op while it's disabled, same as actually
    # clicking it would be).
    components.html(
        """
        <script>
        (function () {
            function wire(tries) {
                const doc = window.parent.document;
                const input = doc.querySelector('div[data-testid="stTextInput"] input');
                const btn = doc.querySelector('[class*="st-key-go_btn"] button');
                if (!input || !btn) {
                    if (tries > 0) setTimeout(function () { wire(tries - 1); }, 150);
                    return;
                }
                if (window.frameElement) { window.frameElement.tabIndex = -1; }
                if (input.dataset.ttEnterWired) return;
                input.dataset.ttEnterWired = "1";
                input.addEventListener('keydown', function (e) {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        if (!btn.disabled) { btn.click(); }
                    }
                });
            }
            wire(20);
        })();
        </script>
        """,
        height=0,
    )

    if go_clicked and can_proceed:
        ss.name = ss.name_field.strip()
        change_grade(grade_choice)
        ss.page = "main"
        st.rerun()
    st.stop()
