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
        # Streaming endpoint is now the only chat API
        response = requests.post(f"{BASE_URL}/api/chat/stream", json=payload, stream=True, headers={"Accept": "text/event-stream"})
        if response.status_code == 200:
            for line in response.iter_lines():
                if line and line.startswith(b"data: "):
                    event = json.loads(line[6:])
                    if event.get("type") == "delta":
                        continue
                    elif event.get("type") == "done":
                        print("\n--- Agent Response ---")
                        print(f"Thought: {event.get('thought')}")
                        print(f"Answer:\n{event.get('answer')}")
                        print("\n--- Citations ---")
                        print(json.dumps(event.get('citations'), indent=2, ensure_ascii=False))
                        break
                    elif event.get("type") == "error":
                        print(f"Chat error: {event.get('detail')}")
                        break
        else:
            print(f"Chat failed: {response.status_code}")
            print(response.text)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # Wait for server to be ready
    time.sleep(3)
    test_chat()
