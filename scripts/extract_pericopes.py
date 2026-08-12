import os
import sys
import requests
import json
import re
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import time
import csv

# Shared book mapping (single source of truth)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from books import KO_TO_EN

# Load environment variables
load_dotenv()
ESV_API_KEY = os.environ.get("ESV_API_KEY")

if not ESV_API_KEY:
    raise ValueError("ESV_API_KEY not found in .env")

def fetch_passage_html(query):
    # Bypass DNS issues by using direct IP of api.esv.org
    url = "https://34.231.140.119/v3/passage/html/"
    params = {
        'q': query,
        'include-headings': 'true',
        'include-passage-references': 'false',
        'include-verse-numbers': 'true',
        'include-first-verse-numbers': 'true',
        'include-footnotes': 'false',
        'include-short-copyright': 'false'
    }
    headers = {
        'Authorization': f'Token {ESV_API_KEY}',
        'Host': 'api.esv.org'
    }
    
    max_retries = 5
    for attempt in range(max_retries):
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            response = requests.get(url, params=params, headers=headers, timeout=30, verify=False)
            if response.status_code == 429:
                wait_time = (attempt + 1) * 10
                print(f"  [!] Rate limited. Waiting {wait_time}s...")
                time.sleep(wait_time)
                continue
            response.raise_for_status()
            return response.json()
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"  [X] Error fetching {query}: {e}")
                return None
            time.sleep(2)
    return None

def parse_pericopes_from_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    pericopes = []
    elements = soup.find_all(['h2', 'h3', 'h4', 'b', 'span'])
    current_heading = None
    
    for el in elements:
        if el.name in ['h2', 'h3', 'h4']:
            text = el.get_text().strip()
            if not re.match(r'^[A-Za-z0-9& ]+ \d+$', text) and len(text) > 0:
                current_heading = text
        elif el.name in ['b', 'span']:
            classes = el.get('class', [])
            if any(c in classes for c in ['verse-num', 'v', 'chapter-num', 'verse-num inline']):
                if current_heading:
                    verse_text = el.get_text().strip().replace('\xa0', ' ').split(' ')[0].strip('[]')
                    try:
                        verse_num = int(verse_text.split(':')[-1]) if ':' in verse_text else int(verse_text)
                        pericopes.append({"title": current_heading, "start": verse_num})
                        current_heading = None
                    except ValueError:
                        continue
    return pericopes

def run_extraction():
    pericope_map = {}
    if os.path.exists("pericope_map.json"):
        with open("pericope_map.json", "r", encoding="utf-8") as f:
            pericope_map = json.load(f)
        print(f"Loaded existing map with {len(pericope_map)} books.")

    bible_structure = []
    with open('bible_chapter_tokens.csv', mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            bible_structure.append(row)

    total = len(bible_structure)
    print(f"Starting extraction for {total} chapters...")

    for i, entry in enumerate(bible_structure):
        ko_book = entry['book']
        chapter = entry['chapter']
        
        # Skip if already processed
        if ko_book in pericope_map and str(chapter) in pericope_map[ko_book]:
            continue

        en_book = KO_TO_EN.get(ko_book)
        if not en_book: continue
            
        query = f"{en_book} {chapter}"
        print(f"[{i+1}/{total}] Processing {query}...")
        
        data = fetch_passage_html(query)
        if data and data['passages']:
            pericopes = parse_pericopes_from_html(data['passages'][0])
            if ko_book not in pericope_map: pericope_map[ko_book] = {}
            pericope_map[ko_book][str(chapter)] = pericopes
            
            with open("pericope_map.json", "w", encoding="utf-8") as f:
                json.dump(pericope_map, f, ensure_ascii=False, indent=2)
        
        time.sleep(0.5)

    print("\nExtraction finished successfully!")

if __name__ == "__main__":
    run_extraction()
