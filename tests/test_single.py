import os
import requests
import json
import re
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()
ESV_API_KEY = os.environ.get("ESV_API_KEY")

def fetch_passage_html(query):
    url = "https://34.231.140.119/v3/passage/html/"
    params = {
        'q': query,
        'include-headings': 'true',
    }
    headers = {
        'Authorization': f'Token {ESV_API_KEY}',
        'Host': 'api.esv.org'
    }
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    response = requests.get(url, params=params, headers=headers, timeout=30, verify=False)
    return response.json()

try:
    print("Testing Psalms 81...")
    data = fetch_passage_html("Psalms 81")
    print("Success!")
    print(data['passages'][0][:200])
except Exception as e:
    print(f"FAILED: {e}")
