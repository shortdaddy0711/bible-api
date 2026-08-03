import requests
import json
import time

BASE_URL = "http://localhost:8080"

def test_chat():
    query = "천지창조에 대해 성경 내용을 바탕으로 설명해주고, 관련 구절을 인용해줘."
    payload = {
        "message": query,
        "history": []
    }
    
    print(f"Sending query: {query}")
    try:
        response = requests.post(f"{BASE_URL}/api/chat", json=payload)
        if response.status_code == 200:
            result = response.json()
            print("\n--- Agent Response ---")
            print(f"Thought: {result.get('thought')}")
            print(f"Answer:\n{result.get('answer')}")
            print("\n--- Citations ---")
            print(json.dumps(result.get('citations'), indent=2, ensure_ascii=False))
        else:
            print(f"Chat failed: {response.status_code}")
            print(response.text)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # Wait for server to be ready
    time.sleep(3)
    test_chat()
