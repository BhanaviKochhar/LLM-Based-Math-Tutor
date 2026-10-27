"""frontend/views/main_page.py -- PAGE 3: the tutoring chat UI."""
from __future__ import annotations

import html
import time

import streamlit as st
import streamlit.components.v1 as components

from frontend import account, history
from frontend.assets.onboarding_scene import _build_footer_scene, _build_header_scene
from frontend.episode import (
    _ACTIONABLE_LABELS,
    _BADGES,
    _CLOSE_EPISODE_LABELS,
    _LABEL_TO_INTENT,
    _group_chat_history,
    _progress_to_next_badge,
    process_pending_turn,
    queue_pending_turn,
)
from frontend.markdown_utils import _markdown_lite
from frontend.state import (
    _current_learner_level,
    _top_weak_topic,
    active_chat,
    change_grade,
    chat_title,
    display_name,
    ss,
    start_new_chat,
)
from frontend.styles.main_css import MAIN_CSS
from frontend.styles.scene_css import SCENE_CSS


def render_chat_reply(msg):
    st.markdown('<div class="tt-bot-head"><span class="tt-av bot">🤖</span>Math Buddy</div>',
                unsafe_allow_html=True)
    st.markdown(f'<div class="chat-reply">{_markdown_lite(html.escape(msg.get("reply", "")))}</div>',
                unsafe_allow_html=True)


def render_turn(msg, idx, is_latest=False):
    """Render one controller-driven tutoring turn.

    The mode (teach_invite / diagnose_correct / diagnose_wrong / hint /
    co_solve / reveal / ...) comes straight from scripts.llm.controller, so
    what's shown — and whether a real answer is on the screen at all — is
    decided by the state machine, not by this function. Shortcut buttons are
    only interactive on the latest turn; older turns are history."""
    st.markdown('<div class="tt-bot-head"><span class="tt-av bot">🤖</span>Math Buddy</div>',
                unsafe_allow_html=True)

    mode = msg.get("mode")
    text = msg.get("text") or ""

    if mode == "diagnose_correct":
        st.markdown('<div class="feedback-correct">⭐ Correct — great job! 🎉</div>',
                    unsafe_allow_html=True)
        if text:
            st.markdown(f'<div class="chat-reply">{_markdown_lite(html.escape(text))}</div>', unsafe_allow_html=True)
        v = msg.get("verify")
        if v and v.get("verifiable") and v.get("match") is False:
            # The student's stated answer was already graded correct against
            # state.computed_answer by the controller; this catches the rarer
            # case where the model's own celebratory restatement names a
            # different number than the one it just graded.
            st.markdown(
                '<div class="verify-tag" style="background:#fdeaea;color:#c0343a;'
                'border-color:#f4bfc2;">⚠ Disagrees with the computed answer</div>',
                unsafe_allow_html=True,
            )
    elif mode == "diagnose_wrong":
        st.markdown('<div class="feedback-wrong">Not quite — let\'s look again! 💪</div>',
                    unsafe_allow_html=True)
        if text:
            st.markdown(f'<div class="chat-reply">{_markdown_lite(html.escape(text))}</div>', unsafe_allow_html=True)
    elif mode == "hint":
        n = msg.get("hint_number")
        prefix = f"Hint {n}: " if n else ""
        st.markdown(f'<div class="hint-tag">💡 {prefix}{_markdown_lite(html.escape(text))}</div>',
                    unsafe_allow_html=True)
    elif mode == "hint_exhausted":
        st.markdown(f'<div class="hint-tag">💡 {_markdown_lite(html.escape(text))}</div>',
                    unsafe_allow_html=True)
    elif mode in ("co_solve", "reveal"):
        if text:
            st.markdown(f'<div class="answer-block">{_markdown_lite(html.escape(text))}</div>', unsafe_allow_html=True)
        v = msg.get("verify")
        if v and v.get("verifiable"):
            if v.get("match") is True:
                st.markdown('<div class="verify-tag">✓ Verified against computed answer</div>',
                            unsafe_allow_html=True)
            elif v.get("match") is False:
                st.markdown(
                    '<div class="verify-tag" style="background:#fdeaea;color:#c0343a;'
                    'border-color:#f4bfc2;">⚠ Disagrees with the computed answer</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown('<div class="verify-tag">… could not read a final number to verify</div>',
                            unsafe_allow_html=True)
        if msg.get("source"):
            st.markdown(f'<div class="source-tag">📖 {html.escape(msg["source"])}</div>',
                        unsafe_allow_html=True)
    elif text:
        st.markdown(f'<div class="chat-reply">{_markdown_lite(html.escape(text))}</div>', unsafe_allow_html=True)

    # Bounded arithmetic self-consistency guardrail (Problem 10): flags a
    # worked example the model invented ITSELF (not the student's own
    # problem, which is already checked above) where its own stated equation
    # doesn't add up. Non-blocking -- the reply still shows -- since this is
    # a transparency signal, not a correctness gate.
    #
    # Framing matters here: this checks the TUTOR's own generated arithmetic,
    # not the child's answer (that's the green/red verify-tag above, a
    # completely different signal). Worded and colored so a child never
    # reads this as "you got it wrong" -- amber/tutor-self-check language,
    # the same family as hint-tag, never the red feedback-wrong treatment.
    for issue in (msg.get("self_check_issues") or []):
        st.markdown(
            '<div class="verify-tag" style="background:#fff4d6;color:#8a6400;'
            'border-color:#f0dca0;">💡 Tutor check: this calculation may need '
            'a second look.</div>',
            unsafe_allow_html=True,
        )

    if not is_latest:
        return
    buttons = [b for b in (msg.get("buttons") or []) if b in _ACTIONABLE_LABELS]
    if not buttons:
        return
    chat = active_chat()
    # change_grade() (and anything else that invalidates an episode without
    # appending a new message) clears chat["episode"] to None but leaves the
    # last reply's stored buttons as they were. Without this check those
    # stale "Give me a hint"/"Show me how" buttons stay clickable and would
    # misroute through start_episode (treating the button's LABEL as a brand
    # new question) instead of doing nothing meaningful. A legitimate
    # terminal reply (diagnose_correct, reveal) still has episode SET (just
    # terminal), so this only suppresses the genuinely stale case.
    if chat.get("episode") is None:
        return
    pending = bool(chat.get("pending_turn"))
    st.markdown('<div class="tt-shortcut-hint">Tap a shortcut, or type below 👇</div>',
                unsafe_allow_html=True)
    cols = st.columns(len(buttons))
    for col, label in zip(cols, buttons):
        with col:
            if st.button(label, key=f"turnbtn_{idx}_{label}", use_container_width=True,
                        disabled=pending):
                if label in _CLOSE_EPISODE_LABELS:
                    episode = chat.get("episode")
                    state = episode.get("state") if episode else None
                    if state is not None:
                        from scripts.llm import controller as C
                        try:
                            C.step(state, "NEW_QUESTION", label)
                        except Exception:
                            pass
                    chat["episode"] = None
                    chat["messages"].append({"role": "user", "text": label})
                    chat["messages"].append({
                        "role": "assistant", "kind": "chat", "question": label,
                        "reply": "Sure! What would you like to try next? 🙂",
                    })
                else:
                    queue_pending_turn(chat, label, forced_intent=_LABEL_TO_INTENT[label])
                st.rerun()


def render_main_page():
    st.markdown(SCENE_CSS, unsafe_allow_html=True)
    st.markdown(MAIN_CSS, unsafe_allow_html=True)

    chat = active_chat()
    history.ensure_loaded(chat)
    msgs = chat["messages"]

    solved = sum(1 for m in msgs if m.get("role") == "assistant" and m.get("outcome") == "solved")
    stars = solved * 5
    _, next_badge, lvl_pct = _progress_to_next_badge(solved)

    initial = display_name()[0].upper() if display_name() != "friend" else "🙂"
    st.markdown(
        f'<div class="tt-appbar{" signed-in" if account.signed_in() else ""}">{_build_header_scene()}'
        f'<div class="tt-brand">Tiny<span class="y">Thinker</span></div>'
        f'<div class="tt-bar-right{" with-logout" if account.signed_in() else ""}">'
        f'<span class="tt-user"><span class="av">{initial}</span>'
        f'<span class="name">{display_name()}</span></span></div></div>',
        unsafe_allow_html=True,
    )
    if account.signed_in():
        if st.button("Switch", key="switch_btn"):
            account.switch_child()
            st.rerun()
        if st.button("Log out", key="logout_btn"):
            account.log_out()
            st.rerun()

    ss.setdefault("history_collapsed", False)
    ss.setdefault("progress_collapsed", False)
    # Collapsing a side panel frees its width back to the chat column instead
    # of just leaving an empty card -- Streamlit's column ratios are static
    # per st.columns() call, so this recomputes them each render based on
    # the two toggles below.
    left_w = 0.18 if ss.history_collapsed else 1.0
    right_w = 0.18 if ss.progress_collapsed else 1.0
    center_w = 2.4 + (1.0 - left_w) + (1.0 - right_w)
    left, center, right = st.columns([left_w, center_w, right_w], gap="medium")

    # ---------- LEFT: History + New chat ----------
    with left:
        with st.container(border=True, key="history_panel"):
            if ss.history_collapsed:
                if st.button("▸", key="toggle_history", help="Show History",
                             use_container_width=True):
                    ss.history_collapsed = False
                    st.rerun()
            else:
                head_c, toggle_c = st.columns([5, 1])
                with head_c:
                    st.markdown('<div class="tt-card-head tt-card-head-with-toggle">History</div>', unsafe_allow_html=True)
                with toggle_c:
                    if st.button("▾", key="toggle_history", help="Hide History",
                                 use_container_width=True):
                        ss.history_collapsed = True
                        st.rerun()

                # Everything below the title scrolls on its OWN, independent
                # of the chat column and the page itself -- the title bar
                # above stays in normal flow (not sticky-positioned), so it
                # is simply always visible, the same way a page header is.
                with st.container(height=430, key="history_scroll"):
                    view = st.radio("view", ["Chat History", "All Chats"], horizontal=True,
                                    label_visibility="collapsed", key="hist_view")
                    if st.button("➕ New chat", key="newchat", use_container_width=True):
                        start_new_chat()
                        st.rerun()

                    if view == "Chat History":
                        groups = _group_chat_history(active_chat()["messages"])
                        if groups:
                            for n, g in enumerate(groups, 1):
                                short = g["text"] if len(g["text"]) <= 30 else g["text"][:29] + "…"
                                badge = (f' <span class="tt-hist-count">+{g["follow_ups"]}</span>'
                                        if g["follow_ups"] else "")
                                st.markdown(
                                    f'<div class="tt-hist-item">{n}. {html.escape(short)}{badge}</div>',
                                    unsafe_allow_html=True)
                        else:
                            st.markdown('<div class="tt-hist-empty">No questions in this chat yet — ask one! 👇</div>',
                                        unsafe_allow_html=True)
                    else:
                        for c in reversed(ss.chats):
                            title = chat_title(c)
                            short = title if len(title) <= 24 else title[:23] + "…"
                            q_count = sum(1 for m in c["messages"] if m["role"] == "user")
                            label = f"💬 {short}" + (f"  ({q_count})" if q_count else "")
                            if st.button(label, key=f"chatopen_{c['id']}",
                                         type=("primary" if c["id"] == ss.active else "secondary"),
                                         use_container_width=True):
                                ss.active = c["id"]
                                ss.pop("_confirm_delete_chat", None)
                                st.rerun()

                        # Delete the open chat (and its saved copy, if any).
                        current = active_chat()
                        if current["messages"] or current.get("db_id"):
                            if ss.get("_confirm_delete_chat") == current["id"]:
                                st.markdown('<div class="tt-hist-empty">Delete this chat? '
                                            "This can't be undone.</div>",
                                            unsafe_allow_html=True)
                                dy, dn = st.columns(2)
                                with dy:
                                    if st.button("Delete", key="delchat_yes",
                                                 use_container_width=True):
                                        try:
                                            history.delete(current)
                                        except Exception:
                                            pass
                                        ss.pop("_confirm_delete_chat", None)
                                        st.rerun()
                                with dn:
                                    if st.button("Cancel", key="delchat_no",
                                                 use_container_width=True):
                                        ss.pop("_confirm_delete_chat", None)
                                        st.rerun()
                            elif st.button("🗑 Delete this chat", key="delchat_btn",
                                           use_container_width=True):
                                ss["_confirm_delete_chat"] = current["id"]
                                st.rerun()

    # ---------- RIGHT: Progress + Badges ----------
    # Rendered BEFORE the center column's blocking LLM call (below) on
    # purpose: Streamlit dims any element that hasn't been redrawn yet in
    # the current script run while a run is in flight ("stale" fade) --
    # with Progress drawn AFTER process_pending_turn's synchronous call, it
    # sat un-redrawn (and visibly greyed out) for the whole multi-second
    # generation (live-reported: "see how progress card greys out when
    # tutor is thinking"). Its values (solved/stars/next_badge/etc.) are all
    # computed from the message list BEFORE this turn's reply exists either
    # way, so drawing it here instead of after doesn't change what it shows
    # -- only when Streamlit considers it fresh.
    with right:
        with st.container(border=True, key="progress_panel"):
            if ss.progress_collapsed:
                if st.button("▸", key="toggle_progress", help="Show Progress",
                             use_container_width=True):
                    ss.progress_collapsed = False
                    st.rerun()
            else:
                head_c, toggle_c = st.columns([5, 1])
                with head_c:
                    st.markdown('<div class="tt-card-head tt-card-head-with-toggle">Progress</div>', unsafe_allow_html=True)
                with toggle_c:
                    if st.button("▾", key="toggle_progress", help="Hide Progress",
                                 use_container_width=True):
                        ss.progress_collapsed = True
                        st.rerun()

                # Everything below the title -- stats, the class row, and
                # Badges -- scrolls on its OWN (same "title stays, rest
                # scrolls" treatment as History), independent of the chat
                # column and the page itself. The three account-level
                # buttons below (Clear chat / Reset / Change name) are
                # deliberately NOT in here -- see their own comment for why.
                with st.container(height=430, key="progress_scroll"):
                    # "Next Badge" (a gamified count toward this chat's next
                    # Badges-panel unlock, reset per new chat) and "Tutor
                    # Level" (the persistent backend classification that
                    # actually drives tutoring depth/thresholds) are two
                    # genuinely different things and are labelled as such --
                    # they used to share the single, misleading label
                    # "Level". The bar's value is literally "questions
                    # solved / next badge's threshold" (see
                    # _progress_to_next_badge) -- a real, checkable count,
                    # not a claim about mastery or learning progress.
                    next_badge_label = f"{solved}/{next_badge}" if next_badge else "All earned!"
                    st.markdown(f'<div class="tt-prog-row"><span>🏅 Next Badge</span>'
                                f'<span class="val">{next_badge_label}</span></div>',
                                unsafe_allow_html=True)
                    st.progress(lvl_pct)
                    st.markdown(
                        f'<div class="tt-prog-row"><span>✅ Questions Answered</span><span class="val">{solved}</span></div>'
                        f'<div class="tt-prog-row"><span>🌟 Stars</span><span class="val">{stars}</span></div>'
                        f'<div class="tt-prog-row"><span>🎯 Tutor Level</span>'
                        f'<span class="val">{_current_learner_level().title()}</span></div>',
                        unsafe_allow_html=True,
                    )
                    weak_topic = _top_weak_topic()
                    if weak_topic:
                        st.markdown(
                            '<div class="tt-prog-row"><span>📌 Practice more</span>'
                            f'<span class="val">{html.escape(weak_topic)}</span></div>',
                            unsafe_allow_html=True,
                        )

                    # Ongoing-session grade change: previously grade was only
                    # reachable from the onboarding "name" page (via Change
                    # name), forcing a full navigation away from the chat
                    # just to move a class up or down. This reuses
                    # change_grade()'s same episode-invalidation invariant
                    # without leaving the tutoring session.
                    gc1, gc2 = st.columns([3, 2])
                    with gc1:
                        st.markdown(f'<div class="tt-prog-row"><span>🏫 Class</span>'
                                    f'<span class="val">Class {ss.grade}</span></div>',
                                    unsafe_allow_html=True)
                    with gc2:
                        if st.button("Change ▾", key="change_grade_btn", use_container_width=True):
                            ss["_show_grade_picker"] = not ss.get("_show_grade_picker", False)
                            st.rerun()

                    if ss.get("_show_grade_picker"):
                        new_grade = st.selectbox(
                            "New class", options=[1, 2, 3, 4, 5], index=ss.grade - 1,
                            format_func=lambda g: f"Class {g}", key="grade_picker",
                            label_visibility="collapsed",
                        )
                        if new_grade != ss.grade:
                            st.markdown(
                                '<div class="tt-hist-empty">Changing class will end the '
                                "current problem, but your chat history will stay. "
                                'Are you sure?</div>',
                                unsafe_allow_html=True,
                            )
                            gy, gn = st.columns(2)
                            with gy:
                                if st.button("✅ Yes, change", key="grade_confirm_yes",
                                            use_container_width=True):
                                    change_grade(new_grade)
                                    account.save_grade(new_grade)
                                    ss["_show_grade_picker"] = False
                                    st.rerun()
                            with gn:
                                if st.button("Cancel", key="grade_confirm_no",
                                            use_container_width=True):
                                    ss["_show_grade_picker"] = False
                                    st.rerun()
                        else:
                            if st.button("Close", key="grade_picker_close", use_container_width=True):
                                ss["_show_grade_picker"] = False
                                st.rerun()

                    with st.container(border=True, key="badges_panel"):
                        st.markdown('<div class="tt-card-head">Badges</div>', unsafe_allow_html=True)
                        cells = ""
                        for name, c, ico, threshold in _BADGES:
                            ok = solved >= threshold
                            cls = "" if ok else "locked"
                            bg = f'style="background:{c}"' if ok else ""
                            cells += f'<div class="tt-badge {cls}"><div class="hex" {bg}>{ico if ok else "🔒"}</div><div class="lbl">{name}</div></div>'
                        st.markdown(f'<div class="tt-badges">{cells}</div>', unsafe_allow_html=True)

    # ---------- CENTER: greeting + conversation + ask bar ----------
    with center:
        st.markdown(
            '<div class="tt-bot-head" style="font-size:20px;">'
            '<span class="tt-av bot">🤖</span>Hi! I\'m Math Buddy</div>'
            '<div class="tt-buddy-line" style="margin:-4px 0 14px 44px;">'
            'Ask me any math question below and I\'ll explain it step by step!</div>',
            unsafe_allow_html=True,
        )

        if not msgs:
            pass
        else:
            pairs, i = [], 0
            while i < len(msgs):
                if msgs[i]["role"] == "user":
                    if i + 1 < len(msgs) and msgs[i + 1]["role"] == "assistant":
                        pairs.append((msgs[i], msgs[i + 1], i + 1))
                    else:
                        pairs.append((msgs[i], None, None))
                    i += 2
                else:
                    i += 1

            # Oldest first, newest last — normal chat order (top -> bottom).
            with st.container(height=430, key="chat_scroll"):
                for q, a, a_idx in pairs:
                    with st.container(border=True):
                        # Same two-piece shape as a bot turn: a plain
                        # icon+name head line, THEN a separate card with
                        # just the content -- NOT nested inside each other.
                        # (A <div> head line nested INSIDE the <a> below was
                        # tried first; Streamlit's markdown renderer silently
                        # drops block-level content nested inside an inline
                        # <a> tag -- confirmed live, the anchor rendered
                        # completely empty. Siblings, like the bot's own
                        # .tt-bot-head + .chat-reply, sidestep that entirely.)
                        st.markdown(
                            '<div class="tt-q-head"><span class="tt-av student">🧒</span>You</div>',
                            unsafe_allow_html=True)
                        # The card is position:sticky (see .tt-q-sticky) --
                        # while its own answer is scrolled past, it sticks to
                        # the top of the chat box. Previously an <a href=
                        # "#qa-N"> so clicking it jumped back to the top of
                        # that response -- live-reported that making it a
                        # LINK meant clicking-and-dragging to select/copy the
                        # question text instead triggered the browser's
                        # link-click behavior, so a child couldn't copy what
                        # they'd typed. Plain <div> now; still sticky, just
                        # not clickable/navigable.
                        st.markdown(
                            f'<div class="tt-q tt-q-sticky">{html.escape(q["text"])}</div>',
                            unsafe_allow_html=True)
                        if a is not None:
                            if a.get("kind") == "chat":
                                render_chat_reply(a)
                            else:
                                render_turn(a, a_idx, is_latest=(a_idx == len(msgs) - 1))

                # Rendered INSIDE chat_scroll, right after the last message,
                # not as a sibling below the box -- it used to sit below
                # (see queue_pending_turn's docstring for why generation is
                # split across two reruns in the first place), in the
                # unbounded gap between the box and the fixed ask bar. Once
                # that gap was closed (see the chat_scroll height override
                # in main_css.py), there was nowhere left for it to render
                # without overlapping the ask bar/footer. Nesting it here
                # also just reads better regardless -- a "typing…" indicator
                # belongs inside the conversation, not floating below it.
                if process_pending_turn(chat, ss.grade, ss.level):
                    history.save(chat)
                    st.rerun()

            components.html(
                f"""
                <!-- cache-buster: {len(msgs)} {time.time()} -->
                <script>
                (function () {{
                    // This component has no visible content (height=0) and
                    // nothing inside it a user could ever interact with --
                    // but the iframe Streamlit wraps it in is focusable by
                    // default, like any iframe. That meant a keyboard user
                    // tabbing through the page hit an invisible, silent tab
                    // stop with no visible focus indicator between the
                    // shortcut buttons and the ask box (U-14). Pulling it
                    // out of tab order is standard practice for a purely
                    // functional/invisible iframe like this one.
                    if (window.frameElement) {{ window.frameElement.tabIndex = -1; }}
                    function isScrollable(el) {{
                        if (!el || el.scrollHeight <= el.clientHeight) return false;
                        const style = window.getComputedStyle(el);
                        return style.overflowY === 'auto' || style.overflowY === 'scroll';
                    }}
                    function findScrollable(root) {{
                        if (isScrollable(root)) return root;
                        let best = null, bestOverhang = 0;
                        const all = root.querySelectorAll('*');
                        for (const el of all) {{
                            if (isScrollable(el)) {{
                                const overhang = el.scrollHeight - el.clientHeight;
                                if (overhang > bestOverhang) {{
                                    best = el;
                                    bestOverhang = overhang;
                                }}
                            }}
                        }}
                        return best;
                    }}
                    function scrollToLatestQuestion(tries) {{
                        const doc = window.parent.document;
                        const root = doc.querySelector('[class*="st-key-chat_scroll"]');
                        if (!root) {{
                            if (tries > 0) setTimeout(function () {{ scrollToLatestQuestion(tries - 1); }}, 100);
                            return;
                        }}
                        const scrollable = findScrollable(root);
                        if (!scrollable) {{
                            if (tries > 0) setTimeout(function () {{ scrollToLatestQuestion(tries - 1); }}, 100);
                            return;
                        }}
                        const blocks = scrollable.querySelectorAll('[data-testid="stVerticalBlockBorderWrapper"]');
                        if (blocks.length > 0) {{
                            const last = blocks[blocks.length - 1];
                            const scrollableTop = scrollable.getBoundingClientRect().top;
                            const lastTop = last.getBoundingClientRect().top;
                            scrollable.scrollTop += (lastTop - scrollableTop) - 8;
                        }} else {{
                            scrollable.scrollTop = scrollable.scrollHeight;
                        }}
                    }}
                    scrollToLatestQuestion(20);
                }})();
                </script>
                """,
                height=0,
            )

        # ---- ask bar: fixed at the bottom of the screen, above the footer ----
        # A bare st.text_input + a separate st.button does NOT submit on
        # Enter in Streamlit -- pressing Enter only commits the text_input's
        # value and reruns the script; it does not set the button's return
        # value to True. A child who types an answer and presses Enter (the
        # near-universal chat-input expectation) previously saw nothing
        # happen at all until they also clicked the small arrow button. An
        # st.form's submit button, uniquely, DOES fire on Enter when it is
        # the form's only submit button -- this is the documented fix, not a
        # cosmetic wrapper.
        ask_pending = bool(chat.get("pending_turn"))
        ask_key = f"askbox_{ss.active}_{len(msgs)}"
        with st.form(key="ask_bar", clear_on_submit=True, border=False):
            a_in, a_btn = st.columns([6, 1])
            with a_in:
                question = st.text_input(
                    "ask", key=ask_key,
                    placeholder="Type your answer, a question, or how you're thinking…",
                    label_visibility="collapsed", disabled=ask_pending,
                )
            with a_btn:
                # key="askbtn" is what lets the [class*="st-key-askbtn"]
                # rules below (circular blue button) actually match this
                # element -- without it, Streamlit never adds that class and
                # the button silently fell back to its unstyled default
                # appearance (U-09), inconsistent next to the styled input.
                ask_clicked = st.form_submit_button("↑", use_container_width=True,
                                                    disabled=ask_pending, key="askbtn")

        # Guard against a double-fire of the ask button (Enter + click landing
        # in the same script run), which was causing the same question to be
        # appended twice. We remember which widget key we last acted on and
        # skip if this exact click has already been processed.
        submit_id = f"{ask_key}:{question.strip()}"
        if ask_clicked and question.strip() and st.session_state.get("_last_submit_id") != submit_id:
            st.session_state["_last_submit_id"] = submit_id
            queue_pending_turn(chat, question.strip())
            st.rerun()

    # ---------- FIXED FOOTER ----------
    st.markdown(
        f'<div class="tt-footer">{_build_footer_scene()}'
        f'<span class="tt-footer-pill">🏆 <b>Keep Practicing!</b> &nbsp; '
        f'Solving problems every day makes you a Tiny Thinker champion! 🚀</span></div>',
        unsafe_allow_html=True,
    )

