import re
from typing import Any
from rustwright.sync_api import Page
from core.controller import controller


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

        # 3. Workday Custom Dropdowns & Comboboxes (e.g. #country--country, role='combobox', button)
        if role == "combobox" or tag == "button" or "--" in selector:
            try:
                curr_text = (first.inner_text() or "").strip()
                if curr_text and not re.search(r"^(select|choose|select one|please select)$", curr_text, re.IGNORECASE):
                    print(f"  \033[1;34m[⏭] Dropdown '{selector}' already selected ('{curr_text}'), skipping...\033[0m")
                    return True
            except Exception:
                pass

            first.click(force=True)
            page.wait_for_timeout(400)

            # Check if popup search box opened
            search_box = page.locator("input[data-automation-id='searchBox'], [role='combobox'] input, [role='listbox'] input, input[type='search']")
            if search_box.count() > 0 and search_box.first.is_visible():
                search_box.first.fill(val_str)
                page.wait_for_timeout(500)
                page.keyboard.press("Enter")
            else:
                opt = page.locator(f"[role='option']:has-text('{val_str}'), li:has-text('{val_str}'), [data-automation-id*='promptOption']:has-text('{val_str}')")
                if opt.count() > 0 and opt.first.is_visible():
                    opt.first.click(force=True)
                else:
                    page.keyboard.type(val_str)
                    page.wait_for_timeout(300)
                    page.keyboard.press("Enter")

            print(f"  \033[1;32m[✔] Custom Dropdown '{selector}' -> '{val_str}'\033[0m")
            return True

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
