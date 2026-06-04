import asyncio
import httpx
import base64
import json
import csv
import sys

API_KEY = "ffd23dbb01065637257e7515a753b4f083c006d891bb231eeeda6588d964a2f2"
BASE_URL = "https://project.intermesh.net/api/v3/work_packages"

credentials = f"apikey:{API_KEY}"
encoded = base64.b64encode(credentials.encode("ascii")).decode("ascii")
headers = {
    "Authorization": f"Basic {encoded}",
    "Content-Type": "application/json"
}

filters = [
    {"type": {"operator": "=", "values": ["7"]}},
    {"project": {"operator": "=", "values": ["3", "85"]}},
    {"createdAt": {"operator": "<>d", "values": ["2025-04-01T05:30:00+05:30", "2026-03-31T05:30:00+05:30"]}}
]

csv_headers = [
    "id", "Project", "Subject", "Type", "Parent", "Status", "Priority", 
    "Author", "Assignee", "Updated on", "Category", "Version", "Created on", 
    "Story Points", "Remaining hours", "Description"
]

async def fetch_page(client, offset):
    params = {
        "filters": json.dumps(filters),
        "sortBy": '[["id","asc"]]',
        "pageSize": 100,
        "offset": offset
    }
    for attempt in range(3):
        try:
            r = await client.get(BASE_URL, headers=headers, params=params)
            if r.status_code != 200:
                print(f"Error {r.status_code} at offset {offset}: {r.text}", flush=True)
                return []
            break
        except Exception as e:
            if attempt == 2:
                print(f"Failed offset {offset} after 3 attempts: {e}", flush=True)
                return []
            await asyncio.sleep(2)
    data = r.json()
    items = data.get("_embedded", {}).get("elements", [])
    
    parsed = []
    for item in items:
        links = item.get("_links", {})
        project = links.get("project", {}).get("title", "") if links.get("project") else ""
        type_ = links.get("type", {}).get("title", "") if links.get("type") else ""
        status = links.get("status", {}).get("title", "") if links.get("status") else ""
        priority = links.get("priority", {}).get("title", "") if links.get("priority") else ""
        author = links.get("author", {}).get("title", "") if links.get("author") else ""
        assignee = links.get("assignee", {}).get("title", "") if links.get("assignee") else ""
        category = links.get("category", {}).get("title", "") if links.get("category") else ""
        version = links.get("version", {}).get("title", "") if links.get("version") else ""
        parent = links.get("parent", {}).get("title", "") if links.get("parent") else ""
        description = item.get("description", {}).get("raw", "") if item.get("description") else ""
        
        parsed.append({
            "id": item.get("id"),
            "Project": project,
            "Subject": item.get("subject", ""),
            "Type": type_,
            "Parent": parent,
            "Status": status,
            "Priority": priority,
            "Author": author,
            "Assignee": assignee,
            "Updated on": item.get("updatedAt", ""),
            "Category": category,
            "Version": version,
            "Created on": item.get("createdAt", ""),
            "Story Points": item.get("storyPoints", ""),
            "Remaining hours": item.get("remainingTime", ""),
            "Description": description
        })
    return parsed

async def main():
    limits = httpx.Limits(max_connections=5) # avoid overwhelming API
    async with httpx.AsyncClient(timeout=120.0, limits=limits) as client:
        # First get total count
        params = {"filters": json.dumps(filters), "pageSize": 1}
        r = await client.get(BASE_URL, headers=headers, params=params)
        data = r.json()
        total = data.get("total", 0)
        print(f"Total bugs to fetch: {total}", flush=True)
        
        pages = (total // 100) + 1
        tasks = [fetch_page(client, i) for i in range(1, pages + 1)]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_bugs = []
        for res in results:
            if isinstance(res, list):
                all_bugs.extend(res)
            else:
                print(f"Task failed with exception: {res}", flush=True)
            
        # sort by ID
        all_bugs.sort(key=lambda x: x["id"])
        
        print(f"Fetched {len(all_bugs)} bugs.", flush=True)
        with open("assets/training_data_6000.csv", "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=csv_headers)
            writer.writeheader()
            writer.writerows(all_bugs)
        print("Saved to assets/training_data_6000.csv", flush=True)
            
if __name__ == "__main__":
    asyncio.run(main())
