"""
templates/__init__.py – Quizzaro Template Dispatcher
=====================================================
Single import point used by video/video_composer.py to route a template
name (e.g. "multiple_choice") to the correct drawing functions without
a long if/elif chain scattered across the renderer.

Usage:
    from templates import get_template_module
    tmpl = get_template_module("multiple_choice")
    img  = tmpl.draw_question_phase(img, ...)
    img  = tmpl.draw_answer_phase(img, ...)

Every module exposes exactly two public functions:
    draw_question_phase(img, ...) -> PIL.Image
    draw_answer_phase(img, ...)   -> PIL.Image

Argument signatures vary slightly per template (some need wrong_answers,
some need fun_fact). video_composer.py calls them via **kwargs so
unused kwargs are silently ignored.
"""

from __future__ import annotations

import importlib
from types import ModuleType

_REGISTRY: dict[str, str] = {
    "true_false":       "templates.true_false",
    "multiple_choice":  "templates.multiple_choice",
    "direct_question":  "templates.direct_question",
    "guess_answer":     "templates.guess_answer",
    "quick_challenge":  "templates.quick_challenge",
    "only_geniuses":    "templates.only_geniuses",
    "memory_test":      "templates.memory_test",
    "visual_question":  "templates.visual_question",
}


def get_template_module(name: str) -> ModuleType:
    """
    Return the module for *name*. Raises ValueError for unknown templates.
    Modules are loaded lazily and cached by Python's import machinery.
    """
    module_path = _REGISTRY.get(name)
    if not module_path:
        raise ValueError(
            f"Unknown template '{name}'. Available: {list(_REGISTRY.keys())}"
        )
    return importlib.import_module(module_path)


def all_template_names() -> list[str]:
    """Return the list of all registered template names."""
    return list(_REGISTRY.keys())
