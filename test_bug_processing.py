"""
Test script to verify bug processing with timeout and optimization.
"""
import asyncio
import os
from dotenv import load_dotenv
from gemini_client import GeminiClient

load_dotenv()

async def test_bug_analysis():
    """Test bug analysis with a simple text report."""
    
    # Initialize client
    client = GeminiClient(
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL"),
        model=os.getenv("LLM_MODEL"),
    )
    
    # Test bug report
    test_text = """
    Login button not working on Samsung Galaxy S23.
    When I click the login button, nothing happens.
    Device: Samsung Galaxy S23
    OS: Android 14
    Environment: Stage
    """
    
    print("Testing bug analysis...")
    print(f"Text: {test_text[:100]}...")
    print("-" * 60)
    
    try:
        import time
        start = time.time()
        
        bug_report = await client.analyze_bug_report(test_text, media_items=[])
        
        elapsed = time.time() - start
        
        print(f"✅ SUCCESS! Analysis completed in {elapsed:.1f}s")
        print(f"\nTitle: {bug_report.title}")
        print(f"Platform: {bug_report.platform}")
        print(f"Priority: {bug_report.priority}")
        print(f"Bug Type: {bug_report.bug_type}")
        print(f"Environment: {bug_report.environment}")
        print(f"\nSteps to Reproduce:")
        for i, step in enumerate(bug_report.steps_to_reproduce, 1):
            print(f"  {i}. {step}")
        
    except Exception as e:
        print(f"❌ FAILED! Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_bug_analysis())
