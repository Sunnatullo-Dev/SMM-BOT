import asyncio
import json
import aiohttp
import os
import sys
from dotenv import load_dotenv

# Force UTF-8 output for Windows terminal
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

async def check_countries():
    load_dotenv()
    api_key = os.getenv("SMS_API_KEY", "418b50398c12de78eba436b5354e8985")
    api_url = os.getenv("SMS_API_URL", "https://locksmm.uz")
    
    params = {
        "action": "countries",
        "key": api_key,
        "service": "tg"
    }
    
    print(f"Connecting to {api_url}...")
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(api_url, params=params) as response:
                text = await response.text()
                data = json.loads(text)
                
                # Based on previous output, we found 144 countries
                # Let's extract them correctly
                countries = data.get('countries', data)
                
                if not countries or not isinstance(countries, dict):
                    print("No countries found.")
                    return
                
                print(f"Found {len(countries)} countries.\n")
                print(f"{'Davlat':<30} | {'Kod':<5} | {'Narx ($)':<10}")
                print("-" * 50)
                
                sorted_countries = sorted(
                    countries.items(), 
                    key=lambda x: str(x[1].get('name', x[0]) if isinstance(x[1], dict) else x[0])
                )
                
                for code, info in sorted_countries:
                    if isinstance(info, dict):
                        name = info.get('name', code)
                        price = info.get('price', 'N/A')
                        print(f"{name:<30} | {code:<5} | {price:<10}")
                    else:
                        print(f"{code:<30} | {'-':<5} | {info:<10}")
                        
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_countries())
