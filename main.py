"""orgs-app-job-auto-rustwright - Main Orchestrator

Coordinates browser execution, multi-provider LLM form analysis,
Workday portal steps, and interactive CLI controls.
"""

import sys
import time
from typing import Optional

from rustwright.sync_api import Page, sync_playwright

from config.settings import (
    get_active_provider_info,
    load_job_urls,
    load_profile,
    save_learned_qa,
)
from core.browser import launch_browser, navigate_to_url, safe_wait_dom
from core.controller import controller
from core.form_filler import fill_form_fields
from llm.dom_analyzer import analyze_dom
from portals.workday import (
    check_and_click_initial_apply_button,
    check_page_errors_or_required,
    check_review_or_submit_page,
    find_next_or_continue_button,
    handle_dynamic_experience_page,
)


def run_application_loop(page: Page, job_url: str, max_steps: int = 15) -> str:
    """Execute application loop: fill mapped fields -> attempt Next -> wait only for mandatory fields."""
    step = 1
    profile = load_profile()

    # Step 0: Check if page is a Job Description and enter application
    check_and_click_initial_apply_button(page)

    while step <= max_steps:
        # Check signals for pause / stop / skip commands
        if not controller.wait_if_paused():
            return "stopped"
        if controller.skip_requested:
            return "skipped"

        print(f"\n==================== [ STEP {step} ] ====================")
        safe_wait_dom(page, settle_ms=1000)

        # Barrier Check: Sign-in, Workday login, 2FA, OTP, or Captcha
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

        # Workday Multi-Section handler (Resume / Work Experience / Education / Websites)
        handle_dynamic_experience_page(page, profile)

        # Step A: Extract DOM and invoke LLM analyzer
        print("[1] Extracting current page DOM from Rustwright...")
        dom_content = page.content()

        provider_info = get_active_provider_info()
        print(f"[2] Calling dom_analyzer with {provider_info['display_name']}...")
        try:
            mappings = analyze_dom(dom_content, profile=profile)
            print(f"    Mapped {len(mappings)} field(s): {mappings}")
        except Exception as e:
            print(f"    \033[1;31m[!] Error during DOM analysis: {e}\033[0m")
            mappings = {}

        # Step B: Populate form fields
        if mappings:
            filled_count = fill_form_fields(page, mappings)
            print(f"[3] Successfully populated {filled_count}/{len(mappings)} field(s).")
        else:
            print("[3] No pending form fields to populate on this step.")

        safe_wait_dom(page, settle_ms=1000)

        # Step C: Review / Final Submit check
        review_indicator = check_review_or_submit_page(page)
        next_button = find_next_or_continue_button(page)

        if next_button:
            if review_indicator:
                btn_name = (next_button.inner_text() or "Submit").strip()
                print(f"\n\033[1;33m[⏸ FINAL REVIEW REACHED] Detected: {review_indicator}\033[0m")
                controller.is_paused = True
                controller.wait_if_paused(
                    reason="Reached Final Review / Submission Page.",
                    details=[
                        f"Detected: {review_indicator}",
                        f"Action button: '{btn_name}' (Submission halted for human safety)."
                    ],
                    action="Carefully review the entire application in Chromium. If satisfied, submit manually, then press [Enter] or [R]."
                )
                return "review_completed"

            # Step D: Attempt to click Next / Continue
            btn_text = (next_button.inner_text() or "Next").strip()
            print(f"\n[*] Attempting to advance: Clicking '{btn_text}'...")
            try:
                next_button.click()
            except Exception:
                try:
                    next_button.click(force=True)
                except Exception as click_err:
                    print(f"[-] Could not click '{btn_text}': {click_err}")

            safe_wait_dom(page, settle_ms=2500)

            # Step E: Validation & Mandatory field check
            unresolved_errors = check_page_errors_or_required(page)
            if unresolved_errors:
                print(f"\n\033[1;33m[!] Validation required ({len(unresolved_errors)} item(s) blocking progression):\033[0m")
                for err in unresolved_errors:
                    print(f"    - {err}")

                controller.is_paused = True
                if not controller.wait_if_paused(
                    reason=f"Form progression blocked by {len(unresolved_errors)} required field(s) or validation error(s).",
                    details=unresolved_errors,
                    action="Fill the highlighted missing field(s) in Chromium, then press [Enter] or [R] to continue."
                ):
                    return "stopped"
                if controller.skip_requested:
                    return "skipped"

                # Automatically learn user-filled answers into profile_qa.json
                try:
                    for err_item in unresolved_errors:
                        if "Missing mandatory field:" in err_item:
                            field_label = err_item.split(":", 1)[1].strip().strip("'\"")
                            target_loc = page.get_by_label(field_label)
                            if target_loc.count() > 0 and target_loc.first.is_visible():
                                user_val = target_loc.first.input_value()
                                if user_val and user_val.strip():
                                    save_learned_qa(field_label, user_val.strip())
                except Exception:
                    pass

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

    with sync_playwright() as p:
        browser, context, page = launch_browser(p)

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
  python main.py                     # Reads URLs line-by-line from data/jobs_links.txt
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
