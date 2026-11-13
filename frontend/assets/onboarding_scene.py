"""frontend/assets/onboarding_scene.py -- reusable illustrated-scene SVG
library for the onboarding/name page.
"""
from __future__ import annotations


# ===========================================================================
# ONBOARDING WORLD — reusable illustrated-scene components
# ===========================================================================
# No image/mascot assets exist anywhere in this repo (checked). Rather than
# pulling in unrelated stock art, this is a small, self-contained library of
# hand-authored inline SVGs built from one shared "critter" template --
# every forest character is the SAME base construction (head/body/eyes/
# smile) with only ears, colors and small extras swapped in, so the whole
# cast reads as one coherent species design instead of N unrelated
# drawings, AND a new animal is just a new set of arguments to
# _critter_svg(), not a new illustration from scratch. Each piece is a
# clearly named, independently swappable constant -- replacing any one
# character later (with a commissioned asset, say) means changing exactly
# one assignment below, nothing in the page layout.
def _critter_svg(body: str, head: str, ears: str, accent: str,
                 cheek: str = "#f7c3cf", extra_back: str = "", extra_front: str = "") -> str:
    return (
        '<svg viewBox="0 0 70 70" xmlns="http://www.w3.org/2000/svg">'
        f'{extra_back}{ears}'
        f'<ellipse cx="35" cy="54" rx="19" ry="14" fill="{body}"/>'
        f'<circle cx="32" cy="36" r="16" fill="{head}"/>'
        f'<circle cx="26" cy="34" r="2.3" fill="#3b2a2a"/>'
        f'<circle cx="38" cy="34" r="2.3" fill="#3b2a2a"/>'
        f'<circle cx="27" cy="33" r="0.7" fill="#fff"/><circle cx="39" cy="33" r="0.7" fill="#fff"/>'
        f'<circle cx="21" cy="40" r="3" fill="{cheek}" opacity="0.75"/>'
        f'<circle cx="43" cy="40" r="3" fill="{cheek}" opacity="0.75"/>'
        '<path d="M27,41 Q32,45 37,41" stroke="#3b2a2a" stroke-width="1.5" fill="none" stroke-linecap="round"/>'
        f'<circle cx="32" cy="38" r="1.5" fill="{accent}"/>'
        f'{extra_front}</svg>'
    )


_RABBIT_SVG = _critter_svg(
    "#f6ead9", "#fdf5ec",
    '<ellipse cx="22" cy="15" rx="6" ry="18" fill="#f6ead9"/>'
    '<ellipse cx="22" cy="17" rx="3" ry="13" fill="#f3b6c8"/>'
    '<ellipse cx="37" cy="13" rx="6" ry="18" fill="#f6ead9" transform="rotate(14 37 13)"/>'
    '<ellipse cx="37" cy="15" rx="3" ry="13" fill="#f3b6c8" transform="rotate(14 37 15)"/>',
    "#e79aa6")

_FOX_SVG = _critter_svg(
    "#f3935a", "#fbb37c",
    '<path d="M16,27 L23,7 L29,25 Z" fill="#f3935a"/><path d="M48,27 L41,7 L35,25 Z" fill="#f3935a"/>'
    '<path d="M19,27 L24,13 L28,24 Z" fill="#fff7ef"/><path d="M45,27 L40,13 L36,24 Z" fill="#fff7ef"/>',
    "#c85a2e", extra_front='<ellipse cx="32" cy="43" rx="7" ry="5" fill="#fff7ef"/>')

_BEAR_SVG = _critter_svg(
    "#b9835a", "#caa074",
    '<circle cx="17" cy="19" r="9" fill="#b9835a"/><circle cx="47" cy="19" r="9" fill="#b9835a"/>'
    '<circle cx="17" cy="19" r="4.3" fill="#8a5d3b"/><circle cx="47" cy="19" r="4.3" fill="#8a5d3b"/>',
    "#8a5d3b", extra_front='<ellipse cx="32" cy="41" rx="8" ry="6" fill="#e3c6a1"/>')

_SQUIRREL_SVG = _critter_svg(
    "#c97b4a", "#e2a164",
    '<ellipse cx="17" cy="21" rx="6" ry="10" fill="#c97b4a"/>'
    '<ellipse cx="38" cy="17" rx="6" ry="10" fill="#c97b4a" transform="rotate(18 38 17)"/>',
    "#8a4a26",
    extra_back='<path d="M45,52 Q68,48 62,20 Q58,6 43,14 Q56,18 55,34 Q55,50 40,51 Z" fill="#c97b4a"/>')

_BIRD_SVG = _critter_svg(
    "#6ea8e0", "#8dc0ee",
    '<ellipse cx="19" cy="50" rx="13" ry="8" fill="#5590c9"/>',
    "#2b5f93", extra_front='<path d="M44,35 L55,32 L45,41 Z" fill="#f5b301"/>')

_BUTTERFLY_SVG = (
    '<svg viewBox="0 0 60 50" xmlns="http://www.w3.org/2000/svg">'
    '<ellipse cx="18" cy="18" rx="15" ry="12" fill="#f5b301" opacity="0.92"/>'
    '<ellipse cx="42" cy="18" rx="15" ry="12" fill="#ff6f59" opacity="0.92"/>'
    '<ellipse cx="20" cy="33" rx="11" ry="9" fill="#ffd23f" opacity="0.92"/>'
    '<ellipse cx="40" cy="33" rx="11" ry="9" fill="#f5a623" opacity="0.92"/>'
    '<rect x="28" y="12" width="4" height="26" rx="2" fill="#5a3b22"/>'
    '<circle cx="30" cy="10" r="3.2" fill="#5a3b22"/></svg>'
)

_CLOUD_SVG = (
    '<svg viewBox="0 0 120 60" xmlns="http://www.w3.org/2000/svg">'
    '<ellipse cx="28" cy="38" rx="26" ry="17" fill="#ffffff"/>'
    '<ellipse cx="58" cy="25" rx="32" ry="23" fill="#ffffff"/>'
    '<ellipse cx="90" cy="38" rx="24" ry="16" fill="#ffffff"/>'
    '<ellipse cx="58" cy="43" rx="42" ry="14" fill="#ffffff"/></svg>'
)

_SPARKLE_SVG = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M12 0 L14.3 9.3 L24 12 L14.3 14.7 L12 24 L9.7 14.7 L0 12 L9.7 9.3 Z" fill="#ffd23f"/></svg>'
)

_TREE_SVG = (
    '<svg viewBox="0 0 60 80" xmlns="http://www.w3.org/2000/svg">'
    '<ellipse cx="30" cy="76" rx="16" ry="4" fill="#3f8a46" opacity="0.25"/>'
    '<rect x="26" y="48" width="8" height="28" rx="3" fill="#8a5a3b"/>'
    '<circle cx="30" cy="30" r="23" fill="#3fa348"/>'
    '<circle cx="14" cy="39" r="15" fill="#4fb858"/>'
    '<circle cx="46" cy="39" r="15" fill="#4fb858"/>'
    '<circle cx="30" cy="22" r="12" fill="#5fc968" opacity="0.8"/></svg>'
)

_BUSH_SVG = (
    '<svg viewBox="0 0 60 36" xmlns="http://www.w3.org/2000/svg">'
    '<ellipse cx="18" cy="22" rx="18" ry="14" fill="#4fb858"/>'
    '<ellipse cx="40" cy="20" rx="20" ry="16" fill="#3fa348"/>'
    '<ellipse cx="29" cy="16" rx="12" ry="9" fill="#5fc968" opacity="0.8"/></svg>'
)


def _flower_svg(petal: str) -> str:
    return (
        '<svg viewBox="0 0 30 34" xmlns="http://www.w3.org/2000/svg">'
        f'<g fill="{petal}"><circle cx="15" cy="7" r="6"/><circle cx="15" cy="19" r="6"/>'
        f'<circle cx="7" cy="13" r="6"/><circle cx="23" cy="13" r="6"/></g>'
        '<circle cx="15" cy="13" r="5.5" fill="#ffd23f"/>'
        '<rect x="13.5" y="18" width="3" height="14" fill="#4a8f45"/></svg>'
    )


def _math_sign_svg(symbol: str) -> str:
    return (
        '<svg viewBox="0 0 50 62" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="22" y="26" width="6" height="36" rx="2" fill="#a9754a"/>'
        '<rect x="3" y="3" width="44" height="28" rx="7" fill="#e9b872" stroke="#a9754a" stroke-width="2"/>'
        f'<text x="25" y="25" font-family="Baloo 2, sans-serif" font-size="22" font-weight="800" '
        f'fill="#5a3b22" text-anchor="middle">{symbol}</text></svg>'
    )


_MOUNTAIN_SVG = (
    '<svg viewBox="0 0 400 100" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M0,100 L60,55 L105,78 L155,45 L210,78 L260,58 L315,82 L365,60 L400,78 V100 Z" '
    'fill="#a3add8" opacity="0.75"/>'
    '<path d="M155,45 L170,62 L140,62 Z" fill="#ffffff" opacity="0.85"/>'
    '<path d="M365,60 L375,70 L355,70 Z" fill="#ffffff" opacity="0.85"/></svg>'
)

_SUN_SVG = (
    '<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">'
    '<g stroke="#ffd23f" stroke-width="5" stroke-linecap="round">'
    '<line x1="50" y1="4" x2="50" y2="16"/><line x1="50" y1="84" x2="50" y2="96"/>'
    '<line x1="4" y1="50" x2="16" y2="50"/><line x1="84" y1="50" x2="96" y2="50"/>'
    '<line x1="17" y1="17" x2="25" y2="25"/><line x1="75" y1="75" x2="83" y2="83"/>'
    '<line x1="83" y1="17" x2="75" y2="25"/><line x1="25" y1="75" x2="17" y2="83"/></g>'
    '<circle cx="50" cy="50" r="28" fill="#ffd23f"/>'
    '<circle cx="42" cy="46" r="3.2" fill="#8a5d1f"/><circle cx="58" cy="46" r="3.2" fill="#8a5d1f"/>'
    '<path d="M40,58 Q50,66 60,58" stroke="#8a5d1f" stroke-width="2.6" fill="none" stroke-linecap="round"/>'
    '<circle cx="34" cy="54" r="3.5" fill="#ffb37a" opacity="0.7"/>'
    '<circle cx="66" cy="54" r="3.5" fill="#ffb37a" opacity="0.7"/></svg>'
)


def _cube_svg(symbol: str, top: str, left: str, right: str) -> str:
    """A small pseudo-3D numbered/symbol block -- flat shapes only (three
    parallelogram-ish faces via simple paths), no gradients, staying in the
    same flat-vector family as the rest of the cast."""
    return (
        '<svg viewBox="0 0 60 60" xmlns="http://www.w3.org/2000/svg">'
        f'<path d="M30,2 L56,14 L30,26 L4,14 Z" fill="{top}"/>'
        f'<path d="M4,14 L30,26 L30,58 L4,46 Z" fill="{left}"/>'
        f'<path d="M56,14 L30,26 L30,58 L56,46 Z" fill="{right}"/>'
        f'<text x="30" y="19" font-family="Baloo 2, sans-serif" font-size="12" font-weight="800" '
        f'fill="#5a3b22" text-anchor="middle">{symbol}</text></svg>'
    )


def _signpost_svg(words: list[str]) -> str:
    """A stacked wooden signpost -- one plank per word, widest/topmost
    first. Shares the same wood-and-plank visual language as
    _math_sign_svg() (one post, rounded tan planks) so the two read as the
    same prop family rather than two unrelated sign styles."""
    plank_h, gap, top0 = 22, 6, 4
    planks = "".join(
        f'<rect x="2" y="{top0 + i * (plank_h + gap)}" width="76" height="{plank_h}" rx="6" '
        f'fill="#e9b872" stroke="#a9754a" stroke-width="2"/>'
        f'<text x="40" y="{top0 + i * (plank_h + gap) + plank_h / 2 + 5}" '
        f'font-family="Baloo 2, sans-serif" font-size="12" font-weight="800" fill="#5a3b22" '
        f'text-anchor="middle">{w}</text>'
        for i, w in enumerate(words)
    )
    post_top = top0 + len(words) * (plank_h + gap)
    return (
        f'<svg viewBox="0 0 80 {post_top + 50}" xmlns="http://www.w3.org/2000/svg">'
        f'{planks}<rect x="35" y="{post_top}" width="8" height="48" rx="3" fill="#a9754a"/></svg>'
    )


_ICON_PERSON_SVG = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<circle cx="12" cy="8" r="5" fill="#e08a1e"/>'
    '<path d="M3,22 Q3,13 12,13 Q21,13 21,22 Z" fill="#e08a1e"/></svg>'
)
_ICON_CAP_SVG = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M12,3 L22,8 L12,13 L2,8 Z" fill="#2f4d80"/>'
    '<path d="M6,10.3 V15 Q6,18 12,18 Q18,18 18,15 V10.3 L12,13 Z" fill="#3a5c99"/>'
    '<circle cx="22" cy="8" r="1.6" fill="#2f4d80"/><line x1="22" y1="8" x2="22" y2="15" '
    'stroke="#2f4d80" stroke-width="1.4"/></svg>'
)

_HILL_BACK_SVG = (
    '<svg viewBox="0 0 400 120" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M0,80 Q100,30 200,55 T400,40 V120 H0 Z" fill="#a9dd97"/></svg>'
)
_HILL_FRONT_SVG = (
    '<svg viewBox="0 0 400 120" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M0,95 Q120,45 250,72 T400,55 V120 H0 Z" fill="#7bcb64"/></svg>'
)
_GRASS_SVG = (
    '<svg viewBox="0 0 400 70" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M0,32 Q100,4 200,24 T400,14 V70 H0 Z" fill="#4fb84a"/></svg>'
)
# A winding stepping-stone path climbing from the bottom edge toward the
# card -- the classic "follow the trail into the adventure" device from
# the reference imagery, built from the same simple ellipse vocabulary as
# everything else here.
_PATH_SVG = (
    '<svg viewBox="0 0 120 260" xmlns="http://www.w3.org/2000/svg">'
    '<ellipse cx="60" cy="250" rx="30" ry="10" fill="#e3cd9c"/>'
    '<ellipse cx="50" cy="214" rx="24" ry="8" fill="#e3cd9c"/>'
    '<ellipse cx="66" cy="180" rx="20" ry="7" fill="#e3cd9c"/>'
    '<ellipse cx="48" cy="148" rx="17" ry="6" fill="#e3cd9c"/>'
    '<ellipse cx="62" cy="118" rx="14" ry="5" fill="#e3cd9c"/>'
    '<ellipse cx="60" cy="250" rx="30" ry="10" fill="none" stroke="#c9ab6c" stroke-width="2" opacity="0.5"/>'
    '<ellipse cx="50" cy="214" rx="24" ry="8" fill="none" stroke="#c9ab6c" stroke-width="2" opacity="0.5"/>'
    '<ellipse cx="66" cy="180" rx="20" ry="7" fill="none" stroke="#c9ab6c" stroke-width="2" opacity="0.5"/>'
    '<ellipse cx="48" cy="148" rx="17" ry="6" fill="none" stroke="#c9ab6c" stroke-width="2" opacity="0.5"/>'
    '<ellipse cx="62" cy="118" rx="14" ry="5" fill="none" stroke="#c9ab6c" stroke-width="2" opacity="0.5"/></svg>'
)

# The hero -- Math Buddy, the SAME character that greets the child
# throughout the actual chat (🤖, gold/orange, see .tt-av.bot) rather than
# a second, unrelated "Tiny Thinker" character -- so the one who welcomes
# you into the world is the one who's still there once the math starts.
# Noticeably larger than the forest critters and drawn in more detail, with
# a graduation cap, a backpack and a glowing chest badge -- "a guide into
# the math world," not just a logo -- per "Tiny Thinker should be the
# hero."
_MASCOT_SVG = (
    '<svg viewBox="0 0 160 190" xmlns="http://www.w3.org/2000/svg">'
    # backpack (peeks out behind the body, drawn first so the body overlaps it)
    '<rect x="20" y="108" width="22" height="46" rx="10" fill="#1f57d6"/>'
    '<rect x="24" y="116" width="14" height="10" rx="4" fill="#2f6bea"/>'
    # antenna
    '<rect x="76" y="20" width="8" height="18" rx="4" fill="#d9890a"/>'
    '<path d="M80 8 L85 17 L95 18 L87 25 L90 35 L80 29 L70 35 L73 25 L65 18 L75 17 Z" fill="#ffd23f"/>'
    # head
    '<rect x="35" y="42" width="90" height="74" rx="30" fill="#f5a623"/>'
    '<rect x="48" y="56" width="64" height="44" rx="18" fill="#fff7ea"/>'
    '<circle cx="68" cy="78" r="6.5" fill="#2b3a67"/><circle cx="94" cy="78" r="6.5" fill="#2b3a67"/>'
    '<circle cx="70.3" cy="75.5" r="1.8" fill="#fff"/><circle cx="96.3" cy="75.5" r="1.8" fill="#fff"/>'
    '<path d="M68,90 Q80,98 92,90" stroke="#2b3a67" stroke-width="3" fill="none" stroke-linecap="round"/>'
    '<circle cx="54" cy="86" r="5" fill="#ff9d7a" opacity="0.55"/>'
    '<circle cx="106" cy="86" r="5" fill="#ff9d7a" opacity="0.55"/>'
    # graduation cap, tilted jauntily on top of the head
    '<g transform="rotate(-8 80 32)">'
    '<rect x="68" y="26" width="24" height="10" rx="2" fill="#2f4d80"/>'
    '<path d="M80,6 L118,22 L80,38 L42,22 Z" fill="#3a5c99"/>'
    '<circle cx="118" cy="22" r="2.6" fill="#ffd23f"/>'
    '<line x1="118" y1="22" x2="114" y2="40" stroke="#ffd23f" stroke-width="2.4"/>'
    '<circle cx="114" cy="41" r="3" fill="#ffd23f"/></g>'
    # body + glowing chest badge
    '<rect x="45" y="116" width="70" height="56" rx="24" fill="#ffd23f"/>'
    '<circle cx="80" cy="144" r="19" fill="#fff2cf" opacity="0.9"/>'
    '<rect x="64" y="132" width="32" height="24" rx="10" fill="#fff7ea"/>'
    '<text x="80" y="151" font-family="Baloo 2, sans-serif" font-size="20" font-weight="800" '
    'fill="#1f57d6" text-anchor="middle">+</text>'
    '<ellipse cx="38" cy="136" rx="9" ry="16" fill="#f5a623"/>'
    '<g class="tt-wave-arm"><ellipse cx="124" cy="118" rx="9" ry="17" fill="#f5a623"/></g>'
    '<rect x="55" y="168" width="16" height="14" rx="6" fill="#d9890a"/>'
    '<rect x="89" y="168" width="16" height="14" rx="6" fill="#d9890a"/></svg>'
)


def _deco(svg: str, cls: str, style: str) -> str:
    """One positioned, non-interactive scene element. pointer-events:none
    on every piece is load-bearing -- nothing decorative may ever intercept
    a click/tap meant for the real form controls underneath (rule 14)."""
    return f'<div class="tt-deco {cls}" style="{style};pointer-events:none;">{svg}</div>'


def _build_onboarding_scene() -> str:
    """Assembles the full illustrated backdrop as one block of fixed,
    absolutely-positioned, non-interactive pieces -- entirely decorative,
    entirely behind the real card (z-index below it). Desktop-only pieces
    (the forest critters, trees, bushes) are hidden at narrow widths by
    MAIN... by this page's own <style> block below, not by omitting them
    here, so the same markup serves every breakpoint."""
    parts = [
        _deco(_MOUNTAIN_SVG, "tt-mountain tt-hide-sm", "bottom:33vh;left:0;width:100%;height:11vh"),
        _deco(_HILL_BACK_SVG, "tt-hillback", "bottom:16vh;left:0;width:100%;height:22vh"),
        _deco(_HILL_FRONT_SVG, "tt-hillfront", "bottom:9vh;left:0;width:100%;height:20vh"),
        _deco(_GRASS_SVG, "tt-grass", "bottom:0;left:0;width:100%;height:11vh"),
        _deco(_PATH_SVG, "tt-path tt-hide-md", "bottom:0;left:calc(50% - 55px);width:110px;height:26vh"),

        _deco(_SUN_SVG, "tt-sun", "top:5%;right:6%;width:64px"),
        _deco(_CLOUD_SVG, "tt-cloud tt-drift-a tt-cloud-near-mascot", "top:8%;left:10%;width:110px"),
        _deco(_CLOUD_SVG, "tt-cloud tt-drift-b", "top:16%;right:18%;width:74px"),
        _deco(_SPARKLE_SVG, "tt-sparkle tt-twinkle-a", "top:10%;left:30%;width:18px"),
        _deco(_SPARKLE_SVG, "tt-sparkle tt-twinkle-b", "top:24%;right:30%;width:14px"),

        _deco(_TREE_SVG, "tt-tree tt-hide-sm", "bottom:19vh;left:3%;width:70px"),
        _deco(_TREE_SVG, "tt-tree tt-hide-sm", "bottom:21vh;right:5%;width:56px"),
        _deco(_BUSH_SVG, "tt-bush tt-hide-sm", "bottom:10vh;left:16%;width:58px"),
        _deco(_BUSH_SVG, "tt-bush tt-hide-sm", "bottom:11vh;right:17%;width:50px"),

        _deco(_math_sign_svg("+"), "tt-sign tt-hide-sm", "bottom:10.5vh;left:8%;width:40px"),
        _deco(_math_sign_svg("×"), "tt-sign tt-hide-sm", "bottom:11vh;right:9%;width:40px"),
        _deco(_signpost_svg(["LEARN", "PLAY", "GROW"]), "tt-signpost tt-hide-md", "bottom:9vh;right:33%;width:52px"),
        _deco(_cube_svg("3", "#8dc7f5", "#4f9fd9", "#2f7cb8"), "tt-cube tt-bob-a tt-hide-md", "bottom:11.5vh;left:30%;width:38px"),
        _deco(_cube_svg("÷", "#d7a8f0", "#b571e0", "#9452c2"), "tt-cube tt-bob-b tt-hide-md", "bottom:10vh;right:46%;width:34px"),

        _deco(_flower_svg("#ff6f59"), "tt-flower", "bottom:2vh;left:6%;width:22px"),
        _deco(_flower_svg("#ffd23f"), "tt-flower", "bottom:3.2vh;left:13%;width:18px"),
        _deco(_flower_svg("#e86fd0"), "tt-flower tt-hide-sm", "bottom:1vh;left:22%;width:16px"),
        _deco(_flower_svg("#f5b301"), "tt-flower tt-hide-sm", "bottom:1.5vh;right:10%;width:20px"),
        _deco(_flower_svg("#ff9d7a"), "tt-flower tt-hide-sm", "bottom:3vh;right:17%;width:18px"),
        _deco(_flower_svg("#7fd4e0"), "tt-flower tt-hide-sm", "bottom:1vh;right:24%;width:16px"),

        _deco(_RABBIT_SVG, "tt-critter tt-bob-a tt-hide-sm", "bottom:9vh;left:5%;width:64px"),
        _deco(_FOX_SVG, "tt-critter tt-bob-b tt-hide-md", "bottom:9.5vh;right:6%;width:62px"),
        _deco(_SQUIRREL_SVG, "tt-critter tt-bob-a tt-hide-md", "bottom:19vh;left:9%;width:50px"),
        _deco(_BEAR_SVG, "tt-critter tt-bob-b tt-hide-md", "bottom:9vh;right:22%;width:58px"),
        _deco(_BIRD_SVG, "tt-critter tt-fly tt-hide-md", "top:16%;left:20%;width:46px"),
        _deco(_BUTTERFLY_SVG, "tt-critter tt-flutter tt-hide-sm", "top:38%;right:24%;width:40px"),
    ]
    return "".join(parts)


# ===========================================================================
# MAIN CHAT PAGE -- the same world, painted into the fixed header/footer
# bands instead of floating over a single centred card. Deliberately reuses
# the onboarding page's own asset vocabulary (sun/clouds/bird/hills/grass/
# flowers/critters) so the working chat page still reads as the same place
# -- the one deliberate omission is _MASCOT_SVG (the graduation-cap hero):
# it stays onboarding's own welcome, not a fixture behind every chat turn.
# ===========================================================================
def _abs(svg: str, cls: str, style: str) -> str:
    """Like _deco(), but position:absolute against its own nearest
    positioned ancestor (a fixed header/footer bar) instead of
    position:fixed against the whole viewport -- for decorations painted
    INSIDE a bar rather than floating independently over the page."""
    return f'<div class="tt-abs-deco {cls}" style="{style};pointer-events:none;">{svg}</div>'


def _build_header_scene() -> str:
    """Decorative sky-band artwork for the main page's app bar.

    The brand now sits CENTERED in the bar (see .tt-appbar's grid layout in
    main_css.py), so every piece here is deliberately kept out of the
    roughly 35%-65% horizontal band around center -- clustered toward the
    two edges instead, where it adds texture without competing with the
    logo for attention. Sized for a half-height band (see --tt-header-h)."""
    return "".join([
        _abs(_SUN_SVG, "tt-h-sun", "left:3%;top:7px;width:28px"),
        _abs(_CLOUD_SVG, "tt-h-cloud tt-drift-a tt-hide-sm", "left:17%;top:10px;width:34px"),
        _abs(_CLOUD_SVG, "tt-h-cloud tt-drift-b tt-hide-md", "right:16%;top:6px;width:30px"),
        _abs(_BIRD_SVG, "tt-h-bird tt-fly tt-hide-md", "right:26%;top:18px;width:18px"),
        _abs(_TREE_SVG, "tt-h-tree tt-hide-md", "bottom:-4px;left:0.5%;width:26px"),
        _abs(_TREE_SVG, "tt-h-tree tt-hide-md", "bottom:-4px;right:1%;width:22px"),
        _abs(_HILL_FRONT_SVG, "tt-h-hill", "bottom:-1px;left:0;width:100%;height:10px"),
    ])


def _build_footer_scene() -> str:
    """Decorative ground-band artwork for the main page's footer strip --
    a fuller meadow than the first pass (more flowers, a second critter),
    sized for the half-height band (see --tt-footer-h) and kept clear of
    the centered "Keep Practicing" pill's own horizontal space."""
    return "".join([
        _abs(_flower_svg("#ff6f59"), "tt-f-flower tt-hide-sm", "bottom:4px;left:4%;width:12px"),
        _abs(_flower_svg("#ffd23f"), "tt-f-flower tt-hide-sm", "bottom:9px;left:8%;width:10px"),
        _abs(_flower_svg("#e86fd0"), "tt-f-flower tt-hide-md", "bottom:3px;left:13%;width:11px"),
        _abs(_SQUIRREL_SVG, "tt-f-critter tt-hide-md", "bottom:-6px;left:20%;width:26px"),
        _abs(_RABBIT_SVG, "tt-f-critter tt-hide-md", "bottom:-4px;right:6%;width:30px"),
        _abs(_flower_svg("#7fd4e0"), "tt-f-flower tt-hide-sm", "bottom:7px;right:16%;width:11px"),
        _abs(_flower_svg("#f5b301"), "tt-f-flower tt-hide-md", "bottom:3px;right:22%;width:12px"),
        _abs(_flower_svg("#ff9d7a"), "tt-f-flower tt-hide-sm", "bottom:10px;right:28%;width:10px"),
    ])

