"""frontend/styles/scene_css.py -- shared CSS for the illustrated-scene SVG
library (frontend/assets/onboarding_scene.py): positioning classes, drift/
bob/fly/flutter animations, and the mascot's wave. Used by both the
onboarding page (fixed, viewport-relative decorations) and the main chat
page (absolute decorations painted inside its header/footer bands) so the
two pages' "world" reads as one coherent place instead of two unrelated
implementations.
"""
from __future__ import annotations

SCENE_CSS = """
<style>
.tt-deco { position: fixed; }
.tt-deco svg { display:block; width:100%; height:auto; }
/* Like .tt-deco, but positioned relative to its own nearest positioned
   ancestor (a fixed header/footer bar) instead of the viewport -- used for
   decorations painted INSIDE a fixed bar rather than floating independently
   over the whole page. */
.tt-abs-deco { position: absolute; }
.tt-abs-deco svg { display:block; width:100%; height:auto; }

@media (prefers-reduced-motion: no-preference) {
    .tt-drift-a { animation: tt-drift 9s ease-in-out infinite; }
    .tt-drift-b { animation: tt-drift 12s ease-in-out infinite 1.2s; }
    .tt-twinkle-a { animation: tt-twinkle 2.4s ease-in-out infinite; }
    .tt-twinkle-b { animation: tt-twinkle 3.1s ease-in-out infinite .6s; }
    .tt-bob-a { animation: tt-bob 3.6s ease-in-out infinite; }
    .tt-bob-b { animation: tt-bob 4.2s ease-in-out infinite .5s; }
    .tt-fly { animation: tt-fly 7s ease-in-out infinite; }
    .tt-flutter { animation: tt-flutter 5s ease-in-out infinite; }
    .tt-wave-arm { animation: tt-wave 1.6s ease-in-out infinite; }
    .tt-speech { animation: tt-pop .4s ease-out .3s both; }
}
/* Single transform source (this class only -- the ellipse inside it is left
   unrotated in the SVG itself) so the static resting angle and the animated
   wave can never fight each other -- see _MASCOT_SVG's own comment for why
   this is one element/one transform-origin instead of two nested ones. */
.tt-wave-arm { transform-origin: 124px 118px; transform: rotate(-20deg); transform-box: fill-box; }
@keyframes tt-drift { 0%,100%{transform:translateX(0)} 50%{transform:translateX(16px)} }
@keyframes tt-twinkle { 0%,100%{opacity:0.35} 50%{opacity:1} }
@keyframes tt-bob { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-7px)} }
@keyframes tt-fly { 0%,100%{transform:translate(0,0)} 50%{transform:translate(14px,-10px)} }
@keyframes tt-flutter { 0%,100%{transform:translate(0,0) rotate(0deg)} 50%{transform:translate(-10px,-14px) rotate(-8deg)} }
@keyframes tt-wave { 0%,100%{transform:rotate(-20deg)} 50%{transform:rotate(2deg)} }
@keyframes tt-pop { 0%{opacity:0;transform:scale(.7) translateY(6px)} 100%{opacity:1;transform:scale(1) translateY(0)} }
</style>
"""
