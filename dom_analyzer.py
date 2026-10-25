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

import requests
from bs4 import BeautifulSoup

# Optional import for Gemini
try:
    from google import genai
    from google.genai import types
    _HAS_GENAI = True
except ImportError:
    _HAS_GENAI = False


def load_dotenv(dotenv_path: Optional[Union[str, Path]] = None, override: bool = True) -> None:
    """Load key-value pairs from a .env file into os.environ."""
    if dotenv_path is None:
        dotenv_path = Path(__file__).resolve().parent / ".env"
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


# Auto-load .env on import
load_dotenv()

# Baseline profile data based on candidate resume details
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


def load_profile(profile_path: Optional[Union[str, Path]] = None) -> dict[str, Any]:
    """Load candidate profile from a JSON file, falling back to DEFAULT_PROFILE."""
    if profile_path is None:
        profile_path = Path(__file__).resolve().parent / "data" / "profile.json"
    path = Path(profile_path)
    if path.is_file():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_PROFILE


def get_active_provider_info() -> dict[str, str]:
    """Detect and return metadata for the currently active LLM provider configured in .env."""
    raw_provider = os.environ.get("LLM_PROVIDER", "").strip().lower()

    # Normalize aliases
    if raw_provider in ("gemini", "google"):
        provider = "gemini"
    elif raw_provider in ("huggingface", "hf", "huggingface_cloud"):
        provider = "huggingface"
    elif raw_provider in ("ollama_cloud", "ollama-cloud", "remote_ollama"):
        provider = "ollama_cloud"
    elif raw_provider in ("ollama_local", "ollama-local", "ollama", "local"):
        provider = "ollama_local"
    else:
        # Fallback heuristic if not specified
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


def _clean_content(content: str, max_chars: int = 60000) -> str:
    """Clean HTML content by removing scripts, styles, and SVGs to optimize token usage."""
    if not ("<html" in content.lower() or "<form" in content.lower() or "<input" in content.lower()):
        return content[:max_chars]

    try:
        soup = BeautifulSoup(content, "html.parser")
        for tag in soup(["script", "style", "svg", "noscript", "head"]):
            tag.decompose()
        body = soup.body if soup.body else soup
        return str(body)[:max_chars]
    except Exception:
        return content[:max_chars]


def _parse_strict_json(raw_text: str) -> dict[str, str]:
    """Parse JSON from the model response, handling markdown blocks and conversational preambles."""
    cleaned = raw_text.strip()

    # Strip markdown fences if present
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        data = json.loads(cleaned)
    except Exception:
        # Fallback: Locate outer braces '{' ... '}'
        start_idx = cleaned.find("{")
        end_idx = cleaned.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            substring = cleaned[start_idx : end_idx + 1]
            data = json.loads(substring)
        else:
            raise ValueError(f"Could not parse valid JSON from LLM response:\n{raw_text[:500]}")

    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object from LLM, got: {type(data).__name__}")

    return {str(k): str(v) for k, v in data.items()}


def _build_prompt(sanitized_content: str, profile_data: dict[str, Any]) -> str:
    """Build standardized prompt for form mapping."""
    return f"""You are an expert browser automation assistant.
Analyze the following web page content (HTML/DOM or Markdown representation) and map the detected form fields to the candidate's profile data.

### Candidate Profile:
{json.dumps(profile_data, indent=2)}

### Web Page Content:
{sanitized_content}

### Requirements:
1. Identify all relevant input fields, textareas, selects, or interactive form controls on the page.
2. For each field that corresponds to an item in the candidate profile, generate a precise and valid CSS selector (prefer IDs like '#first-name', unique name attributes like 'input[name="first_name"]', or unique aria/data attributes).
3. Map each CSS selector to the corresponding profile value as a string.
4. Output a STRICT JSON object mapping each CSS selector to its value.
   Example:
   {{
     "#first-name": "Vinayak",
     "#experience-years": "4",
     "input[name='current_company']": "SS&C Technologies",
     "textarea[name='skills']": "Java, Spring Boot, Kafka, PostgreSQL"
   }}
5. Only include fields with matching information in the candidate profile. Do not make up unknown info.
6. Return purely valid JSON with no markdown wrapping, explanation, or additional text.
"""


def _call_gemini(prompt: str, model: str, api_key: str) -> str:
    """Call Google Gemini API via google-genai SDK."""
    if not _HAS_GENAI:
        raise ImportError("google-genai package is not installed. Run: pip install google-genai")
    if not api_key:
        raise ValueError(
            "Gemini API key is missing. Set GEMINI_API_KEY in your .env file or choose another LLM_PROVIDER."
        )

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1,
        ),
    )
    if not response.text:
        raise RuntimeError("Empty response received from Gemini API.")
    return response.text


def _call_huggingface(prompt: str, model: str, api_key: str, base_url: str) -> str:
    """Call Hugging Face Serverless Inference API."""
    if not api_key or api_key.strip() in ("", "hf_your_token_here"):
        raise ValueError(
            "Hugging Face token is missing. Please set HUGGINGFACE_API_KEY in your .env file.\n"
            "Get a free token with Read permissions at: https://huggingface.co/settings/tokens"
        )

    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }

    # 1. Try standard OpenAI-compatible chat completions endpoint first
    chat_url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are an automated browser form filler. You always output strictly valid JSON with no preamble or explanation.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 1500,
    }

    try:
        resp = requests.post(chat_url, headers=headers, json=payload, timeout=60)
        if resp.status_code == 200:
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception:
        pass

    # 2. Fallback to direct model inference endpoint
    direct_url = f"https://api-inference.huggingface.co/models/{model}"
    direct_payload = {
        "inputs": prompt,
        "parameters": {"max_new_tokens": 1500, "temperature": 0.1, "return_full_text": False},
    }
    resp = requests.post(direct_url, headers=headers, json=direct_payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    if isinstance(data, list) and len(data) > 0 and "generated_text" in data[0]:
        return data[0]["generated_text"]
    elif isinstance(data, dict) and "generated_text" in data:
        return data["generated_text"]
    return str(data)


def _call_ollama(prompt: str, model: str, host_url: str, api_key: Optional[str] = None) -> str:
    """Call Ollama native API (/api/chat) with structured JSON enforcement."""
    endpoint = f"{host_url.rstrip('/')}/api/chat"
    headers = {"Content-Type": "application/json"}
    if api_key and api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a browser automation assistant. Always output strictly valid JSON mapping CSS selectors to profile values.",
            },
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "format": "json",  # Native Ollama JSON grammar mode
        "options": {
            "temperature": 0.1,
        },
    }

    try:
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=90)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("message", {}).get("content", "")
        if not content:
            raise RuntimeError(f"Ollama returned empty message content from {endpoint}")
        return content
    except requests.exceptions.ConnectionError as ce:
        raise ConnectionError(
            f"Could not connect to Ollama at {host_url}. Ensure Ollama is running.\n"
            f"If running locally, run: 'ollama run {model}' or download from https://ollama.com\n"
            f"Details: {ce}"
        )


def analyze_dom(
    page_content: Union[str, Any],
    profile: Optional[dict[str, Any]] = None,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> dict[str, str]:
    """Analyze page HTML/markdown and return CSS selectors mapped to profile values.

    Supports:
        - Google Gemini ('gemini')
        - Hugging Face Cloud ('huggingface')
        - Ollama Cloud ('ollama_cloud')
        - Ollama Local ('ollama_local')

    Configuration is loaded automatically from .env (LLM_PROVIDER).
    """
    if hasattr(page_content, "content") and callable(page_content.content):
        raw_content = page_content.content()
    else:
        raw_content = str(page_content)

    provider_info = get_active_provider_info()
    active_provider = (provider or provider_info["provider"]).lower()
    active_model = model or provider_info["model"]

    profile_data = profile if profile is not None else load_profile()
    sanitized_content = _clean_content(raw_content)
    prompt = _build_prompt(sanitized_content, profile_data)

    if active_provider == "gemini":
        resolved_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
        raw_output = _call_gemini(prompt, active_model, resolved_key)

    elif active_provider == "huggingface":
        resolved_key = api_key or os.environ.get("HUGGINGFACE_API_KEY", "")
        base_url = os.environ.get("HUGGINGFACE_BASE_URL", "https://api-inference.huggingface.co/v1")
        raw_output = _call_huggingface(prompt, active_model, resolved_key, base_url)

    elif active_provider == "ollama_cloud":
        host_url = os.environ.get("OLLAMA_CLOUD_URL", "https://your-remote-ollama-host.com")
        resolved_key = api_key or os.environ.get("OLLAMA_CLOUD_API_KEY")
        raw_output = _call_ollama(prompt, active_model, host_url, resolved_key)

    elif active_provider == "ollama_local":
        host_url = os.environ.get("OLLAMA_LOCAL_URL", "http://localhost:11434")
        raw_output = _call_ollama(prompt, active_model, host_url, None)

    else:
        raise ValueError(
            f"Unknown LLM provider: '{active_provider}'. Supported options: 'gemini', 'huggingface', 'ollama_cloud', 'ollama_local'"
        )

    return _parse_strict_json(raw_output)


# Convenience alias
analyze_form_fields = analyze_dom


if __name__ == "__main__":
    sample_html = """
    <form id="job-application">
        <label for="first-name">First Name:</label>
        <input type="text" id="first-name" name="firstName" required />

        <label for="current-title">Job Title / Role:</label>
        <input type="text" id="current-title" name="jobTitle" />

        <label for="experience-years">Years of Experience:</label>
        <input type="number" id="experience-years" name="expYears" />

        <label for="company">Current / Last Company:</label>
        <input type="text" id="company" name="companyName" />

        <label for="skills-input">Key Technologies / Skills:</label>
        <textarea id="skills-input" name="skills"></textarea>
    </form>
    """

    info = get_active_provider_info()
    print("=" * 60)
    print("orgs-app-job-auto-rustwright - Provider Status")
    print("=" * 60)
    print(f"Active Provider : {info['provider']}")
    print(f"Model           : {info['model']}")
    print(f"Endpoint/Host   : {info['endpoint']}")
    print("=" * 60)

    try:
        print("[*] Testing DOM analysis with sample form...")
        results = analyze_dom(sample_html)
        print("\nExtracted Form Mappings:")
        print(json.dumps(results, indent=2))
    except Exception as e:
        print(f"\n[!] Provider test encountered an error:\n    {e}")
        print("\nTo switch or configure your provider, edit the .env file:")
        print("  - LLM_PROVIDER='gemini'       -> Set GEMINI_API_KEY")
        print("  - LLM_PROVIDER='huggingface'  -> Set HUGGINGFACE_API_KEY")
        print("  - LLM_PROVIDER='ollama_cloud' -> Set OLLAMA_CLOUD_URL & OLLAMA_CLOUD_MODEL")
        print("  - LLM_PROVIDER='ollama_local' -> Run 'ollama run llama3.2' locally")
