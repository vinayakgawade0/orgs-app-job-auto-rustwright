import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

# Ensure Windows consoles don't crash on UTF-8 characters
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from rustwright.sync_api import Locator, Page, sync_playwright
from controller import controller
from dom_analyzer import analyze_dom, get_active_provider_info, load_dotenv, load_profile

# Auto-load .env configuration
load_dotenv()


def load_job_urls(arg_target: Optional[str] = None) -> list[str]:
    """Load job URLs from a direct CLI argument or from plaintext jobs_links.txt."""
    # 1. Direct URL passed via CLI
    if arg_target and (arg_target.startswith("http://") or arg_target.startswith("https://")):
        print(f"\033[1;36m[+] Target URL provided via CLI:\033[0m {arg_target}")
        return [arg_target]

    # 2. File path (defaults to jobs_links.txt)
    target_file = Path(arg_target) if arg_target else Path("jobs_links.txt")

    if not target_file.is_file():
        print(f"\n\033[1;31m[-] Error: File not found: '{target_file}'\033[0m")
        print("Please create 'jobs_links.txt' with one job URL per line.\n")
        sys.exit(1)

    try:
        content = target_file.read_text(encoding="utf-8")
        urls = [
            line.strip()
            for line in content.splitlines()
            if line.strip() and not line.strip().startswith("#") and line.strip().startswith("http")
        ]
        if urls:
            print(f"\033[1;32m[+] Loaded {len(urls)} job URL(s) from:\033[0m {target_file}")
            return urls
    except Exception as e:
        print(f"[-] Error reading {target_file}: {e}")

    print(f"\n\033[1;31m[-] Error: No valid URLs found in '{target_file}'.\033[0m")
    print("Please add at least one job link starting with http:// or https:// (one per line).\n")
    sys.exit(1)


def safe_wait_dom(page: Page, settle_ms: int = 1500) -> None:
    """Wait for DOM content to settle without hanging on infinite background network telemetry."""
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(settle_ms)


def wait_for_spa_ready(page: Page, timeout_sec: int = 15) -> None:
    """Wait for client-side Single Page Application (Workday / React) to render real content and title."""
    start_time = time.time()
    print("[*] Waiting for career portal to render (Workday SPA hydration)...")

    while time.time() - start_time < timeout_sec:
        title = page.title()
        if title and title.strip():
            break

        try:
            has_content = page.locator(
                "[data-automation-id='jobPostingHeader'], "
                "[data-automation-id='adventureButton'], "
                "main, article, h1, h2, form, input"
            ).count()
            if has_content > 0:
                break
        except Exception:
            pass

        page.wait_for_timeout(500)

    page.wait_for_timeout(1500)
    print(f"[+] Portal ready: '{page.title()}' ({page.url})")


def navigate_to_url(page: Page, url: str) -> bool:
    """Navigate to target URL using domcontentloaded and wait for SPA hydration."""
    print(f"\n[->] Navigating to: {url}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        wait_for_spa_ready(page)
        return True
    except Exception as e:
        curr_url = page.url or ""
        if curr_url and curr_url != "about:blank":
            print(f"\033[1;33m[!] Telemetry slow, but DOM loaded: '{page.title()}'\033[0m")
            wait_for_spa_ready(page)
            return True

        print(f"\033[1;31m[X] Navigation timeout or error: {e}\033[0m")
        controller.is_paused = True
        controller.wait_if_paused(
            reason=f"Navigation timeout while loading portal ({e}).",
            details=[f"URL: {url}", "Portal took too long to respond or background requests blocked."],
            action="Check the Chromium window. Refresh if needed, then press [Enter] or [R]."
        )
        return False


def check_and_click_initial_apply_button(page: Page) -> bool:
    """If on a job description page (e.g. Workday/Greenhouse), click 'Apply' or 'Apply Manually'."""
    try:
        apply_selectors = [
            "[data-automation-id='adventureButton']",  # Workday main Apply button
            "a[data-automation-id='applyManually']",    # Workday Apply Manually
            "button[data-automation-id='applyManually']",
            "a:has-text('Apply Manually')",
            "button:has-text('Apply Manually')",
            "a:has-text('Apply Now')",
            "button:has-text('Apply Now')",
            "a:has-text('Apply')",
            "button:has-text('Apply')",
        ]

        # Wait up to 8s for Apply button to appear
        for _ in range(16):
            if page.locator("input[type='password']").count() > 0:
                return False
            if page.locator("input:not([type='hidden'])").count() >= 3:
                return False

            found_loc = None
            for sel in apply_selectors:
                try:
                    loc = page.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible():
                        found_loc = loc.first
                        break
                except Exception:
                    continue

            if found_loc:
                btn_text = (found_loc.inner_text() or "Apply").strip()
                print(f"\033[1;36m[+] Job Description detected. Clicking '{btn_text}' to enter application...\033[0m")
                found_loc.click()
                safe_wait_dom(page, settle_ms=2500)

                # Prefer 'Autofill with Resume' if available, otherwise fallback to 'Apply Manually'
                try:
                    autofill_loc = page.locator(
                        "a[data-automation-id='autofillWithResume'], button[data-automation-id='autofillWithResume'], "
                        "a:has-text('Autofill with Resume'), button:has-text('Autofill with Resume'), "
                        "a:has-text('Apply with Resume'), button:has-text('Apply with Resume')"
                    )
                    resume_path = Path("data/resume.pdf").resolve()

                    if autofill_loc.count() > 0 and autofill_loc.first.is_visible() and resume_path.is_file():
                        print("\033[1;36m[+] Selecting 'Autofill with Resume' option...\033[0m")
                        autofill_loc.first.click()
                        safe_wait_dom(page, settle_ms=2500)

                        # If immediate file upload modal appears, attach resume
                        file_inp = page.locator("input[type='file']")
                        if file_inp.count() > 0:
                            print(f"[*] Uploading resume for autofill: {resume_path.name}...")
                            file_inp.first.set_input_files(str(resume_path))
                            safe_wait_dom(page, settle_ms=2500)

                            cont_btn = page.locator("button:has-text('Continue'), button:has-text('Next'), [data-automation-id='bottom-navigation-next-button']")
                            if cont_btn.count() > 0 and cont_btn.first.is_visible():
                                cont_btn.first.click()
                                safe_wait_dom(page, settle_ms=2500)
                    else:
                        manual_loc = page.locator("a[data-automation-id='applyManually'], button:has-text('Apply Manually'), a:has-text('Apply Manually')")
                        if manual_loc.count() > 0 and manual_loc.first.is_visible():
                            print("\033[1;36m[+] Selecting 'Apply Manually' option...\033[0m")
                            manual_loc.first.click()
                            safe_wait_dom(page, settle_ms=2500)
                except Exception as opt_err:
                    print(f"[-] Note selecting apply option: {opt_err}")

                return True

            page.wait_for_timeout(500)

    except Exception as e:
        print(f"[-] Notice checking apply button: {e}")
    return False


def check_page_errors_or_required(page: Page) -> list[str]:
    """Identify ONLY mandatory unfilled fields or active validation errors."""
    unresolved: list[str] = []

    try:
        # 1. Check for visible error messages on the page
        error_selectors = [
            "[data-automation-id='errorBanner']",
            "[data-automation-id='errorMessage']",
            "[aria-invalid='true']",
            ".error-message",
            ".field-error",
            "[role='alert']",
        ]
        for sel in error_selectors:
            loc = page.locator(sel)
            for i in range(loc.count()):
                el = loc.nth(i)
                if el.is_visible():
                    txt = (el.inner_text() or "").strip()
                    if txt and len(txt) < 150 and txt not in unresolved:
                        unresolved.append(f"Error Banner: '{txt}'")

        # 2. Check for empty mandatory inputs (required, aria-required, or label with *)
        inputs = page.locator("input:not([type='hidden']):not([type='submit']):not([type='button']), textarea, select")
        for i in range(inputs.count()):
            el = inputs.nth(i)
            if not el.is_visible():
                continue

            is_required = (
                el.get_attribute("required") is not None
                or el.get_attribute("aria-required") == "true"
                or el.get_attribute("aria-invalid") == "true"
            )

            el_id = el.get_attribute("id") or ""
            el_name = el.get_attribute("name") or ""
            placeholder = el.get_attribute("placeholder") or ""
            aria_label = el.get_attribute("aria-label") or ""

            # Check label text for asterisk
            label_text = ""
            if el_id:
                try:
                    lbl = page.locator(f"label[for='{el_id}']")
                    if lbl.count() > 0:
                        label_text = lbl.first.inner_text().strip()
                except Exception:
                    pass

            if "*" in label_text or "required" in label_text.lower():
                is_required = True

            # If mandatory, check if currently empty
            if is_required:
                try:
                    tag = el.evaluate("e => e.tagName.toLowerCase()")
                    val = el.input_value() if tag in ("input", "textarea") else ""
                    if not val or not val.strip():
                        display_name = label_text or aria_label or placeholder or el_name or el_id or f"<{tag}>"
                        hint = f"Mandatory field required: '{display_name}'"
                        if hint not in unresolved:
                            unresolved.append(hint)
                except Exception:
                    pass

            if len(unresolved) >= 6:
                break

    except Exception:
        pass

    return unresolved


def smart_fill_field(page: Page, selector: str, value: Any) -> bool:
    """Intelligently populate form fields, handling radios, checkboxes, custom comboboxes, and text."""
    val_str = str(value).strip()
    try:
        loc = page.locator(selector)
        if loc.count() == 0:
            return False

        first = loc.first
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

            # Check if already in desired state
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


def check_review_or_submit_page(page: Page) -> Optional[str]:
    """Detect if current page is a Review, Summary, or Final Submit page."""
    review_heading_regex = re.compile(
        r"(review(\s+your)?\s+application|review\s*(&|and)\s*submit|review\s+details|summary\s+and\s+review)",
        re.IGNORECASE,
    )
    for tag in ["h1", "h2", "h3", "h4", "legend", "[role='heading']"]:
        try:
            elements = page.locator(tag)
            for i in range(elements.count()):
                el = elements.nth(i)
                if el.is_visible():
                    text = el.inner_text().strip()
                    if review_heading_regex.search(text):
                        return f"Review heading: '{text}'"
        except Exception:
            continue

    submit_patterns = [
        re.compile(r"^(submit\s+application|submit|finish|complete\s+application)$", re.IGNORECASE),
        re.compile(r"^(review\s+application|review\s*&\s*submit|review\s+and\s+submit)$", re.IGNORECASE),
    ]
    for pattern in submit_patterns:
        try:
            btn = page.get_by_role("button", name=pattern)
            for i in range(btn.count()):
                b = btn.nth(i)
                if b.is_visible() and b.is_enabled():
                    return f"Submit/Review button: '{b.inner_text().strip()}'"
        except Exception:
            continue

    try:
        sub_inputs = page.locator("input[type='submit']")
        for i in range(sub_inputs.count()):
            inp = sub_inputs.nth(i)
            if inp.is_visible() and inp.is_enabled():
                val = (inp.get_attribute("value") or "").strip()
                if re.search(r"submit|review", val, re.IGNORECASE):
                    return f"Submit input: '{val}'"
    except Exception:
        pass

    return None


def find_next_or_continue_button(page: Page) -> Optional[Locator]:
    """Dynamically locate a visible 'Next' or 'Continue' button on the page."""
    next_regex = re.compile(
        r"^(next|continue|proceed|next\s+step|save\s*&\s*continue|save\s+and\s+continue)\b",
        re.IGNORECASE,
    )

    try:
        role_buttons = page.get_by_role("button", name=next_regex)
        for i in range(role_buttons.count()):
            b = role_buttons.nth(i)
            if b.is_visible() and b.is_enabled():
                return b
    except Exception:
        pass

    css_candidates = [
        "[data-automation-id='bottom-navigation-next-button']",  # Workday next
        "button:has-text('Save & Continue')",
        "button:has-text('Save and Continue')",
        "button:has-text('Next')",
        "button:has-text('Continue')",
        "input[type='button'][value*='Next' i]",
        "input[type='button'][value*='Continue' i]",
        "input[type='submit'][value*='Next' i]",
        "input[type='submit'][value*='Continue' i]",
        "a[role='button']:has-text('Next')",
        "a[role='button']:has-text('Continue')",
        "[data-testid*='next' i]",
        "[data-testid*='continue' i]",
    ]

    for sel in css_candidates:
        try:
            loc = page.locator(sel)
            for i in range(loc.count()):
                el = loc.nth(i)
                if el.is_visible() and el.is_enabled():
                    return el
        except Exception:
            continue

    return None


def fill_last_by_label(page: Page, label_pattern: Any, value: str) -> bool:
    """Target the .last instance of an input matching label_pattern and fill it."""
    if not value:
        return False
    val_clean = str(value).strip()
    try:
        loc = page.get_by_label(label_pattern)
        if loc.count() > 0:
            target = loc.last
            # If field is already filled (e.g. from resume autofill), skip overwriting
            try:
                curr_text = target.input_value()
                if curr_text and curr_text.strip():
                    return True
            except Exception:
                pass

            input_type = target.evaluate("e => (e.getAttribute('type') || '').toLowerCase()")
            if input_type in ("checkbox", "radio"):
                target.check(force=True)
            else:
                target.fill(val_clean, timeout=3000)
            return True
    except Exception:
        pass

    # Fallback to Workday data-automation-id or name selectors if get_by_label missed
    try:
        clean_pat = str(label_pattern).lower()
        if "title" in clean_pat:
            page.locator("input[data-automation-id='jobTitle'], #jobTitle").last.fill(val_clean, timeout=2000)
            return True
        elif "company" in clean_pat:
            page.locator("input[data-automation-id='company'], #company").last.fill(val_clean, timeout=2000)
            return True
        elif "description" in clean_pat:
            page.locator("textarea[data-automation-id='description'], textarea").last.fill(val_clean, timeout=2000)
            return True
    except Exception:
        pass

    return False


def find_add_experience_button(page: Page, is_first: bool = False) -> Optional[Locator]:
    """Find the 'Add Work Experience' or 'Add Another' button using flexible text/aria locators."""
    patterns = [
        re.compile(r"Add.*(Work\s+)?Experience", re.I),
        re.compile(r"Add\s+Another", re.I),
        re.compile(r"^Add$", re.I),
    ]

    # 1. Search inside Work Experience container first
    try:
        work_section = page.locator("div, section, fieldset").filter(has=page.locator("text='Work Experience'"))
        for pat in patterns:
            btn = work_section.get_by_role("button", name=pat)
            if btn.count() > 0 and btn.last.is_visible():
                return btn.last
    except Exception:
        pass

    # 2. Search entire page
    for pat in patterns:
        try:
            btn = page.get_by_role("button", name=pat)
            if btn.count() > 0 and btn.last.is_visible():
                return btn.last
        except Exception:
            pass

    # 3. Fallback CSS selectors
    css_candidates = [
        "[data-automation-id='add-work-experience']",
        "[data-automation-id='Add']",
        "button:has-text('Add Work Experience')",
        "button:has-text('Add Another')",
        "button:has-text('Add')",
    ]
    for sel in css_candidates:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.last.is_visible():
                return loc.last
        except Exception:
            pass

    return None


def populate_experience_array(page: Page, experiences: list[dict[str, Any]], profile: dict[str, Any]) -> int:
    """Iteratively populate every record in the experience array using Rustwright accessibility locators."""
    if not experiences:
        return 0

    print(f"\n\033[1;36m[+] Iterating through {len(experiences)} work experience record(s)...\033[0m")
    added_count = 0

    for idx, record in enumerate(experiences, start=1):
        role = record.get("role") or record.get("job_title", "")
        company = record.get("company", "")
        print(f"\n  [Record {idx}/{len(experiences)}] Processing: '{role}' at '{company}'...")

        # Check if an empty fieldset is already open (common for the 1st record)
        has_open_fields = False
        try:
            title_loc = page.get_by_label(re.compile(r"Job Title", re.I))
            if title_loc.count() > 0 and title_loc.last.is_visible():
                curr_val = title_loc.last.input_value()
                if not curr_val or not curr_val.strip():
                    has_open_fields = True
        except Exception:
            pass

        # Step 1: Find and click 'Add Work Experience' button if fields are not already open
        if not has_open_fields:
            add_btn = find_add_experience_button(page, is_first=(idx == 1))
            if add_btn and add_btn.is_visible():
                btn_name = (add_btn.inner_text() or "Add Work Experience").strip()
                print(f"  [*] Clicking '{btn_name}' button...")
                add_btn.click()
                # Step 2: Force short wait to allow Workday's JavaScript to render the new input block
                page.wait_for_timeout(1500)
            else:
                print("  [!] Could not locate 'Add Work Experience' button for this record.")
                if idx > 1:
                    break

        # Step 3: Target the .last added instance of the inputs using accessibility locators
        # 1. Job Title
        if fill_last_by_label(page, re.compile(r"Job Title", re.I), role):
            print(f"    \033[1;32m[✔] Job Title -> '{role}'\033[0m")

        # 2. Company
        if fill_last_by_label(page, re.compile(r"^Company", re.I), company):
            print(f"    \033[1;32m[✔] Company -> '{company}'\033[0m")

        # 3. Location
        location = record.get("location") or profile.get("personal", {}).get("city", "Mumbai, India")
        if fill_last_by_label(page, re.compile(r"^Location", re.I), location):
            print(f"    \033[1;32m[✔] Location -> '{location}'\033[0m")

        # 4. Start Date
        start_date = record.get("start_date", "")
        if start_date:
            if fill_last_by_label(page, re.compile(r"Start Date|^From", re.I), start_date):
                print(f"    \033[1;32m[✔] Start Date -> '{start_date}'\033[0m")

        # 5. Currently Work Here / End Date
        end_date = record.get("end_date", "")
        if end_date.lower() in ("present", "current", "now"):
            try:
                curr_box = page.get_by_label(re.compile(r"currently work here", re.I))
                if curr_box.count() > 0:
                    curr_box.last.check(force=True)
                    print("    \033[1;32m[✔] Checked 'I currently work here'\033[0m")
            except Exception:
                pass
        elif end_date:
            if fill_last_by_label(page, re.compile(r"End Date|^To", re.I), end_date):
                print(f"    \033[1;32m[✔] End Date -> '{end_date}'\033[0m")

        # 6. Description
        description = record.get("description", "")
        if description:
            if fill_last_by_label(page, re.compile(r"Role Description|Description", re.I), description):
                print(f"    \033[1;32m[✔] Description filled ({len(description)} chars)\033[0m")

        added_count += 1
        page.wait_for_timeout(800)

    return added_count


def handle_dynamic_experience_page(page: Page, profile: dict[str, Any]) -> bool:
    """Handle Workday 'My Experience' sections (Resume, Work Experience, Education, Websites)."""
    try:
        has_experience_header = page.locator("h2:has-text('Experience'), h1:has-text('Experience'), legend:has-text('Experience')").count() > 0
        has_work_text = page.locator("text='Work Experience'").count() > 0
        has_file_input = page.locator("input[type='file']").count() > 0

        if not (has_experience_header or (has_work_text and has_file_input)):
            return False

        print("\n\033[1;36m===============================================================\033[0m")
        print("\033[1;36m[+] Detected 'My Experience' Multi-Section Page\033[0m")
        print("\033[1;36m===============================================================\033[0m")
        actions_taken: list[str] = []

        # 1. Resume / CV Upload
        resume_path = Path("data/resume.pdf").resolve()
        if resume_path.is_file() and has_file_input:
            try:
                file_input = page.locator("input[type='file']").first
                print(f"[*] Attaching resume: {resume_path.name}...")
                file_input.set_input_files(str(resume_path))
                page.wait_for_timeout(2500)
                print("\033[1;32m[✔] Resume uploaded successfully!\033[0m")
                actions_taken.append("Resume Upload: 'data/resume.pdf' attached")
            except Exception as e:
                print(f"[-] Could not attach resume: {e}")

        # 2. Work Experience (Iterative Loop through experience array)
        experiences = profile.get("experience", [])
        if experiences:
            count = populate_experience_array(page, experiences, profile)
            if count > 0:
                actions_taken.append(f"Work Experience: Added {count} position(s) from profile")

        # 3. Education
        educations = profile.get("education", [])
        if educations:
            try:
                edu_container = page.locator("div, section, fieldset").filter(has=page.locator("text='Education'"))
                add_edu_btn = edu_container.locator("button:has-text('Add'), [data-automation-id='Add']").first

                has_expanded_edu = page.locator("input[data-automation-id='school'], #school").count() > 0
                if not has_expanded_edu and add_edu_btn.count() > 0 and add_edu_btn.is_visible():
                    print("[*] Section: Education -> Clicking 'Add' to expand...")
                    add_edu_btn.click()
                    safe_wait_dom(page, settle_ms=1500)

                primary_edu = educations[0]
                smart_fill_field(page, "input[data-automation-id='school'], #school, input[name*='school' i]", primary_edu.get("institution", ""))
                smart_fill_field(page, "input[data-automation-id='degree'], #degree, button[data-automation-id='degree']", primary_edu.get("degree", ""))

                actions_taken.append(f"Education: Added {primary_edu.get('institution')} ({primary_edu.get('degree')})")
            except Exception as e:
                print(f"[-] Note on education: {e}")

        # 4. Websites
        linkedin = profile.get("personal", {}).get("linkedin")
        if linkedin:
            try:
                web_container = page.locator("div, section, fieldset").filter(has=page.locator("text='Websites'"))
                add_web_btn = web_container.locator("button:has-text('Add'), [data-automation-id='Add']").first

                has_expanded_web = page.locator("input[data-automation-id='website'], input[name*='website' i], input[type='url']").count() > 0
                if not has_expanded_web and add_web_btn.count() > 0 and add_web_btn.is_visible():
                    print("[*] Section: Websites -> Clicking 'Add' to expand...")
                    add_web_btn.click()
                    safe_wait_dom(page, settle_ms=1000)

                smart_fill_field(page, "input[data-automation-id='website'], input[name*='website' i], input[type='url']", linkedin)
                actions_taken.append("Websites: Added LinkedIn profile")
            except Exception as e:
                print(f"[-] Note on websites: {e}")

        # 5. Section-by-Section Manageable Pause & Prompt
        if actions_taken:
            print("\n\033[1;32m[✔] Section automation completed for My Experience!\033[0m")
            controller.is_paused = True
            controller.wait_if_paused(
                reason="Populated 'My Experience' sections from your profile.json.",
                details=actions_taken,
                action="Review the filled entries in Chromium. Adjust or add more if desired, then press [Enter] or [R] to proceed."
            )
            return True

    except Exception as e:
        print(f"[-] Note handling experience page: {e}")

    return False


def run_application_loop(page: Page, job_url: str, max_steps: int = 10) -> str:
    """Execute application loop: fill mapped fields -> attempt Next -> wait only for mandatory fields."""
    step = 1
    profile = load_profile()

    # Check if page is currently a Job Description with an 'Apply' button
    check_and_click_initial_apply_button(page)

    while step <= max_steps:
        # Check for pause / stop / skip commands
        if not controller.wait_if_paused():
            return "stopped"
        if controller.skip_requested:
            return "skipped"

        print(f"\n==================== [ STEP {step} ] ====================")
        safe_wait_dom(page, settle_ms=1000)

        # Barrier Check: Sign-in, Workday login, 2FA, or Captcha
        barrier = controller.check_for_sign_in_or_barriers(page)
        if barrier:
            controller.is_paused = True
            if not controller.wait_if_paused(
                reason=barrier["reason"],
                details=barrier.get("details"),
                action=barrier.get("action"),
            ):
                return "stopped"
            if controller.skip_requested:
                return "skipped"
            safe_wait_dom(page, settle_ms=1500)

        # Check and handle dynamic multi-section pages (My Experience / Resume / Education)
        handle_dynamic_experience_page(page, profile)

        # Step 1: Extract DOM
        print("[1] Extracting current page DOM from Rustwright...")
        dom_content = page.content()

        # Step 2: Pass DOM to dom_analyzer function
        provider_info = get_active_provider_info()
        print(f"[2] Calling dom_analyzer with {provider_info['display_name']}...")
        try:
            mappings = analyze_dom(dom_content)
            print(f"    Mapped {len(mappings)} field(s): {mappings}")
        except Exception as e:
            print(f"    \033[1;31m[!] Error during DOM analysis: {e}\033[0m")
            mappings = {}

        # Step 3: Populate form fields with mapped values
        if mappings:
            print("[3] Populating form fields using page.fill()...")
            fill_form_fields(page, mappings)
            page.wait_for_timeout(1000)

        # Step 4: Check if Review or Submit page is reached
        review_indicator = check_review_or_submit_page(page)
        next_button = find_next_or_continue_button(page)

        if review_indicator and not next_button:
            print(f"\n\033[1;32m[🛑 REVIEW STAGE] {review_indicator}\033[0m")
            print("[✔] Reached final Review / Submit page!")
            print("Action: Review application entries in Chromium. Submit manually when ready.")
            controller.is_paused = True
            controller.wait_if_paused(
                reason="Application fields populated. Reached final Review / Submit page.",
                details=[f"Trigger element: {review_indicator}"],
                action="Review all entries in Chromium. Click 'Submit' manually when ready.",
            )
            return "review_reached"

        # Step 5: Attempt to advance by clicking 'Next' / 'Continue'
        if next_button:
            button_text = (next_button.inner_text() or next_button.get_attribute("value") or "Next").strip()
            print(f"\033[1;36m[4] Identified navigation button: '{button_text}'. Attempting to proceed...\033[0m")

            initial_url = page.url
            try:
                next_button.click()
                safe_wait_dom(page, settle_ms=2000)
            except Exception as click_err:
                print(f"[!] Error clicking navigation button: {click_err}")

            # Check if mandatory fields or validation errors stopped advancement
            mandatory_errors = check_page_errors_or_required(page)
            new_url = page.url

            # Only pause if mandatory errors exist AND the page did not advance!
            if mandatory_errors and (new_url == initial_url):
                print("\n\033[1;33m[!] Mandatory fields or validation errors require your attention.\033[0m")
                controller.is_paused = True
                if not controller.wait_if_paused(
                    reason="Mandatory fields or validation errors prevented advancing to next step.",
                    details=mandatory_errors,
                    action="Fill the required fields in Chromium, then press [Enter] or [R] to retry.",
                ):
                    return "stopped"
                if controller.skip_requested:
                    return "skipped"

                # Retry clicking Next after user intervention
                safe_wait_dom(page, settle_ms=1500)
                retry_btn = find_next_or_continue_button(page)
                if retry_btn:
                    try:
                        retry_btn.click()
                        safe_wait_dom(page, settle_ms=2000)
                    except Exception:
                        pass

            step += 1
        else:
            if review_indicator:
                controller.is_paused = True
                controller.wait_if_paused(
                    reason="Reached Review step.",
                    details=[f"Trigger: {review_indicator}"],
                    action="Review application in Chromium, then press [Enter] or [R].",
                )
                return "review_reached"
            elif step == 1 and not mappings:
                print("\n\033[1;33m[!] No form fields or navigation buttons found on initial page.\033[0m")
                controller.is_paused = True
                if not controller.wait_if_paused(
                    reason="No application form fields or Next buttons detected on page.",
                    details=[
                        f"Current URL: {page.url}",
                        f"Page Title: '{page.title()}'",
                        "The portal may require manual login or navigation to reach the application form."
                    ],
                    action="Navigate to the application form or sign in in Chromium, then press [Enter] or [R]."
                ):
                    return "stopped"
                if controller.skip_requested:
                    return "skipped"
                safe_wait_dom(page, settle_ms=2000)
                continue
            else:
                print("\n[ℹ] No further 'Next' or 'Continue' buttons found. Application steps completed.")
                break

    return "completed"


def main(url_arg: Optional[str] = None) -> None:
    """Initialize session, process job queue, and handle interactive CLI controls."""
    job_urls = load_job_urls(url_arg)
    provider_info = get_active_provider_info()
    print(f"\n\033[1;32m[*] Total job applications to process: {len(job_urls)}\033[0m")
    print(f"\033[1;36m[*] Active LLM Provider: {provider_info['display_name']} ({provider_info['endpoint']})\033[0m")

    print("\n[Controls] Keyboard shortcuts in this console:")
    print("  [P] or [Space] = Pause | [R] or [Enter] = Resume")
    print("  [N] = Skip to Next Job | [Q] = Stop Automator\n")

    headless_env = os.environ.get("HEADLESS", "false").lower() in ("true", "1")

    with sync_playwright() as p:
        print("[*] Launching Chromium browser (non-headless)...")
        browser = p.chromium.launch(headless=headless_env)
        context = browser.new_context()
        page = context.new_page()

        try:
            for idx, job_url in enumerate(job_urls, start=1):
                if controller.stop_requested:
                    print("\n\033[1;31m[🛑] Stopping application run as requested.\033[0m")
                    break

                controller.skip_requested = False
                print(f"\n==========================================================")
                print(f"  PROCESSING JOB {idx}/{len(job_urls)}: {job_url}")
                print(f"==========================================================")

                try:
                    loaded = navigate_to_url(page, job_url)
                    if loaded:
                        result = run_application_loop(page, job_url)
                        print(f"\033[1;32m[✓] Outcome for Job {idx}: {result}\033[0m")
                except Exception as job_err:
                    print(f"\033[1;31m[X] Error processing job {job_url}: {job_err}\033[0m")
                    controller.is_paused = True
                    controller.wait_if_paused(
                        reason=f"Error encountered: {job_err}",
                        details=[f"URL: {job_url}"],
                        action="Inspect Chromium window, then press [Enter] / [R] to retry or [N] to Skip."
                    )

                if controller.stop_requested:
                    break

                if idx < len(job_urls):
                    print("\nProceeding to next job in 2 seconds...")
                    time.sleep(2)

            print("\n[*] All job application runs finished.")

            if sys.stdin.isatty():
                print("Browser remains open. Press Enter to close...")
                try:
                    input()
                except (EOFError, KeyboardInterrupt):
                    pass
            else:
                page.wait_for_timeout(2000)

        finally:
            browser.close()


if __name__ == "__main__":
    if "-h" in sys.argv or "--help" in sys.argv:
        print("""orgs-app-job-auto-rustwright - Automated Job Application Agent

Usage:
  python main.py                     # Reads URLs line-by-line from jobs_links.txt
  python main.py <job_url>           # Processes a single target job URL directly

Controls (Interactive Terminal):
  [P] or [Space] : Pause execution
  [R] or [Enter] : Resume execution
  [N]            : Skip current job and proceed to next
  [Q]            : Quit automator immediately
""")
        sys.exit(0)

    cli_arg = None
    for arg in sys.argv[1:]:
        if not arg.startswith("-"):
            cli_arg = arg
            break
    main(cli_arg)
