import requests

def test_search(query):
    url = f"http://localhost:8080/api/bible/search?query={query}&limit=2"
    print(f"\n[Test Search] Query: {query}")
    try:
        response = requests.get(url)
        if response.status_code == 200:
            results = response.json()
            print(f"Found {len(results)} results:")
            for r in results:
                print(f"--- {r['book']} {r['chapter']}:{r['verse_range']} ({r['title']}) ---")
                print(f"Content: {r['content'][:200]}...")
                print(f"Similarity: {r['similarity']:.4f}")
        else:
            print(f"Error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Failed to connect to API: {e}")

if __name__ == "__main__":
    # Test query related to a book we just uploaded (e.g., Psalms or John)
    test_search("The Lord is my shepherd")
    test_search("creation of heaven and earth")
