import requests  
import os  
from typing import List, Dict, Any  
  
def get_all_entities_with_details(base_url: str, bank_id: str, api_key: str = None, limit: int = 100) -> List[Dict[str, Any]]:  
    """  
    Retrieve all entities with full details including observations.  
    """  
    headers = {}  
    if api_key:  
        headers["authorization"] = api_key  
      
    # First, get all entities with metadata  
    all_entities = get_all_entities(base_url, bank_id, api_key, limit)  
      
    # Then fetch detailed information for each entity  
    detailed_entities = []  
    for entity in all_entities:  
        entity_id = entity.get('id')  
        if not entity_id:  
            continue  
              
        # Get entity details with observations  
        detail_url = f"{base_url}/v1/default/banks/{bank_id}/entities/{entity_id}"  
        try:  
            response = requests.get(detail_url, headers=headers)  
            response.raise_for_status()  
            entity_detail = response.json()  
            detailed_entities.append(entity_detail)  
        except requests.exceptions.RequestException as e:  
            print(f"Error fetching details for entity {entity_id}: {e}")  
            # Fall back to basic entity info  
            detailed_entities.append(entity)  
      
    return detailed_entities  
  
def get_all_entities(base_url: str, bank_id: str, api_key: str = None, limit: int = 100) -> List[Dict[str, Any]]:  
    """Your existing function to get entities list"""  
    all_entities = []  
    offset = 0  
      
    headers = {}  
    if api_key:  
        headers["authorization"] = api_key  
      
    while True:  
        url = f"{base_url}/v1/default/banks/{bank_id}/entities"  
        params = {"limit": limit, "offset": offset}  
          
        try:  
            response = requests.get(url, params=params, headers=headers)  
            response.raise_for_status()  
              
            data = response.json()  
            entities = data.get("items", [])  
            total = data.get("total", 0)  
              
            all_entities.extend(entities)  
              
            if len(all_entities) >= total or len(entities) == 0:  
                break  
                  
            offset += limit  
              
        except requests.exceptions.RequestException as e:  
            print(f"Error fetching entities: {e}")  
            break  
      
    return all_entities  
  
# Example usage  
if __name__ == "__main__":  
    BASE_URL = os.getenv("ATULYA_API_URL", "http://localhost:8888")  
    BANK_ID = os.getenv("ATULYA_BANK_ID", "hermes")  
    API_KEY = os.getenv("ATULYA_API_KEY")  
      
    # Get entities with full details  
    entities = get_all_entities_with_details(BASE_URL, BANK_ID, API_KEY)  
      
    print(f"Retrieved {len(entities)} entities with full details")  
      
    # Print first few entities with all data  
    for i, entity in enumerate(entities[:3]):  
        print(f"\nEntity {i+1}:")  
        print(f"  ID: {entity.get('id')}")  
        print(f"  Name: {entity.get('canonical_name')}")  
        print(f"  Mentions: {entity.get('mention_count')}")  
        print(f"  First Seen: {entity.get('first_seen')}")  
        print(f"  Last Seen: {entity.get('last_seen')}")  
        print(f"  Metadata: {entity.get('metadata')}")  
          
        # Print observations if available  
        observations = entity.get('observations', [])  
        if observations:  
            print(f"  Observations ({len(observations)}):")  
            for j, obs in enumerate(observations[:3]):  # Show first 3 observations  
                print(f"    {j+1}. {obs.get('text', 'No text')}")  
                if obs.get('mentioned_at'):  
                    print(f"       Mentioned at: {obs['mentioned_at']}")
