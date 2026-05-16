"""
Quick test script to verify LLM API key and connection.
"""
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL")
LLM_MODEL = os.getenv("LLM_MODEL")

print(f"Testing LLM connection...")
print(f"API Key: {LLM_API_KEY[:20]}..." if LLM_API_KEY else "API Key: NOT SET")
print(f"Base URL: {LLM_BASE_URL}")
print(f"Model: {LLM_MODEL}")
print("-" * 60)

try:
    client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    
    print("Sending test request...")
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": "Reply with: OK"}],
        max_tokens=10,
        timeout=10.0,
    )
    
    result = response.choices[0].message.content
    print(f"✅ SUCCESS! Response: {result}")
    print(f"Model used: {response.model}")
    print(f"Tokens: {response.usage.total_tokens if response.usage else 'N/A'}")
    
except Exception as e:
    print(f"❌ FAILED! Error: {e}")
    print(f"Error type: {type(e).__name__}")
