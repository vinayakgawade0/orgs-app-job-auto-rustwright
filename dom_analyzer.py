"""Backward-compatibility shim for dom_analyzer."""
from config.settings import (
    DEFAULT_PROFILE,
    get_active_provider_info,
    load_dotenv,
    load_profile,
)
from llm.dom_analyzer import (
    _clean_content,
    _parse_strict_json,
    analyze_dom,
    analyze_form_fields,
)

__all__ = [
    "analyze_dom",
    "analyze_form_fields",
    "load_dotenv",
    "load_profile",
    "get_active_provider_info",
    "DEFAULT_PROFILE",
]

if __name__ == "__main__":
    import json
    sample_html = """
    <form id="job-application">
        <label for="first-name">First Name:</label>
        <input type="text" id="first-name" name="firstName" required />
        <label for="current-title">Job Title / Role:</label>
        <input type="text" id="current-title" name="jobTitle" />
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
        results = analyze_dom(sample_html)
        print("Sample Form Analysis Result:")
        print(json.dumps(results, indent=2))
    except Exception as e:
        print(f"[!] Provider test notice: {e}")
