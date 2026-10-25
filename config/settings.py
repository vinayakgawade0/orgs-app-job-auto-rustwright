import json
import os
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

# Baseline fallback candidate profile
DEFAULT_PROFILE: dict[str, Any] = {
    "first_name": "Vinayak",
    "full_name": "Vinayak",
    "job_title": "Senior Java Backend Engineer",
    "current_role": "Senior Java Backend Engineer",
    "years_of_experience": "4",
    "current_company": "SS&C Technologies",
    "experience": [
        {
            "company": "SS&C Technologies",
            "role": "Senior Java Backend Engineer",
            "duration_years": "4",
        }
    ],
    "skills": ["Java", "Spring Boot", "Kafka", "PostgreSQL"],
    "skills_summary": "Java, Spring Boot, Kafka, PostgreSQL",
    "summary": (
        "Senior Java Backend Engineer with 4 years of experience at SS&C Technologies, "
        "specializing in Java, Spring Boot, Kafka, and PostgreSQL."
    ),
}


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


def load_profile(profile_path: Optional[Union[str, Path]] = None) -> dict[str, Any]:
    """Load candidate profile from a JSON file, falling back to DEFAULT_PROFILE."""
    if profile_path is None:
        profile_path = BASE_DIR / "data" / "profile.json"
    path = Path(profile_path)
    if path.is_file():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_PROFILE


def load_job_urls(arg_target: Optional[str] = None) -> list[str]:
    """Load job URLs from a direct CLI argument or from data/jobs_links.txt."""
    if arg_target and (arg_target.startswith("http://") or arg_target.startswith("https://")):
        print(f"\033[1;36m[+] Target URL provided via CLI:\033[0m {arg_target}")
        return [arg_target]

    if arg_target:
        target_file = Path(arg_target)
    else:
        # Default to data/jobs_links.txt, fallback to root jobs_links.txt if present
        data_file = BASE_DIR / "data" / "jobs_links.txt"
        root_file = BASE_DIR / "jobs_links.txt"
        target_file = data_file if data_file.is_file() else root_file

    if not target_file.is_file():
        print(f"\n\033[1;31m[-] Error: File not found: '{target_file}'\033[0m")
        print("Please create 'data/jobs_links.txt' with one job URL per line.\n")
        sys.exit(1)

    try:
        content = target_file.read_text(encoding="utf-8")
        urls = [
            line.strip()
            for line in content.splitlines()
            if line.strip() and not line.strip().startswith("#") and line.strip().startswith("http")
        ]
        if urls:
            rel_name = target_file.relative_to(BASE_DIR) if target_file.is_relative_to(BASE_DIR) else target_file.name
            print(f"\033[1;32m[+] Loaded {len(urls)} job URL(s) from:\033[0m {rel_name}")
            return urls
    except Exception as e:
        print(f"[-] Error reading {target_file}: {e}")

    print(f"\n\033[1;31m[-] Error: No valid URLs found in '{target_file}'.\033[0m")
    print("Please add at least one job link starting with http:// or https:// (one per line).\n")
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
