"""
core/groq_service.py
---------------------
Everything related to talking to Groq's AI API lives here.
If you ever want to swap Groq for another provider, or change how the
RAG context is injected, this is the one file to change.

NOTE (kept from the full build): this project previously hit
    TypeError: Client.__init__() got an unexpected keyword argument 'proxies'
That was caused by an old, pinned `groq==0.11.0` SDK being installed
alongside a newer `httpx` release. The fix is in requirements.txt
(groq upgraded to 1.7.0) - this file only instantiates `Groq(api_key=...)`
with no extra kwargs, which is correct and forward compatible.
"""

from groq import Groq

from config import Config

_client = None


def get_client() -> Groq:
    """Lazily create a single Groq client instance."""
    global _client
    if _client is None:
        if not Config.GROQ_API_KEY:
            raise RuntimeError(
                "GROQ_API_KEY is missing. Add it to your .env file locally, "
                "or set it in the Vercel/Render dashboard for deployments "
                "(see .env.example)."
            )
        # Only pass api_key - do NOT pass proxies/http_client kwargs here.
        _client = Groq(api_key=Config.GROQ_API_KEY)
    return _client


def build_system_prompt(language: str) -> str:
    """
    The system prompt is where 'Tamil and English Support' actually
    happens - we simply tell the model which language the user used
    and ask it to reply in the same language.
    """
    if language == "ta":
        language_instruction = (
            "The user is writing in Tamil. Reply naturally in Tamil "
            "(Tamil script), unless the user clearly asks for English."
        )
    else:
        language_instruction = (
            "The user is writing in English. Reply naturally in English, "
            "unless the user clearly asks for Tamil."
        )

    return (
        f"You are {Config.MASCOT_NAME}, the friendly AI mascot inside the "
        f"{Config.APP_NAME} mobile app. You are warm, encouraging, and to "
        f"the point - like a helpful pocket-sized study buddy. "
        f"{language_instruction} Keep replies concise and easy to read on "
        f"a small phone screen. If the user's question includes a "
        f"'Context:' block taken from an uploaded PDF, base your answer on "
        f"that context and say so briefly if the context doesn't contain "
        f"the answer."
    )


def get_ai_reply(user_message: str, language: str, history: list) -> str:
    """
    Send the conversation to Groq and return the assistant's reply text.
    `history` is a list of {"role": "user"/"assistant", "message": "..."}
    dicts, already loaded from SQLite, used to give the model short-term
    memory of the conversation. `history` should NOT include the current
    turn's message - only prior turns - to avoid sending the same user
    message to the model twice.
    """
    client = get_client()

    messages = [{"role": "system", "content": build_system_prompt(language)}]

    # Add recent chat history for context (keeps last N turns only)
    for item in history[-10:]:
        role = "assistant" if item["role"] == "assistant" else "user"
        messages.append({"role": role, "content": item["message"]})

    messages.append({"role": "user", "content": user_message})

    try:
        response = client.chat.completions.create(
            model=Config.GROQ_MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=1024,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller as-is
        raise RuntimeError(f"Groq API request failed: {exc}") from exc

    return response.choices[0].message.content.strip()
