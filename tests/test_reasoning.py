import requests
import json

BASE_URL = "http://localhost:8080"

def test_search():
    query = "태초에 하나님이 천지를 창조하시니라"
    response = requests.get(f"{BASE_URL}/api/bible/search", params={"query": query})
    if response.status_code == 200:
        print("Search successful:")
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    else:
        print(f"Search failed: {response.status_code}")
        print(response.text)

if __name__ == "__main__":
    test_search()
