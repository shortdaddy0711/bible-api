import os
import requests
import json
import re
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
ESV_API_KEY = os.environ.get("ESV_API_KEY")

if not ESV_API_KEY:
    raise ValueError("ESV_API_KEY not found in .env")

def get_esv_passage_with_headings(query):
    """
    Fetch a passage from the ESV API with headings and verse numbers included.
    """
    url = "https://api.esv.org/v3/passage/text/"
    params = {
        'q': query,
        'include-headings': 'true',
        'include-passage-references': 'false',
        'include-verse-numbers': 'true',
        'include-first-verse-numbers': 'true',
        'include-footnotes': 'false',
        'include-short-copyright': 'false',
        'line-length': 0
    }
    headers = {'Authorization': f'Token {ESV_API_KEY}'}
    
    response = requests.get(url, params=params, headers=headers)
    if response.status_code != 200:
        print(f"Error fetching {query}: {response.status_code}")
        return None
    return response.json()

def parse_headings(passage_text):
    """
    Simple parser to find headings and the verse that follows.
    Heuristic: Headings are lines followed by an empty line or a verse marker [1].
    """
    lines = passage_text.strip().split('\n')
    pericopes = []
    
    # Regex to find verse markers like [1], [1:1], [15:10]
    verse_regex = re.compile(r'\[(\d+(?::\d+)?)\]')
    
    current_heading = None
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
            
        # Check if this line contains a verse marker
        match = verse_regex.search(line)
        if match:
            verse_label = match.group(1)
            verse_num = int(verse_label.split(':')[-1]) if ':' in verse_label else int(verse_label)
            
            if current_heading:
                pericopes.append({
                    "title": current_heading,
                    "start_verse": verse_num
                })
                current_heading = None
        else:
            # If not a verse marker and looks like a title (not too long, no brackets)
            if '[' not in line and len(line) < 100:
                current_heading = line
                
    return pericopes

def test_extraction():
    # Let's test with Mark 1 (has clear headings like 'John the Baptist Prepares the Way')
    book = "Mark"
    chapter = 1
    query = f"{book} {chapter}"
    
    print(f"Fetching {query} from ESV API...")
    data = get_esv_passage_with_headings(query)
    
    if not data or not data['passages']:
        print("No data received.")
        return

    passage = data['passages'][0]
    # print("\n--- RAW PASSAGE START ---")
    # print(passage[:500]) # Peek at first 500 chars
    # print("--- RAW PASSAGE END ---\n")
    
    pericopes = parse_headings(passage)
    
    print(f"Extracted {len(pericopes)} pericopes for {query}:")
    for p in pericopes:
        print(f"- {p['title']} (Starts at Verse {p['start_verse']})")
        
    # Save test result
    test_result = {book: {str(chapter): pericopes}}
    with open("pericope_test.json", "w", encoding="utf-8") as f:
        json.dump(test_result, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    test_extraction()
