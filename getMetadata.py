import requests
import json
import os
from random import choices, shuffle
from string import ascii_letters, digits

def generate_tokens():
    x_csrftoken = "".join(choices(ascii_letters + digits, k=22))
    x_asbd_id = "".join(choices(digits, k=6))
    return [x_csrftoken, x_asbd_id]

def get_proxy_list():
    base_url = "https://raw.githubusercontent.com/afkarxyz/proxies/main/"
    proxy_types = ["http", "https", "socks4", "socks5"]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    
    all_proxies = []
    
    for proxy_type in proxy_types:
        try:
            response = requests.get(f"{base_url}{proxy_type}", headers=headers)
            if response.status_code == 200:
                proxies = response.text.splitlines()
                formatted_proxies = [(proxy, proxy_type) for proxy in proxies]
                all_proxies.extend(formatted_proxies)
        except:
            continue
    
    if all_proxies:
        shuffle(all_proxies)
        return all_proxies
    return None

def filter_profile_data(profile_data):
    try:
        filtered_data = {
            "name": profile_data.get("username", ""),
            "nick": profile_data.get("full_name", ""),
            "followers_count": profile_data.get("edge_followed_by", {}).get("count", 0),
            "friends_count": profile_data.get("edge_follow", {}).get("count", 0),
            "profile_image": profile_data.get("profile_pic_url_hd", ""),
            "statuses_count": profile_data.get("edge_owner_to_timeline_media", {}).get("count", 0),
            "is_private": profile_data.get("is_private", False)
        }
        return filtered_data
    except Exception as e:
        return {"error": f"Failed to filter profile data: {str(e)}"}

def get_profile_data(username):
    proxies = get_proxy_list()
    if not proxies:
        return {"error": "Failed to get proxy list"}
    
    TOKENS = generate_tokens()
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "sec-ch-prefers-color-scheme": "dark",
        "sec-fetch-dest": "empty", 
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-csrftoken": TOKENS[0],
        "x-asbd-id": TOKENS[1],
        "x-ig-app-id": "936619743392459",
        "x-ig-www-claim": "0",
        "x-requested-with": "XMLHttpRequest",
        "Referer": f"https://www.instagram.com/{username}/",
        "Referrer-Policy": "strict-origin-when-cross-origin"
    }

    for proxy, proxy_type in proxies:
        try:
            response = requests.get(
                f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}",
                headers=headers,
                proxies={proxy_type: proxy},
                timeout=10
            )

            if response.status_code == 200:
                try:
                    profile_data = response.json()["data"]["user"]
                    if profile_data is None:
                        continue
                    
                    filtered_data = filter_profile_data(profile_data)
                    return filtered_data
                except:
                    continue
            elif response.status_code == 404:
                return {"error": "User not found"}
        except:
            continue
            
    return {"error": "Failed to fetch profile data with available proxies"}

if __name__ == "__main__":
    username = "takomayuyi"
    result = get_profile_data(username)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(current_dir, f"{username}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=4)
