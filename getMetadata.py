import requests
import json
from random import choices
from string import ascii_letters, digits

def generate_tokens():
    x_csrftoken = "".join(choices(ascii_letters + digits, k=22))
    x_asbd_id = "".join(choices(digits, k=6))
    return [x_csrftoken, x_asbd_id]

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

    try:
        response = requests.get(
            f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}",
            headers=headers,
            timeout=10
        )

        if response.status_code == 200:
            try:
                profile_data = response.json()["data"]["user"]
                if profile_data is None:
                    return {"error": "User data not found"}
                
                filtered_data = filter_profile_data(profile_data)
                return filtered_data
            except Exception as e:
                return {"error": f"Failed to parse profile data: {str(e)}"}
        elif response.status_code == 404:
            return {"error": "User not found"}
        else:
            return {"error": f"Request failed with status code: {response.status_code}"}
    except Exception as e:
        return {"error": f"Request failed: {str(e)}"}

if __name__ == "__main__":
    username = "takomayuyi"
    result = get_profile_data(username)
    print(json.dumps(result, indent=4))
