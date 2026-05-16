import httpx
import json
import time
import sys

BASE_URL = "http://localhost:8080"

def send_message(text: str):
    payload = {
        "type": "MESSAGE",
        "message": {
            "name": f"spaces/local/messages/{int(time.time())}",
            "text": text,
            "sender": {
                "name": "users/local-tester",
                "displayName": "Local QA Tester"
            }
        }
    }
    print(f"\nSending to bot: {text}")
    try:
        response = httpx.post(f"{BASE_URL}/webhook", json=payload, timeout=10.0)
        print("Bot replied:")
        print(json.dumps(response.json(), indent=2))
        return response.json()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    print("🤖 QA Bug Logger Local Tester")
    print("--------------------------------")
    
    # 1. Register
    api_key = input("Enter your OpenProject API Key to register: ").strip()
    if not api_key:
        print("API key required.")
        sys.exit(1)
        
    send_message(f"/register {api_key}")
    time.sleep(1)
    
    # 2. Test Bug Report
    print("\nNow testing a bug report...")
    test_bug = "The login CTA is completely trimmed on the post-login screen and cannot be clicked. Device: iPhone 15, OS: iOS 17.1"
    send_message(test_bug)
    
    print("\nThe bot is processing the bug in the background! Check the bot terminal logs (uvicorn) to see it create the ticket in OpenProject.")
