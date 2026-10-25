import re
from typing import Any
from rustwright.sync_api import Locator, Page
from core.controller import controller


def _handle_workday_dropdown(page: Page, trigger: Locator, selector: str, val_str: str) -> bool:
    """Handle Workday popup combobox/listbox selection via search & promptOption click."""
    try:
        # Check if already has a non-placeholder value selected
        curr_text = (trigger.inner_text() or "").strip()
        if curr_text and not re.search(r"^(select|choose|select one|please select)$", curr_text, re.IGNORECASE):
            print(f"  \033[1;34m[⏭] Dropdown '{selector}' already selected ('{curr_text}'), skipping...\033[0m")
            return True
    except Exception:
        pass

    try:
        # Step 1: Click the trigger to open the popup listbox
        trigger.click(force=True)
        page.wait_for_timeout(500)

        # Step 2: Check for search box inside the opened popup listbox
        search_box = page.locator(
            "input[data-automation-id='searchBox'], "
            "[role='listbox'] input, "
            "[data-automation-id='promptSearchContainer'] input, "
            "[role='combobox'] input, "
            "input[type='search']"
        )
        if search_box.count() > 0 and search_box.first.is_visible():
            search_box.first.fill(val_str)
            page.wait_for_timeout(700)  # Allow Workday AJAX query to return promptOptions

        # Step 3: Click the matching promptOption item in the popup listbox
        # Workday renders options as data-automation-id="promptOption" or role="option"
        option_locators = [
            page.locator(f"[data-automation-id*='promptOption']:has-text('{val_str}')"),
            page.locator(f"[role='option']:has-text('{val_str}')"),
            page.locator(f"li[role='option']:has-text('{val_str}')"),
            page.locator(f"li:has-text('{val_str}')"),
        ]

        option_clicked = False
        for opt in option_locators:
            if opt.count() > 0 and opt.first.is_visible():
                opt.first.click(force=True)
                option_clicked = True
                page.wait_for_timeout(400)
                break

        # Step 4: If text match was too strict, pick the first filtered result in the listbox
        if not option_clicked:
            first_filtered = page.locator("[data-automation-id*='promptOption'], [role='option']").first
            if first_filtered.count() > 0 and first_filtered.is_visible():
                first_filtered.click(force=True)
                option_clicked = True
                page.wait_for_timeout(400)

        # Step 5: Fallback keyboard selection (ArrowDown -> Enter)
        if not option_clicked:
            page.keyboard.press("ArrowDown")
            page.wait_for_timeout(200)
            page.keyboard.press("Enter")
            page.wait_for_timeout(300)

        # Dismiss any lingering popup backdrop by pressing Escape or clicking outside
        try:
            if page.locator("[role='listbox'], [data-automation-id='promptSearchContainer']").count() > 0:
                page.keyboard.press("Escape")
                page.wait_for_timeout(200)
        except Exception:
            pass

        print(f"  \033[1;32m[✔] Dropdown '{selector}' -> '{val_str}'\033[0m")
        return True

    except Exception as e:
        print(f"  \033[1;31m[!] Error selecting dropdown '{selector}': {e}\033[0m")
        return False


def smart_fill_field(page: Page, selector: str, value: Any) -> bool:
    """Intelligently populate a form field based on tag/type with native already-filled skip."""
    if not selector or value is None:
        return False

    val_str = str(value).strip()
    try:
        loc = page.locator(selector)
        if loc.count() == 0:
            return False

        first = loc.first
        if not first.is_visible():
            return False

        try:
            first.scroll_into_view_if_needed(timeout=1000)
        except Exception:
            pass

        tag = first.evaluate("el => el.tagName.toLowerCase()")
        input_type = first.evaluate("el => (el.getAttribute('type') || '').toLowerCase()")
        role = first.evaluate("el => (el.getAttribute('role') || '').toLowerCase()")
        aria_haspopup = first.evaluate("el => (el.getAttribute('aria-haspopup') || '').toLowerCase()")

        # 1. Radio Buttons & Checkboxes
        if input_type in ("radio", "checkbox") or role in ("radio", "checkbox"):
            is_truthy = val_str.lower() in ("true", "yes", "1", "check", "checked", "on")
            is_falsy = val_str.lower() in ("false", "no", "0", "uncheck", "off")

            # Check if already in desired state (Zero token cost)
            try:
                already_checked = first.is_checked()
                if is_truthy and already_checked:
                    print(f"  \033[1;34m[⏭] Option '{selector}' already checked, skipping...\033[0m")
                    return True
                elif is_falsy and not already_checked:
                    print(f"  \033[1;34m[⏭] Option '{selector}' already unchecked, skipping...\033[0m")
                    return True
            except Exception:
                pass

            if "[value=" in selector.lower():
                first.check(force=True)
            elif input_type == "checkbox" and is_falsy:
                first.uncheck(force=True)
            else:
                first.check(force=True)

            print(f"  \033[1;32m[✔] Checked '{selector}'\033[0m")
            return True

        # 2. Native <select> elements
        if tag == "select":
            try:
                curr_sel = first.input_value()
                if curr_sel and curr_sel.strip():
                    print(f"  \033[1;34m[⏭] Select '{selector}' already has value ('{curr_sel}'), skipping...\033[0m")
                    return True
            except Exception:
                pass

            try:
                first.select_option(value=val_str, timeout=2000)
            except Exception:
                first.select_option(label=val_str, timeout=2000)
            print(f"  \033[1;32m[✔] Selected '{selector}' -> '{val_str}'\033[0m")
            return True

        # 3. Workday Custom Dropdowns & Comboboxes (buttons, comboboxes, popup triggers)
        # Often Workday selectors are: #country--country, button[data-automation-id='...'], role='combobox'
        is_dropdown = (
            role in ("combobox", "listbox")
            or aria_haspopup in ("listbox", "true")
            or tag == "button"
            or "--" in selector
            or "dropdown" in selector.lower()
            or "multiselect" in selector.lower()
        )

        if is_dropdown:
            return _handle_workday_dropdown(page, first, selector, val_str)

        # Check if the element contains an inner button or combobox trigger (e.g. div wrapper)
        inner_btn = first.locator("button, [role='combobox'], [aria-haspopup='listbox']")
        if inner_btn.count() > 0 and inner_btn.first.is_visible():
            return _handle_workday_dropdown(page, inner_btn.first, selector, val_str)

        # 4. Standard text/number/email/textarea inputs
        try:
            curr_val = first.input_value()
            if curr_val and curr_val.strip():
                print(f"  \033[1;34m[⏭] Field '{selector}' already populated ('{curr_val.strip()}'), skipping...\033[0m")
                return True
        except Exception:
            pass

        first.fill(val_str, timeout=3000)
        print(f"  \033[1;32m[✔] Filled '{selector}' -> '{val_str}'\033[0m")
        return True

    except Exception as fill_err:
        err_msg = str(fill_err)

        # If fill threw 'Element is not an <input>...', it's almost certainly a custom dropdown widget
        if "not an <input>" in err_msg or "contenteditable" in err_msg:
            try:
                first = page.locator(selector).first
                return _handle_workday_dropdown(page, first, selector, val_str)
            except Exception:
                pass

        # Fallback: click and type
        try:
            first = page.locator(selector).first
            first.click(force=True)
            first.fill(val_str, timeout=1500)
            print(f"  \033[1;32m[✔] Filled (fallback) '{selector}' -> '{val_str}'\033[0m")
            return True
        except Exception:
            pass

        print(f"  \033[1;31m[X] Could not fill '{selector}': {fill_err}\033[0m")
        return False


def fill_form_fields(page: Page, mappings: dict[str, str]) -> int:
    """Populate form fields using intelligent field handler."""
    if not mappings:
        return 0

    filled_count = 0
    print(f"\n[+] Populating {len(mappings)} detected form field(s)...")

    for selector, value in mappings.items():
        controller.check_signals()
        if controller.stop_requested or controller.skip_requested:
            break

        if smart_fill_field(page, selector, value):
            filled_count += 1

    return filled_count
