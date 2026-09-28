import requests
import io

url = "http://127.0.0.1:8000/check-plagiarism"
data = {
    "title": "Test Title",
    "description": "Test abstract"
}
files = {
    "file": ("test.pdf", io.BytesIO(b"Hello world, testing 1 2 3"), "application/pdf")
}

try:
    response = requests.post(url, data=data, files=files)
    print("Status Code:", response.status_code)
    print("Response JSON/Text:", response.text)
except Exception as e:
    print("Failed request:", e)
