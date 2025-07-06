import json
import re
import os
import tempfile
from pathlib import Path
from gallery_dl.extractor import instagram

class InstagramFetcher:
    
    def __init__(self, username, output_dir=None, cookies=None, progress_callback=None):
        self.username = username
        if output_dir is None:
            output_dir = os.path.join(tempfile.gettempdir(), "instagrammediabatchdownloader")
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.cookies = cookies or {}
        self.base_url = f"https://www.instagram.com/{username}/"
        self.posts_count = 0
        self.progress_callback = progress_callback
        
    def _create_extractor(self, extractor_class, url_suffix=""):
        url = self.base_url + url_suffix
        pattern = re.compile(extractor_class.pattern)
        match = pattern.match(url)
        
        if not match:
            raise ValueError(f"Invalid URL for {extractor_class.__name__}: {url}")
            
        extractor = extractor_class(match)
        extractor.initialize()
        
        if self.cookies:
            extractor.cookies_update_dict(self.cookies, '.instagram.com')
        
        return extractor
    
    def get_user_metadata(self):
        try:
            extractor = self._create_extractor(instagram.InstagramInfoExtractor, "info/")
            for message_type, user_info in extractor.items():
                if user_info:
                    username = user_info.get('username', 'N/A')
                    user_id = user_info.get('id', '')
                    full_name = user_info.get('full_name', 'N/A')
                    posts_count = user_info.get('edge_owner_to_timeline_media', {}).get('count', 0)
                    followers_count = user_info.get('edge_followed_by', {}).get('count', 0)
                    following_count = user_info.get('edge_follow', {}).get('count', 0)
                    profile_pic_url = user_info.get('profile_pic_url', '')
                    if self.progress_callback:
                        self.progress_callback(f"User: {username}")
                        self.progress_callback(f"Name: {full_name}")
                        self.progress_callback(f"Posts: {posts_count:,}")
                        self.progress_callback(f"Followers: {followers_count:,}")
                        self.progress_callback(f"Following: {following_count:,}")
                        self.progress_callback("")
                    else:
                        print(f"User: {username}")
                        print(f"Name: {full_name}")
                        print(f"Posts: {posts_count:,}")
                        print(f"Followers: {followers_count:,}")
                        print(f"Following: {following_count:,}")
                        print("")
                    
                    user_summary = {
                        'username': username,
                        'user_id': user_id,
                        'full_name': full_name,
                        'posts_count': posts_count,
                        'followers_count': followers_count,
                        'following_count': following_count,
                        'profile_pic_url': profile_pic_url
                    }
                    self._save_json(user_summary, f"{self.username}_user_info.json")
                    
                    self.posts_count = posts_count
                    return user_info
                    
            return {}
        except Exception:
            return {}
        
    def _fetch_and_save(self, extractor_class, url_suffix, filename_prefix, metadata_key=None):
        try:
            media_type = filename_prefix.capitalize()
            if self.progress_callback:
                self.progress_callback(f"Fetching {filename_prefix}...")
            else:
                print(f"Fetching {filename_prefix}...")
            
            if url_suffix == "stories/":
                stories_url = f"https://www.instagram.com/stories/{self.username}/"
                pattern = re.compile(instagram.InstagramStoriesExtractor.pattern)
                match = pattern.match(stories_url)
                if not match:
                    if self.progress_callback:
                        self.progress_callback(f"No {filename_prefix} found")
                    return []
                extractor = instagram.InstagramStoriesExtractor(match)
                extractor.initialize()
                if self.cookies:
                    extractor.cookies_update_dict(self.cookies, '.instagram.com')
            elif url_suffix == "tagged/":
                try:
                    extractor = self._create_extractor(extractor_class, url_suffix)
                    user_info_file = self.output_dir / f"{self.username}_user_info.json"
                    if user_info_file.exists():
                        with open(user_info_file, 'r', encoding='utf-8') as f:
                            user_data = json.load(f)
                            user_id = user_data.get('id') or user_data.get('user_id')
                            if user_id:
                                extractor.user_id = str(user_id)
                    
                    if not hasattr(extractor, 'user_id') or not extractor.user_id:
                        if self.progress_callback:
                            self.progress_callback(f"Unable to fetch {filename_prefix} - user ID not available")
                        return []
                except Exception as e:
                    if self.progress_callback:
                        self.progress_callback(f"Error setting up {filename_prefix} extractor: {str(e)}")
                    return []
            else:
                extractor = self._create_extractor(extractor_class, url_suffix)
            
            items = []
            for item in extractor.posts():
                items.append(item)
                progress_msg = f"Fetching {filename_prefix}: {len(items)}"
                if self.progress_callback:
                    self.progress_callback(f"PROGRESS_UPDATE:{progress_msg}")
                else:
                    print(f"\r{progress_msg}", end='', flush=True)
            
            if not self.progress_callback:
                print(f"\r{'':50}")
                print(f"Done - Found {len(items)} {filename_prefix}")
            else:
                self.progress_callback("PROGRESS_CLEAR")
                self.progress_callback(f"{media_type} fetch completed - Found {len(items)} items")
            
            if items:
                if metadata_key:
                    metadata = extractor.metadata()
                    data = {"metadata": metadata, metadata_key: items}
                else:
                    data = items
                self._save_json(data, f"{self.username}_{filename_prefix}.json")
                return items
            else:
                if self.progress_callback:
                    self.progress_callback(f"No {filename_prefix} found")
                return []
        except Exception as e:
            if self.progress_callback:
                self.progress_callback(f"Error fetching {filename_prefix}: {str(e)}")
            return []
        
    def fetch_posts(self):
        try:
            extractor = self._create_extractor(instagram.InstagramPostsExtractor, "posts/")
            posts = []
            for post in extractor.posts():
                posts.append(post)
                if self.posts_count > 0:
                    progress_percent = int((len(posts) / self.posts_count) * 100)
                    progress_msg = f"Fetching posts: {len(posts)}/{self.posts_count} - {progress_percent}%"
                else:
                    progress_msg = f"Fetching posts: {len(posts)}/? - ?%"
                if self.progress_callback:
                    self.progress_callback(f"PROGRESS_UPDATE:{progress_msg}")
                else:
                    print(f"\r{progress_msg}", end='', flush=True)
            
            if not self.progress_callback:
                print(f"\r{'':50}")
                print("Done")
            else:
                self.progress_callback("PROGRESS_CLEAR")
                self.progress_callback("Posts fetch completed")
                
            if posts:
                self._save_json(posts, f"{self.username}_posts.json")
            return posts
        except Exception:
            return []
    
    def fetch_reels(self):
        return self._fetch_and_save(instagram.InstagramReelsExtractor, "reels/", "reels")
    
    def fetch_tagged_posts(self):
        return self._fetch_and_save(instagram.InstagramTaggedExtractor, "tagged/", "tagged", "tagged_posts")
    
    def fetch_stories(self):
        return self._fetch_and_save(None, "stories/", "stories")
    
    def fetch_highlights(self):
        return self._fetch_and_save(instagram.InstagramHighlightsExtractor, "highlights/", "highlights")
    
    def _handle_error(self, e, results):
        error_info = {
            "error": str(e),
            "username": self.username,
            "partial_results": results
        }
        self._save_json(error_info, f"{self.username}_error_log.json")
        raise
    
    def fetch_all_media(self):
        results = {}
        try:
            results['user_info'] = self.get_user_metadata()
            results['posts'] = self.fetch_posts()
            results['reels'] = self.fetch_reels()
            results['tagged_posts'] = self.fetch_tagged_posts()
            results['stories'] = self.fetch_stories()
            results['highlights'] = self.fetch_highlights()
            return results
        except Exception as e:
            self._handle_error(e, results)
        
    def fetch_selective_media(self, **fetch_options):
        default_options = {
            'fetch_posts': True,
            'fetch_reels': True, 
            'fetch_tagged': True,
            'fetch_stories': True,
            'fetch_highlights': True
        }
        default_options.update(fetch_options)
        
        results = {'user_info': self.get_user_metadata()}
        
        fetch_methods = {
            'posts': self.fetch_posts,
            'reels': self.fetch_reels,
            'tagged_posts': self.fetch_tagged_posts,
            'stories': self.fetch_stories,
            'highlights': self.fetch_highlights
        }
        
        method_mapping = {
            'fetch_posts': 'posts',
            'fetch_reels': 'reels', 
            'fetch_tagged': 'tagged_posts',
            'fetch_stories': 'stories',
            'fetch_highlights': 'highlights'
        }
        
        try:
            for option, should_fetch in default_options.items():
                if option in method_mapping:
                    result_key = method_mapping[option]
                    if should_fetch:
                        results[result_key] = fetch_methods[result_key]()
                    else:
                        results[result_key] = []
            return results
        except Exception as e:
            self._handle_error(e, results)
    
    def _save_json(self, data, filename):
        try:
            filepath = self.output_dir / filename
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        except Exception:
            pass

def main():
    username = "lyq01777"
    cookies = {"sessionid": ""}
    
    fetcher = InstagramFetcher(username, cookies=cookies)
    
    try:
        summary = fetcher.fetch_selective_media(
            fetch_posts=True,
            fetch_reels=False,
            fetch_tagged=False,
            fetch_stories=False,
            fetch_highlights=False
        )
        return 0
    except Exception as e:
        print(f"Program error: {e}")
        return 1

if __name__ == "__main__":
    exit(main())