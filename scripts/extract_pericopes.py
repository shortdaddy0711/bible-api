import os
import requests
import json
import re
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import time
import csv
import sys

# Load environment variables
load_dotenv()
ESV_API_KEY = os.environ.get("ESV_API_KEY")

if not ESV_API_KEY:
    raise ValueError("ESV_API_KEY not found in .env")

KO_TO_EN_BOOKS = {
    '창세기': 'Genesis', '출애굽기': 'Exodus', '레위기': 'Leviticus', '민수기': 'Numbers', '신명기': 'Deuteronomy',
    '여호수아': 'Joshua', '사사기': 'Judges', '룻기': 'Ruth', '사무엘상': '1 Samuel', '사무엘하': '2 Samuel',
    '열왕기상': '1 Kings', '열왕기하': '2 Kings', '역대상': '1 Chronicles', '역대하': '2 Chronicles',
    '에스라': 'Ezra', '느헤미야': 'Nehemiah', '에스더': 'Esther', '욥기': 'Job', '시편': 'Psalms',
    '잠언': 'Proverbs', '전도서': 'Ecclesiastes', '아가': 'Song of Solomon', '이사야': 'Isaiah',
    '예레미야': 'Jeremiah', '예레미야애가': 'Lamentations', '에스겔': 'Ezekiel', '다니엘': 'Daniel',
    '호세아': 'Hosea', '요엘': 'Joel', '아모스': 'Amos', '오바댜': 'Obadiah', '요나': 'Jonah',
    '미가': 'Micah', '나훔': 'Nahum', '하박국': 'Habakkuk', '스바냐': 'Zephaniah', '학개': 'Haggai',
    '스가랴': 'Zechariah', '말라기': 'Malachi', '마태복음': 'Matthew', '마가복음': 'Mark',
    '누가복음': 'Luke', '요한복음': 'John', '사도행전': 'Acts', '로마서': 'Romans',
    '고린도전서': '1 Corinthians', '고린도후서': '2 Corinthians', '갈라디아서': 'Galatians',
    '에베소서': 'Ephesians', '빌립보서': 'Philippians', '골로새서': 'Colossians',
    '데살로니가전서': '1 Thessalonians', '데살로니가후서': '2 Thessalonians',
    '디모데전서': '1 Timothy', '디모데후서': '2 Timothy', '디도서': 'Titus', '빌레몬서': 'Philemon',
    '히브리서': 'Hebrews', '야고보서': 'James', '베드로전서': '1 Peter', '베드로후서': '2 Peter',
    '요한일서': '1 John', '요한이서': '2 John', '요한삼서': '3 John', '유다서': 'Jude', '요한계시록': 'Revelation'
}

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

        en_book = KO_TO_EN_BOOKS.get(ko_book)
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
