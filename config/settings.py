import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional, Union

# Ensure Windows consoles don't crash on UTF-8 characters
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Root directory of the application
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PROFILE_DIR = DATA_DIR / "profile"
RESUME_DIR = DATA_DIR / "resume"


def load_dotenv(dotenv_path: Optional[Union[str, Path]] = None, override: bool = True) -> None:
    """Load key-value pairs from a .env file into os.environ."""
    if dotenv_path is None:
        dotenv_path = BASE_DIR / ".env"
    path = Path(dotenv_path)
    if path.is_file():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if override or key not in os.environ:
                        os.environ[key] = val


# Load .env upon module import
load_dotenv()


def _read_json_file(path: Path) -> Any:
    """Helper to safely read a JSON file."""
    if path.is_file():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def load_section_profile(section: str) -> dict[str, Any]:
    """Load specific profile section(s) to provide focused RAG context to the LLM.

    Supported sections:
      - 'personal'   -> profile_personal.json + profile_address.json
      - 'experience' -> profile_experience.json + profile_skills.json
      - 'education'  -> profile_education.json
      - 'skills'     -> profile_skills.json
      - 'screening'  -> profile_screening.json + profile_qa.json
      - 'qa'         -> profile_qa.json
    """
    sec_lower = section.lower().strip()
    result: dict[str, Any] = {}

    if sec_lower in ("personal", "contact", "address"):
        personal = _read_json_file(PROFILE_DIR / "profile_personal.json") or {}
        address = _read_json_file(PROFILE_DIR / "profile_address.json") or {}
        result.update(personal)
        result["address"] = address

    elif sec_lower in ("experience", "work"):
        experiences = _read_json_file(PROFILE_DIR / "profile_experience.json") or []
        skills = _read_json_file(PROFILE_DIR / "profile_skills.json") or {}
        result["experience"] = experiences
        result["professional"] = skills

    elif sec_lower in ("education", "academics"):
        education = _read_json_file(PROFILE_DIR / "profile_education.json") or []
        result["education"] = education

    elif sec_lower in ("screening", "questions", "qa"):
        screening = _read_json_file(PROFILE_DIR / "profile_screening.json") or {}
        qa_bank = _read_json_file(PROFILE_DIR / "profile_qa.json") or {}
        result["screening_defaults"] = screening
        result["questions"] = qa_bank

    else:
        # Fallback to loading direct file if named profile_<section>.json
        custom_file = PROFILE_DIR / f"profile_{sec_lower}.json"
        if custom_file.is_file():
            data = _read_json_file(custom_file)
            if isinstance(data, dict):
                result.update(data)
            else:
                result[sec_lower] = data

    return result


def load_profile(section: Optional[str] = None) -> dict[str, Any]:
    """Load unified profile or specific section context from data/profile/ directory.

    If section is specified, returns only the focused section data (RAG approach).
    If section is None, merges all modular profile files into a comprehensive profile.
    """
    if section:
        return load_section_profile(section)

    # Modular unified profile from data/profile/
    profile: dict[str, Any] = {}

    personal = _read_json_file(PROFILE_DIR / "profile_personal.json") or {}
    address = _read_json_file(PROFILE_DIR / "profile_address.json") or {}
    experience = _read_json_file(PROFILE_DIR / "profile_experience.json") or []
    education = _read_json_file(PROFILE_DIR / "profile_education.json") or []
    skills = _read_json_file(PROFILE_DIR / "profile_skills.json") or {}
    screening = _read_json_file(PROFILE_DIR / "profile_screening.json") or {}
    qa_bank = _read_json_file(PROFILE_DIR / "profile_qa.json") or {}

    profile["personal"] = personal
    if address:
        profile["personal"]["address"] = address.get("address_line1", "")
        profile["personal"]["city"] = address.get("city", "")
        profile["personal"]["state"] = address.get("state_province", "")
        profile["personal"]["postal_code"] = address.get("postal_code", "")
        profile["personal"]["country"] = address.get("country", "")
        profile["address"] = address

    # Top-level convenience aliases
    if personal:
        profile["first_name"] = personal.get("first_name", "")
        profile["last_name"] = personal.get("last_name", "")
        profile["full_name"] = personal.get("full_name", "")
        profile["email"] = personal.get("email", "")
        profile["phone"] = personal.get("phone", "")

    profile["professional"] = skills
    if skills:
        profile["job_title"] = skills.get("job_title", "")
        profile["years_of_experience"] = skills.get("years_of_experience", "")
        profile["skills"] = skills.get("primary_skills", [])
        profile["summary"] = skills.get("summary", "")

    profile["experience"] = experience
    profile["education"] = education
    profile["screening_defaults"] = screening
    profile["questions"] = qa_bank

    return profile


def save_learned_qa(question: str, answer: str) -> None:
    """Persist newly answered screening questions into data/profile/profile_qa.json."""
    if not question or not answer:
        return

    qa_file = PROFILE_DIR / "profile_qa.json"
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    qa_data: dict[str, str] = _read_json_file(qa_file) or {}
    clean_q = question.strip()
    clean_a = str(answer).strip()

    if clean_q and clean_a:
        qa_data[clean_q] = clean_a
        try:
            with open(qa_file, "w", encoding="utf-8") as f:
                json.dump(qa_data, f, indent=2)
            print(f"  \033[1;36m[💾 LEARNED] Saved to profile_qa.json: '{clean_q}' -> '{clean_a}'\033[0m")
        except Exception as e:
            print(f"[-] Note saving learned Q&A: {e}")


def get_resume_path(job_url: Optional[str] = None) -> Path:
    """Resolve resume path, prioritizing job-specific custom resume (data/resume/resume_<job_id>.pdf)."""
    RESUME_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Custom resume per job ID if present
    if job_url:
        job_id_match = re.search(r"(?:_R|_|job/|jobs/|/)([A-Za-z0-9_-]{5,30})(?:/|\?|$)", job_url)
        if job_id_match:
            job_id = job_id_match.group(1)
            custom_candidate = RESUME_DIR / f"resume_{job_id}.pdf"
            if custom_candidate.is_file():
                print(f"[*] Found custom tailored resume for Job ID '{job_id}': {custom_candidate.name}")
                return custom_candidate

    # 2. Default resume in data/resume/resume.pdf
    nested_default = RESUME_DIR / "resume.pdf"
    if nested_default.is_file():
        return nested_default

    # 3. Fallback to data/resume.pdf
    root_default = DATA_DIR / "resume.pdf"
    return root_default


def load_job_urls(arg_target: Optional[str] = None) -> list[str]:
    """Load job URLs from direct CLI argument, data/jobs_links.md, or data/jobs_links.txt."""
    if arg_target and (arg_target.startswith("http://") or arg_target.startswith("https://")):
        print(f"\033[1;36m[+] Target URL provided via CLI:\033[0m {arg_target}")
        return [arg_target]

    if arg_target:
        target_file = Path(arg_target)
    else:
        # Check jobs_links.md first, then jobs_links.txt
        md_file = DATA_DIR / "jobs_links.md"
        txt_file = DATA_DIR / "jobs_links.txt"
        target_file = md_file if md_file.is_file() else txt_file

    if not target_file.is_file():
        print(f"\n\033[1;31m[-] Error: Job links file not found: '{target_file}'\033[0m")
        print("Please create 'data/jobs_links.md' or 'data/jobs_links.txt' with your target URLs.\n")
        sys.exit(1)

    try:
        content = target_file.read_text(encoding="utf-8")
        urls: list[str] = []

        # Parse both markdown links `[Title](https://...)` and raw URLs
        for line in content.splitlines():
            line_str = line.strip()
            if not line_str or line_str.startswith("#"):
                continue

            md_matches = re.findall(r"\[.*?\]\((https?://[^\s\)]+)\)", line_str)
            if md_matches:
                urls.extend(md_matches)
            else:
                raw_match = re.search(r"(https?://[^\s]+)", line_str)
                if raw_match:
                    urls.append(raw_match.group(1))

        if urls:
            rel_name = target_file.relative_to(BASE_DIR) if target_file.is_relative_to(BASE_DIR) else target_file.name
            print(f"\033[1;32m[+] Loaded {len(urls)} job URL(s) from:\033[0m {rel_name}")
            return urls

    except Exception as e:
        print(f"[-] Error reading {target_file}: {e}")

    print(f"\n\033[1;31m[-] Error: No valid URLs found in '{target_file.name}'.\033[0m")
    sys.exit(1)


def get_active_provider_info() -> dict[str, str]:
    """Detect and return metadata for the currently active LLM provider configured in .env."""
    raw_provider = os.environ.get("LLM_PROVIDER", "").strip().lower()

    if raw_provider in ("gemini", "google"):
        provider = "gemini"
    elif raw_provider in ("huggingface", "hf", "huggingface_cloud"):
        provider = "huggingface"
    elif raw_provider in ("ollama_cloud", "ollama-cloud", "remote_ollama"):
        provider = "ollama_cloud"
    elif raw_provider in ("ollama_local", "ollama-local", "ollama", "local"):
        provider = "ollama_local"
    else:
        if os.environ.get("GEMINI_API_KEY"):
            provider = "gemini"
        elif os.environ.get("HUGGINGFACE_API_KEY") and os.environ.get("HUGGINGFACE_API_KEY") != "hf_your_token_here":
            provider = "huggingface"
        else:
            provider = "gemini"

    if provider == "gemini":
        model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        return {
            "provider": "gemini",
            "model": model,
            "display_name": f"Google Gemini ({model})",
            "endpoint": "Google AI Studio",
        }
    elif provider == "huggingface":
        model = os.environ.get("HUGGINGFACE_MODEL", "meta-llama/Llama-3.2-3B-Instruct")
        base_url = os.environ.get("HUGGINGFACE_BASE_URL", "https://api-inference.huggingface.co/v1")
        return {
            "provider": "huggingface",
            "model": model,
            "display_name": f"HuggingFace Cloud ({model})",
            "endpoint": base_url,
        }
    elif provider == "ollama_cloud":
        model = os.environ.get("OLLAMA_CLOUD_MODEL", "llama3.2")
        host_url = os.environ.get("OLLAMA_CLOUD_URL", "https://your-remote-ollama-host.com")
        return {
            "provider": "ollama_cloud",
            "model": model,
            "display_name": f"Ollama Cloud ({model})",
            "endpoint": host_url,
        }
    else:  # ollama_local
        model = os.environ.get("OLLAMA_LOCAL_MODEL", "llama3.2")
        host_url = os.environ.get("OLLAMA_LOCAL_URL", "http://localhost:11434")
        return {
            "provider": "ollama_local",
            "model": model,
            "display_name": f"Ollama Local ({model})",
            "endpoint": host_url,
        }
