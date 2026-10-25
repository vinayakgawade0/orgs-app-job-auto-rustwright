"""Core automation package for orgs-app-job-auto-rustwright."""
from core.browser import launch_browser, navigate_to_url, safe_wait_dom, wait_for_spa_ready
from core.controller import AutomatorController, controller
from core.form_filler import fill_form_fields, smart_fill_field

__all__ = [
    "launch_browser",
    "navigate_to_url",
    "safe_wait_dom",
    "wait_for_spa_ready",
    "AutomatorController",
    "controller",
    "smart_fill_field",
    "fill_form_fields",
]
