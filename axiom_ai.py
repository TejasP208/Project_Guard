import os

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

_groq_client = None


def _get_groq_client():
    global _groq_client
    api_key = os.getenv("API_key")
    if not api_key:
        raise RuntimeError("Groq API key is missing. Set GROQ_API_KEY in the environment or .env file.")
    if _groq_client is None:
        _groq_client = Groq(api_key=api_key)
    return _groq_client

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

def Chatbot_stream(prompt: str):
    stream = _get_groq_client().chat.completions.create(
        model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        messages=[
             {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}],
        stream=True,
    )
    for chunk in stream:
        content = chunk.choices[0].delta.content
        if content:
            yield content
