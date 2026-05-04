import requests
import os
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://api-inference.huggingface.co/models/microsoft/phi-2"
headers = {"Authorization": f"Bearer {os.getenv('HF_API_KEY')}"}

response = requests.post(
    API_URL,
    headers=headers,
    json={"inputs": "Explain what is half for a grade 3 student"}
)

print("STATUS:", response.status_code)
print("RAW RESPONSE:", response.text)