"""
src/llm/risk_summarizer.py
Local LLM inference via Ollama.
Model: qwen2.5:3b — better instruction following than phi3:mini, same RAM footprint.
"""

import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5:3b"


def check_ollama_running() -> bool:
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def check_model_pulled() -> bool:
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=3)
        models = [m["name"] for m in resp.json().get("models", [])]
        return any("qwen2.5" in m for m in models)
    except Exception:
        return False


def generate_risk_report(prompt: str, temperature: float = 0.2) -> str:
    if not check_ollama_running():
        print("[LLM] Ollama not running. Start it: ollama serve")
        return _fallback_report()

    if not check_model_pulled():
        print(f"[LLM] Model '{MODEL_NAME}' not found. Run: ollama pull qwen2.5:3b")
        return _fallback_report()

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": 600,
            "top_p": 0.9,
        },
    }

    try:
        print(f"[LLM] Running {MODEL_NAME} inference (CPU — ~30-60s)...")
        resp = requests.post(OLLAMA_URL, json=payload, timeout=180)
        resp.raise_for_status()
        report = resp.json().get("response", "").strip()
        print(f"[LLM] Done. {len(report.split())} words generated.")
        return report
    except requests.Timeout:
        print("[LLM] Timeout. Model too slow — try: ollama pull qwen2.5:3b")
        return _fallback_report()
    except Exception as e:
        print(f"[LLM] Error: {e}")
        return _fallback_report()


def _fallback_report() -> str:
    return (
        "[FALLBACK — Ollama not available]\n"
        "Setup: curl -fsSL https://ollama.ai/install.sh | sh\n"
        "       ollama pull qwen2.5:3b\n"
        "       ollama serve"
    )


if __name__ == "__main__":
    print("Ollama running:", check_ollama_running())
    print("Model pulled:", check_model_pulled())