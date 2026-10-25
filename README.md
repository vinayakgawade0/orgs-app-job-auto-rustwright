# orgs-app-job-auto-rustwright

> Automated, resilient browser job application agent powered by **Rustwright** (Playwright for Rust/Python) and **Multi-Provider LLM Routing** (Local Ollama, HuggingFace Serverless, Google Gemini).

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Automation: Rustwright](https://img.shields.io/badge/Browser-Rustwright%20(Chromium)-orange.svg)](https://github.com/rustwright/rustwright)
[![LLM: Multi-Provider](https://img.shields.io/badge/LLM-Ollama%20%7C%20HuggingFace%20%7C%20Gemini-green.svg)](https://ollama.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Key Features

- **Multi-Provider LLM Engine**: Seamlessly toggle between **Ollama Local** (100% free, offline, zero token quotas), **HuggingFace Cloud Serverless**, **Google Gemini**, or **Remote Ollama** with a single switch in `.env`.
- **Workday SPA & Repeating Fieldsets**: Handles Workday's client-side React rendering and dynamic CSS IDs by iteratively expanding repeating fieldsets (Experience, Education, Websites) and binding via accessibility locators (`page.get_by_label(...).last`).
- **Autofill-with-Resume & Native DOM Skip**: Prioritizes *"Autofill with Resume"*, uploads `resume.pdf` for initial ATS parsing, and uses instant `< 1ms` DOM checks to skip already populated fields with **zero LLM token consumption**.
- **Human-in-the-Loop Barrier Detection**: Real-time detection of sign-in walls, Workday authentication, OTP, 2FA, and captchas. Pauses with an audible chime and ANSI terminal alert, letting you intervene and press `[Enter]` to resume.
- **Form Safety**: Attempts navigation automatically, waits only when required mandatory fields or validation errors block progression, and halts at the final **Review & Submit** step for human verification.
- **Interactive Terminal HUD**: Live non-blocking keyboard controls (`[P]` Pause, `[R]` Resume, `[N]` Skip Job, `[Q]` Quit).

---

## Project Structure

```text
orgs-app-job-auto-rustwright/
├── .env.example              # Multi-provider environment template
├── .gitignore                # Excludes secrets, caches, and private resumes
├── pyproject.toml            # Modern project packaging configuration
├── requirements.txt          # Python runtime dependencies
├── README.md                 # Project documentation
│
├── main.py                   # Core orchestrator, navigation & Workday flow
├── dom_analyzer.py           # Multi-provider LLM analyzer (JSON schema output)
├── controller.py             # Non-blocking CLI HUD & barrier detection
│
├── jobs_links.txt            # Plaintext target job URLs (one per line)
├── jobs_links.example.txt    # Template for target job URLs
└── data/
    ├── profile.json          # Your active candidate profile & resume data
    ├── profile.example.json  # Sanitized profile schema template
    └── resume.pdf            # (Ignored) Your PDF resume for auto-upload
```

---

## Quickstart

### 1. Clone & Set Up Virtual Environment

```powershell
git clone https://github.com/your-username/orgs-app-job-auto-rustwright.git
cd orgs-app-job-auto-rustwright

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Profile & Resume

1. Copy the example profile:
   ```powershell
   Copy-Item data\profile.example.json data\profile.json
   ```
2. Edit `data/profile.json` with your real personal details, experience array, and education.
3. Place your PDF resume in `data/resume.pdf`.

### 3. Configure LLM Provider

Copy the template environment file:
```powershell
Copy-Item .env.example .env
```

Open `.env` and set `LLM_PROVIDER`:

#### Option A: Ollama Local (Free & Offline)
```ini
LLM_PROVIDER="ollama_local"
OLLAMA_LOCAL_MODEL="llama3.2"
OLLAMA_LOCAL_URL="http://localhost:11434"
```
*(Make sure Ollama is running: `ollama run llama3.2`)*

#### Option B: Hugging Face Cloud (Free Serverless)
```ini
LLM_PROVIDER="huggingface"
HUGGINGFACE_API_KEY="hf_your_free_token"
HUGGINGFACE_MODEL="meta-llama/Llama-3.2-3B-Instruct"
```

#### Option C: Google Gemini
```ini
LLM_PROVIDER="gemini"
GEMINI_API_KEY="AIzaSyYourGeminiApiKey"
GEMINI_MODEL="gemini-2.5-flash"
```

### 4. Add Target Job URLs

Add job application links to `jobs_links.txt` (one URL per line):
```text
https://citi.wd5.myworkdayjobs.com/2/job/Pune-Maharashtra-India/Java-Full-Stack-Developer_26996236/apply
https://careers.mastercard.com/us/en/apply?jobSeqNo=MASRUSR289268EXTERNALENUS
```

### 5. Run the Automator

Run against all URLs in `jobs_links.txt`:
```powershell
python main.py
```

Or process a single URL directly:
```powershell
python main.py "https://citi.wd5.myworkdayjobs.com/2/job/.../apply"
```

---

## Interactive Controls

While the automator runs in non-headless Chromium, you can press any of these keys in your PowerShell terminal at any time:

| Key | Action |
| :---: | :--- |
| **`[P]`** or **`[Space]`** | **Pause Execution**: Pauses browser automation immediately. |
| **`[R]`** or **`[Enter]`** | **Resume Execution**: Resumes automation after human review. |
| **`[N]`** | **Skip Job**: Immediately skips the current application and proceeds to next. |
| **`[Q]`** | **Quit Automator**: Safely halts runner and cleans up browser context. |

---

## Safety & Security

- **Never Auto-Submits**: The runner purposefully halts on summary and review screens, prompting you for final manual submission.
- **Credential Safety**: Authentication credentials and OTPs are never collected or stored. The automator pauses and chimes when login screens or 2FA are detected, allowing you to log in securely.
- **Git Safety**: Personal PDF resumes and `.env` credentials are excluded by `.gitignore` by default.

---

## License

Distributed under the MIT License. See [LICENSE](LICENSE) for details.
