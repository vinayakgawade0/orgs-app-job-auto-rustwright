import re
from pathlib import Path
from typing import Any, Optional

from rustwright.sync_api import Locator, Page
from config.settings import BASE_DIR, get_resume_path, save_learned_qa
from core.browser import safe_wait_dom
from core.controller import controller
from core.form_filler import smart_fill_field


def _find_autofill_with_resume_button(page: Page) -> Optional[Locator]:
    """Find the 'Autofill with Resume' button or link if present on the page or modal."""
    selectors = [
        "[data-automation-id='autofillWithResume']",
        "button[data-automation-id='autofillWithResume']",
        "a[data-automation-id='autofillWithResume']",
        "button:has-text('Autofill with Resume')",
        "a:has-text('Autofill with Resume')",
        "button:has-text('Autofill with resume')",
        "a:has-text('Autofill with resume')",
        "button:has-text('Apply with Resume')",
        "a:has-text('Apply with Resume')",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                return loc.first
        except Exception:
            continue
    return None


def check_and_click_initial_apply_button(page: Page) -> bool:
    """If on a job description page, click 'Apply' and strictly prioritize 'Autofill with Resume'."""
    resume_path = get_resume_path(page.url)

    try:
        # Check if already on a screen showing 'Autofill with Resume'
        autofill_btn = _find_autofill_with_resume_button(page)
        if autofill_btn and resume_path.is_file():
            print("\033[1;36m[+] 'Autofill with Resume' already visible. Selecting it now...\033[0m")
            autofill_btn.click()
            safe_wait_dom(page, settle_ms=2500)
            return _upload_resume_and_proceed(page, resume_path)

        # Primary initial Apply buttons on Job Posting (DO NOT put applyManually here!)
        apply_selectors = [
            "[data-automation-id='adventureButton']",  # Workday main Apply button
            "button:has-text('Apply Now')",
            "a:has-text('Apply Now')",
            "button:has-text('Apply')",
            "a[role='button']:has-text('Apply')",
        ]

        # Wait up to 8s for initial Apply button to appear
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

                # Poll specifically for Workday application mode modal (up to 8 seconds)
                # Prioritizing 'Autofill with Resume'
                print("[*] Checking application options: prioritizing 'Autofill with Resume'...")
                for _ in range(16):
                    autofill_opt = _find_autofill_with_resume_button(page)
                    if autofill_opt and resume_path.is_file():
                        print("\033[1;32m[+] Selecting 'Autofill with Resume' option...\033[0m")
                        autofill_opt.click()
                        safe_wait_dom(page, settle_ms=2500)
                        return _upload_resume_and_proceed(page, resume_path)

                    page.wait_for_timeout(500)

                # If Autofill with Resume is definitely not offered by this portal, fallback to Apply Manually
                manual_loc = page.locator(
                    "a[data-automation-id='applyManually'], "
                    "button[data-automation-id='applyManually'], "
                    "a:has-text('Apply Manually'), "
                    "button:has-text('Apply Manually')"
                )
                if manual_loc.count() > 0 and manual_loc.first.is_visible():
                    print("\033[1;33m[!] 'Autofill with Resume' not offered by employer. Falling back to 'Apply Manually'...\033[0m")
                    manual_loc.first.click()
                    safe_wait_dom(page, settle_ms=2500)

                return True

            page.wait_for_timeout(500)

    except Exception as e:
        print(f"[-] Notice checking apply button: {e}")
    return False


def _upload_resume_and_proceed(page: Page, resume_path: Path) -> bool:
    """Helper to upload resume file on Autofill screen and click Continue/Next."""
    try:
        # Wait for file upload dropzone/input
        for _ in range(12):
            file_inp = page.locator("input[type='file']")
            if file_inp.count() > 0:
                print(f"\033[1;32m[*] Attaching resume for ATS parsing: {resume_path.name}...\033[0m")
                file_inp.first.set_input_files(str(resume_path))
                safe_wait_dom(page, settle_ms=3000)

                # Look for 'Continue' or 'Next' button after uploading
                cont_btn = page.locator(
                    "button:has-text('Continue'), button:has-text('Next'), "
                    "[data-automation-id='bottom-navigation-next-button']"
                )
                if cont_btn.count() > 0 and cont_btn.first.is_visible():
                    print("[*] Advancing after resume upload...")
                    cont_btn.first.click()
                    safe_wait_dom(page, settle_ms=3000)
                return True

            page.wait_for_timeout(500)

    except Exception as e:
        print(f"[-] Note uploading resume: {e}")
    return True


def fill_last_by_label(page: Page, label_pattern: Any, value: str) -> bool:
    """Target the .last instance of an input matching label_pattern and fill it."""
    if not value:
        return False
    val_clean = str(value).strip()
    try:
        loc = page.get_by_label(label_pattern)
        if loc.count() > 0:
            target = loc.last
            # If field is already populated (e.g. from resume autofill), skip overwriting
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


def find_add_experience_button(page: Page) -> Optional[Locator]:
    """Find the specific 'Add' or 'Add Work Experience' button in the Work Experience section."""
    # 1. Structural XPath: Find button with text 'Add' immediately following the Work Experience heading
    xpath_selectors = [
        "xpath=//h3[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'work experience')]/following::button[contains(., 'Add')][1]",
        "xpath=//h2[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'work experience')]/following::button[contains(., 'Add')][1]",
        "xpath=//legend[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'work experience')]/following::button[contains(., 'Add')][1]",
        "xpath=//*[contains(@data-automation-id, 'workExperience')]//button[contains(., 'Add') or @data-automation-id='Add'][1]",
    ]
    for xp in xpath_selectors:
        try:
            btn = page.locator(xp)
            if btn.count() > 0 and btn.first.is_visible():
                return btn.first
        except Exception:
            continue

    # 2. Specific automation IDs
    css_selectors = [
        "button[data-automation-id='add-work-experience']",
        "button[aria-label*='Work Experience' i]",
        "button[aria-label*='Add Experience' i]",
        "[data-automation-id='workExperienceSection'] button:has-text('Add')",
    ]
    for sel in css_selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                return loc.first
        except Exception:
            continue

    return None


def find_add_education_button(page: Page) -> Optional[Locator]:
    """Find the specific 'Add' or 'Add Education' button in the Education section."""
    xpath_selectors = [
        "xpath=//h3[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'education')]/following::button[contains(., 'Add')][1]",
        "xpath=//h2[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'education')]/following::button[contains(., 'Add')][1]",
        "xpath=//legend[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'education')]/following::button[contains(., 'Add')][1]",
        "xpath=//*[contains(@data-automation-id, 'education')]//button[contains(., 'Add') or @data-automation-id='Add'][1]",
    ]
    for xp in xpath_selectors:
        try:
            btn = page.locator(xp)
            if btn.count() > 0 and btn.first.is_visible():
                return btn.first
        except Exception:
            continue

    css_selectors = [
        "button[data-automation-id='add-education']",
        "button[aria-label*='Education' i]",
        "[data-automation-id='educationSection'] button:has-text('Add')",
    ]
    for sel in css_selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                return loc.first
        except Exception:
            continue

    return None


def find_add_website_button(page: Page) -> Optional[Locator]:
    """Find the specific 'Add' button in the Websites section."""
    xpath_selectors = [
        "xpath=//h3[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'website')]/following::button[contains(., 'Add')][1]",
        "xpath=//h2[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'website')]/following::button[contains(., 'Add')][1]",
        "xpath=//*[contains(@data-automation-id, 'website')]//button[contains(., 'Add') or @data-automation-id='Add'][1]",
    ]
    for xp in xpath_selectors:
        try:
            btn = page.locator(xp)
            if btn.count() > 0 and btn.first.is_visible():
                return btn.first
        except Exception:
            continue

    css_selectors = [
        "button[data-automation-id='add-website']",
        "button[aria-label*='Website' i]",
    ]
    for sel in css_selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                return loc.first
        except Exception:
            continue

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

        # Check if an empty fieldset is already open
        has_open_fields = False
        try:
            title_loc = page.get_by_label(re.compile(r"Job Title", re.I))
            if title_loc.count() > 0 and title_loc.last.is_visible():
                curr_val = title_loc.last.input_value()
                if not curr_val or not curr_val.strip():
                    has_open_fields = True
        except Exception:
            pass

        # Step 1: Click 'Add Work Experience' button if fields are not already open
        if not has_open_fields:
            add_btn = find_add_experience_button(page)
            if add_btn and add_btn.is_visible():
                btn_name = (add_btn.inner_text() or "Add Work Experience").strip()
                print(f"  [*] Clicking '{btn_name}' button...")
                add_btn.click()
                page.wait_for_timeout(1500)
            else:
                print("  [!] Could not locate 'Add Work Experience' button for this record.")
                if idx > 1:
                    break

        # Step 2: Target the .last added instance of the inputs using accessibility locators
        if fill_last_by_label(page, re.compile(r"Job Title", re.I), role):
            print(f"    \033[1;32m[✔] Job Title -> '{role}'\033[0m")

        if fill_last_by_label(page, re.compile(r"^Company", re.I), company):
            print(f"    \033[1;32m[✔] Company -> '{company}'\033[0m")

        location = (
            record.get("location")
            or profile.get("personal", {}).get("city")
            or profile.get("address", {}).get("city", "")
        )
        if location and fill_last_by_label(page, re.compile(r"^Location", re.I), location):
            print(f"    \033[1;32m[✔] Location -> '{location}'\033[0m")

        start_date = record.get("start_date", "")
        if start_date:
            if fill_last_by_label(page, re.compile(r"Start Date|^From", re.I), start_date):
                print(f"    \033[1;32m[✔] Start Date -> '{start_date}'\033[0m")

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
        has_experience_header = page.locator(
            "h2:has-text('Experience'), h1:has-text('Experience'), legend:has-text('Experience')"
        ).count() > 0
        has_work_text = page.locator("text='Work Experience'").count() > 0
        has_file_input = page.locator("input[type='file']").count() > 0

        if not (has_experience_header or (has_work_text and has_file_input)):
            return False

        print("\n\033[1;36m===============================================================\033[0m")
        print("\033[1;36m[+] Detected 'My Experience' Multi-Section Page\033[0m")
        print("\033[1;36m===============================================================\033[0m")
        actions_taken: list[str] = []

        # 1. Resume / CV Upload
        resume_path = get_resume_path(page.url)
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

        # 2. Work Experience (Iterative Loop)
        experiences = profile.get("experience", [])
        if experiences:
            count = populate_experience_array(page, experiences, profile)
            if count > 0:
                actions_taken.append(f"Work Experience: Added {count} position(s) from profile")

        # 3. Education
        educations = profile.get("education", [])
        if educations:
            try:
                # Find the exact Add Education button
                add_edu_btn = find_add_education_button(page)
                has_expanded_edu = page.locator("input[data-automation-id='school'], #school").count() > 0

                if not has_expanded_edu and add_edu_btn and add_edu_btn.is_visible():
                    print("[*] Section: Education -> Clicking 'Add' button...")
                    add_edu_btn.click()
                    safe_wait_dom(page, settle_ms=1500)

                primary_edu = educations[0]
                smart_fill_field(
                    page,
                    "input[data-automation-id='school'], #school, input[name*='school' i]",
                    primary_edu.get("institution", ""),
                )
                smart_fill_field(
                    page,
                    "input[data-automation-id='degree'], #degree, button[data-automation-id='degree']",
                    primary_edu.get("degree", ""),
                )

                actions_taken.append(f"Education: Added {primary_edu.get('institution')} ({primary_edu.get('degree')})")
            except Exception as e:
                print(f"[-] Note on education: {e}")

        # 4. Websites
        linkedin = profile.get("personal", {}).get("linkedin")
        if linkedin:
            try:
                add_web_btn = find_add_website_button(page)
                has_expanded_web = page.locator(
                    "input[data-automation-id='website'], input[name*='website' i], input[type='url']"
                ).count() > 0

                if not has_expanded_web and add_web_btn and add_web_btn.is_visible():
                    print("[*] Section: Websites -> Clicking 'Add' button...")
                    add_web_btn.click()
                    safe_wait_dom(page, settle_ms=1000)

                smart_fill_field(
                    page,
                    "input[data-automation-id='website'], input[name*='website' i], input[type='url']",
                    linkedin,
                )
                actions_taken.append("Websites: Added LinkedIn profile")
            except Exception as e:
                print(f"[-] Note on websites: {e}")

        # 5. Manageable Section Review & Prompt
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


def check_page_errors_or_required(page: Page) -> list[str]:
    """Identify ONLY mandatory unfilled fields or active validation errors."""
    unresolved: list[str] = []

    try:
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

            if is_required:
                try:
                    val = el.input_value().strip()
                except Exception:
                    val = (el.get_attribute("value") or "").strip()

                if not val:
                    field_name = aria_label or label_text or placeholder or el_name or el_id or "Required input"
                    item_str = f"Missing mandatory field: '{field_name}'"
                    if item_str not in unresolved:
                        unresolved.append(item_str)

    except Exception:
        pass

    return unresolved


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
