"""frontend/page_script.py -- run a small script in the app page.

Built on st.components.v2, which replaces the deprecated
st.components.v1.html. The script runs in the page itself rather than in a
hidden iframe, so it works on `document` directly, and there is no invisible
iframe left in the page for a keyboard user to tab into.
"""
from __future__ import annotations

import streamlit as st

_components: dict[str, object] = {}


def run(name: str, js_body: str, data: dict | None = None) -> None:
    """Run js_body in the page, with `data` in scope. It runs on first
    render and again whenever `data` changes."""
    component = _components.get(name)
    if component is None:
        component = st.components.v2.component(
            name, js="export default function(component) {\n"
                     "    const { data } = component;\n" + js_body + "\n}")
        _components[name] = component
    component(key=name, data=data or {})
