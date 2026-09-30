import os
from pathlib import Path
from dotenv import load_dotenv
from groq import AsyncGroq, Groq

# Ensure .env from Project_Guard directory is loaded
env_file = Path(__file__).resolve().parent / ".env"
if env_file.exists():
    load_dotenv(dotenv_path=env_file, override=True)
else:
    load_dotenv()

_async_groq_client = None
_groq_client = None


def _get_api_key() -> str:
    for key in ["GROQ_API_KEY", "API_key", "API_KEY", "api_key", "API_key "]:
        val = os.getenv(key)
        if val and val.strip():
            return val.strip()
    raise RuntimeError("Groq API key is missing. Set GROQ_API_KEY in the environment or .env file.")


def _get_async_groq_client() -> AsyncGroq:
    global _async_groq_client
    api_key = _get_api_key()
    if _async_groq_client is None:
        _async_groq_client = AsyncGroq(api_key=api_key)
    return _async_groq_client


SYSTEM_PROMPT = """
You are Axiom AI, an intelligent Project Finder and Academic Assistant for students.

Your responsibilities:
1. Help students find and understand their existing projects.
2. Assist in identifying potential plagiarism risks in their project descriptions or ideas.
3. Provide suggestions to improve originality and reduce plagiarism.
4. Answer doubts related to their ongoing or submitted academic projects.
5. Guide students in improving structure, clarity, and innovation in their work.

Behavior rules:
- Be helpful, clear, and concise.
- Always respond in a student-friendly tone.
- If plagiarism risk is detected, explain WHY and suggest improvements.
- Encourage originality and ethical academic practices.
- If the query is unclear, ask follow-up questions.

Never:
- Generate plagiarized content.
- Encourage copying.

Give the answer in plain text.
Do NOT use *, **, markdown, or bullet symbols.
Keep formatting simple and clean.
Also consider the past history of the chat.
do consider the project title and project absract and project ppt
"""


async def Chatbot_stream(prompt: str):
    client = _get_async_groq_client()
    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    stream = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        stream=True,
    )
    async for chunk in stream:
        content = chunk.choices[0].delta.content
        if content:
            yield content
