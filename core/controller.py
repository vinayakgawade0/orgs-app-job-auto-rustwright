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
                ch = msvcrt.getch()
                if ch in (b"\x00", b"\xe0"):
                    msvcrt.getch()
                    return

                key = ch.decode("utf-8", errors="ignore").lower()
                if key in ("p", " "):
                    self.is_paused = True
                    print("\n\033[1;33m[⏸ PAUSE REQUESTED] Automation will pause at the next safe step.\033[0m")
                elif key in ("r", "\r", "\n"):
                    if self.is_paused:
                        self.is_paused = False
                        print("\n\033[1;32m[▶ RESUME] Resuming automation...\033[0m")
                elif key == "n":
                    self.skip_requested = True
                    self.is_paused = False
                    print("\n\033[1;35m[⏭ SKIP] Skipping current job posting...\033[0m")
                elif key == "q":
                    self.stop_requested = True
                    self.is_paused = False
                    print("\n\033[1;31m[🛑 STOP] Stopping automator...\033[0m")
            except Exception:
                pass

    def wait_if_paused(
        self,
        reason: str = "Execution Paused",
        details: Optional[list[str]] = None,
        action: Optional[str] = None,
    ) -> bool:
        """If paused, print formatted HUD banner, chime, and wait until user resumes or quits."""
        if not self.is_paused:
            self.check_signals()
            if not self.is_paused:
                return True

        if winsound:
            try:
                winsound.Beep(1000, 250)
            except Exception:
                pass

        print("\n" + "=" * 65)
        print(" \033[1;33m[⏸ ATTENTION REQUIRED / PAUSED]\033[0m")
        print("=" * 65)
        print(f" Reason  : {reason}")
        if details:
            for item in details:
                print(f" Details : {item}")
        action_msg = action or "Take any required manual action in Chromium, then press [Enter] or [R] here."
        print(f" Action  : \033[1;32m{action_msg}\033[0m")
        print("-" * 65)
        print(" Controls: [R] or [Enter] = Resume | [N] = Skip Job | [Q] = Quit")
        print("=" * 65 + "\n")

        while self.is_paused and not self.stop_requested and not self.skip_requested:
            self.check_signals()
            time.sleep(0.2)

        if self.stop_requested:
            return False
        return True

    def check_for_sign_in_or_barriers(self, page: Any) -> Optional[dict[str, Any]]:
        """Detect sign-in screens, Workday authentication, OTP, 2FA, or captchas."""
        try:
            # 1. Password input
            pwd = page.locator("input[type='password']")
            if pwd.count() > 0 and pwd.first.is_visible():
                return {
                    "type": "sign_in",
                    "reason": "Sign-in / Password screen detected.",
                    "details": ["Password field visible on page."],
                    "action": "Sign in or create an account in Chromium, then press [Enter] or [R] to continue."
                }

            # 2. Captcha or Cloudflare challenge
            captcha = page.locator(
                "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], iframe[src*='turnstile'], "
                "[data-sitekey], .g-recaptcha, .h-captcha, #cf-challenge"
            )
            if captcha.count() > 0 and captcha.first.is_visible():
                return {
                    "type": "captcha",
                    "reason": "Security Captcha / Bot Challenge detected.",
                    "details": ["Cloudflare or Captcha widget active."],
                    "action": "Solve the captcha in Chromium, then press [Enter] or [R] to resume."
                }

            # 3. 2FA / OTP verification code
            otp = page.locator(
                "input[name*='otp' i], input[name*='code' i], input[autocomplete='one-time-code'], "
                "text='Enter verification code', text='Authentication Code'"
            )
            if otp.count() > 0 and otp.first.is_visible():
                return {
                    "type": "otp",
                    "reason": "2-Factor / OTP Verification detected.",
                    "details": ["Verification code input detected."],
                    "action": "Complete two-factor authentication in Chromium, then press [Enter] or [R]."
                }

            # 4. Workday specific Sign-In modal/page
            workday_login = page.locator(
                "[data-automation-id='signInContainer'], [data-automation-id='createAccountContainer']"
            )
            if workday_login.count() > 0 and workday_login.first.is_visible():
                return {
                    "type": "sign_in",
                    "reason": "Workday candidate authentication required.",
                    "details": ["Workday sign-in / registration container displayed."],
                    "action": "Sign in or register in Chromium, then press [Enter] or [R]."
                }

        except Exception:
            pass

        return None


# Global singleton controller instance
controller = AutomatorController()
