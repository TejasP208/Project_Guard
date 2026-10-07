"""Manual check against a running API; test discovery never sends requests."""
import os
import requests

url = "http://127.0.0.1:8000/check-plagiarism"
data = {
    "title": "Test Title",
    "description": "Test abstract"
}
files = {"file": ("test.txt", b"Academic project description", "text/plain")}

if __name__ == "__main__":
    token = os.getenv("PROJECT_GUARD_TEST_SESSION_TOKEN")
    if not token:
        raise SystemExit("Set PROJECT_GUARD_TEST_SESSION_TOKEN to a student Clerk session token.")
    response = requests.post(url, data=data, files=files, headers={"Authorization": f"Bearer {token}"}, timeout=100)
    print("Status Code:", response.status_code)
    print("Response:", response.text)
