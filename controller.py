import os
import re
import sys
import time
from typing import Any, Optional

try:
    import msvcrt
except ImportError:
    msvcrt = None

try:
    import winsound
except ImportError:
    winsound = None

# Configure UTF-8 output on Windows consoles if supported
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class AutomatorController:
    """Manages execution state, barrier detection, and responsive CLI keyboard controls."""

    def __init__(self) -> None:
        self.is_paused = False
        self.skip_requested = False
        self.stop_requested = False

    def check_signals(self) -> None:
        """Poll non-blocking console key presses via msvcrt (Windows)."""
        if msvcrt and msvcrt.kbhit():
            try:
                char = msvcrt.getch().decode("utf-8", errors="ignore").lower()
                if char in ("p", " "):
                    print("\n\033[1;33m[User Input] 'P' pressed -> PAUSING AUTOMATOR...\033[0m")
                    self.is_paused = True
                elif char in ("r", "\r", "\n"):
                    print("\n\033[1;32m[User Input] 'R' pressed -> RESUMING AUTOMATOR...\033[0m")
                    self.is_paused = False
                elif char == "n":
                    print("\n\033[1;36m[User Input] 'N' pressed -> SKIPPING TO NEXT JOB...\033[0m")
                    self.skip_requested = True
                elif char in ("q", "\x03"):
                    print("\n\033[1;31m[User Input] 'Q' pressed -> STOPPING AUTOMATOR...\033[0m")
                    self.stop_requested = True
            except Exception:
                pass

    def print_highlighted_banner(
        self,
        title: str,
        reason: str,
        details: Optional[list[str]] = None,
        action: Optional[str] = None,
    ) -> None:
        """Print a high-visibility, highlighted ANSI banner to the terminal."""
        width = 82
        sep_double = "=" * width
        sep_single = "-" * width

        CYAN_BOLD = "\033[1;36m"
        YELLOW_BOLD = "\033[1;33m"
        WHITE_BOLD = "\033[1;37m"
        GREEN_BOLD = "\033[1;32m"
        RESET = "\033[0m"

        print(f"\n{YELLOW_BOLD}+{sep_double}+{RESET}")
        print(f"{YELLOW_BOLD}| {title.center(width - 2)} |{RESET}")
        print(f"{YELLOW_BOLD}+{sep_double}+{RESET}")
        print(f"{WHITE_BOLD}| REASON: {reason:<{width - 11}} |{RESET}")

        if details:
            print(f"{YELLOW_BOLD}+{sep_single}+{RESET}")
            print(f"{CYAN_BOLD}| MANDATORY FIELDS / DETAILS: {' ' * (width - 31)}|{RESET}")
            for d in details:
                line = f"  * {d}"
                if len(line) > width - 4:
                    line = line[: width - 7] + "..."
                print(f"{WHITE_BOLD}| {line:<{width - 2}} |{RESET}")

        print(f"{YELLOW_BOLD}+{sep_single}+{RESET}")
        action_text = action or "Fill the required fields in Chromium, then resume."
        print(f"{GREEN_BOLD}| >> ACTION: {action_text:<{width - 12}} |{RESET}")
        print(f"{CYAN_BOLD}| >> RESUME: Press [Enter] or [R] in this console to proceed{' ' * (width - 58)}|{RESET}")
        print(f"{YELLOW_BOLD}+{sep_double}+\n{RESET}")

    def wait_if_paused(
        self,
        reason: str = "",
        details: Optional[list[str]] = None,
        action: Optional[str] = None,
    ) -> bool:
        """Wait loop when paused. Returns False if stop was requested."""
        if not self.is_paused:
            self.check_signals()

        if self.is_paused:
            self._alert_sound()

            title = "AUTOMATOR PAUSED -- ACTION REQUIRED" if reason else "AUTOMATOR PAUSED (MANUAL HOLD)"
            self.print_highlighted_banner(
                title=title,
                reason=reason or "Manual pause triggered by user.",
                details=details,
                action=action,
            )

            # Wait loop: checks keystrokes responsive to [R], [Enter], [P], [N], [Q]
            while self.is_paused and not self.stop_requested and not self.skip_requested:
                self.check_signals()
                time.sleep(0.1)

            if self.stop_requested:
                print("\033[1;31m[🛑] Stop command acknowledged. Halting.\033[0m")
                return False

            if self.skip_requested:
                print("\033[1;36m[⏭] Skip command acknowledged. Moving to next job.\033[0m")
                return True

            print("\033[1;32m[▶] Resuming execution...\033[0m")

        return not self.stop_requested

    def check_for_sign_in_or_barriers(self, page: Any) -> Optional[dict[str, Any]]:
        """Detect login forms, Workday sign-ins, SSO, captchas, 2FA, or bot verification."""
        try:
            # 1. Password input detection (Workday / Portal Sign-In)
            passwords = page.locator("input[type='password']")
            if passwords.count() > 0 and passwords.first.is_visible():
                return {
                    "reason": "Portal Sign-In / Candidate Login required.",
                    "details": [
                        "Password field detected on current page.",
                        "Portal requires candidate account login or registration before applying.",
                    ],
                    "action": "Log in or create an account in Chromium. Once in the application, press [Enter] or [R].",
                }

            # 2. Workday specific sign-in or create account buttons
            workday_sign_in = page.locator("[data-automation-id='signInSubmitButton'], [data-automation-id='createAccountSubmitButton']")
            if workday_sign_in.count() > 0 and workday_sign_in.first.is_visible():
                return {
                    "reason": "Workday Sign-In / Account Creation page detected.",
                    "details": [
                        "Workday requires candidate login to proceed with this application.",
                    ],
                    "action": "Log in to your Workday candidate account in Chromium, then press [Enter] or [R].",
                }

            # 3. Captcha / Bot protection detection
            captcha_selectors = [
                "iframe[src*='captcha']",
                "iframe[src*='cloudflare']",
                "div.g-recaptcha",
                "div.h-captcha",
                "#cf-turnstile",
                "[data-testid*='captcha' i]",
            ]
            for sel in captcha_selectors:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    return {
                        "reason": "Security challenge / Captcha verification active.",
                        "details": [f"Matched security selector: {sel}"],
                        "action": "Solve the Captcha in Chromium, then press [Enter] or [R] to continue.",
                    }

            # 4. 2FA / One-Time Passcode
            otp_loc = page.locator("input[autocomplete*='one-time-code'], input[name*='otp' i], input[name*='2fa' i]")
            if otp_loc.count() > 0 and otp_loc.first.is_visible():
                return {
                    "reason": "Two-Factor Authentication (2FA / OTP) required.",
                    "details": ["One-time verification code requested."],
                    "action": "Enter verification code in Chromium, then press [Enter] or [R].",
                }

        except Exception:
            pass

        return None

    def _alert_sound(self) -> None:
        """Trigger an audible chime on Windows if available."""
        if winsound:
            try:
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except Exception:
                pass


# Global singleton instance
controller = AutomatorController()
