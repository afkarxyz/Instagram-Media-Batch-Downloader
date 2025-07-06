import asyncio
import aiohttp
import aiofiles
import json
import time
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime

class InstagramMediaDownloader:
    def __init__(self, output_dir=None, max_concurrent=25, progress_callback=None):
        if output_dir is None:
            raise ValueError("output_dir must be specified")
        
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.progress_callback = progress_callback
        
        self.stats = {
            'total': 0,
            'downloaded': 0,
            'skipped': 0,
            'failed': 0,
            'start_time': None
        }
        
        self.category_progress = {}
        self.session = None
    
    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(total=300, connect=30)
        connector = aiohttp.TCPConnector(limit=100, limit_per_host=30)
        
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    def _format_timestamp(self, timestamp):
        try:
            dt = datetime.fromtimestamp(timestamp)
            return dt.strftime("%Y%m%d_%H%M%S")
        except:
            return "unknown_time"

    def _get_extension(self, url):
        try:
            parsed = urlparse(url)
            path = parsed.path.lower()
            if '.' in path:
                ext = path.split('.')[-1].split('?')[0]
                if ext in ['jpg', 'jpeg', 'png', 'webp', 'mp4', 'mov']:
                    return ext
            return 'jpg'
        except:
            return 'jpg'

    def _extract_media_from_item(self, item, username, prefix="", idx=None):
        urls = []
        code = item.get('code', 'unknown')
        taken_at = item.get('taken_at', 0)
        timestamp_str = self._format_timestamp(taken_at)
        
        name_prefix = f"{username}_{timestamp_str}_{code}"
        if prefix:
            name_prefix += f"_{prefix}"
        if idx is not None:
            name_prefix += f"_{idx}"
        
        if 'image_versions2' in item:
            candidates = item['image_versions2'].get('candidates', [])
            if candidates:
                img = candidates[0]
                if 'url' in img:
                    ext = self._get_extension(img['url'])
                    filename = f"{name_prefix}.{ext}"
                    urls.append((img['url'], filename))
        
        if 'video_versions' in item:
            videos = item['video_versions']
            if videos:
                video = videos[0]
                if 'url' in video:
                    filename = f"{name_prefix}_video.mp4"
                    urls.append((video['url'], filename))
        
        return urls

    def _load_json_file(self, json_file):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading {json_file}: {e}")
            return None

    def _process_carousel_or_single(self, item, username, prefix=""):
        urls = []
        carousel_media = item.get('carousel_media', [])
        
        if not carousel_media:
            urls.extend(self._extract_media_from_item(item, username, prefix))
        else:
            for idx, media in enumerate(carousel_media, 1):
                carousel_prefix = f"{prefix}_carousel" if prefix else "carousel"
                urls.extend(self._extract_media_from_item(media, username, carousel_prefix, idx))
        
        return urls

    def extract_urls_from_posts(self, json_file, username, limit=None):
        data = self._load_json_file(json_file)
        if not data:
            return []
        
        if limit:
            data = data[:limit]
        
        urls = []
        for post in data:
            urls.extend(self._process_carousel_or_single(post, username))
        
        return urls

    def extract_urls_from_reels(self, json_file, username):
        data = self._load_json_file(json_file)
        if not data:
            return []
        
        urls = []
        for reel in data:
            urls.extend(self._extract_media_from_item(reel, username))
        
        return urls

    def extract_urls_from_tagged(self, json_file, username):
        data = self._load_json_file(json_file)
        if not data:
            return []
        
        posts = data.get('tagged_posts', data) if isinstance(data, dict) else data
        
        urls = []
        for post in posts:
            urls.extend(self._process_carousel_or_single(post, username, "tagged"))
        
        return urls

    def extract_urls_from_stories(self, json_file, username):
        data = self._load_json_file(json_file)
        if not data:
            return []
        
        urls = []
        for story_reel in data:
            items = story_reel.get('items', [])
            for item in items:
                urls.extend(self._extract_media_from_item(item, username, "story"))
        
        return urls

    def extract_urls_from_highlights(self, json_file, username):
        data = self._load_json_file(json_file)
        if not data:
            return []
        
        urls = []
        for highlight_reel in data:
            items = highlight_reel.get('items', [])
            highlight_id = highlight_reel.get('id', 'unknown').replace('highlight:', '')
            
            for item in items:
                urls.extend(self._extract_media_from_item(item, username, f"highlight_{highlight_id}"))
        
        return urls

    def _detect_username_from_files(self, data_path):
        try:
            patterns = ["*_posts.json", "*_user_info.json", "*_reels.json", "*_highlights.json", "*_stories.json"]
            suffixes = ['_posts', '_user_info', '_reels', '_highlights', '_stories']
            
            for pattern in patterns:
                json_files = list(data_path.glob(pattern))
                if json_files:
                    filename = json_files[0].stem
                    for suffix in suffixes:
                        if suffix in filename:
                            return filename.replace(suffix, '')
            return None
        except Exception as e:
            print(f"Error detecting username: {e}")
            return None

    async def download_file(self, url, filename, category_dir):
        async with self.semaphore:
            file_path = category_dir / filename
            
            if file_path.exists():
                self.stats['skipped'] += 1
                return True
            
            try:
                async with self.session.get(url) as response:
                    if response.status == 200:
                        file_path.parent.mkdir(parents=True, exist_ok=True)
                        
                        async with aiofiles.open(file_path, 'wb') as f:
                            async for chunk in response.content.iter_chunked(8192):
                                await f.write(chunk)
                        
                        self.stats['downloaded'] += 1
                        return True
                    else:
                        self.stats['failed'] += 1
                        return False
            
            except Exception:
                self.stats['failed'] += 1
                if file_path.exists():
                    try:
                        file_path.unlink()
                    except:
                        pass
                return False

    async def download_category(self, urls, category_name, username):
        if not urls:
            return
        
        category_dir = self.output_dir / f"{category_name}_{username}"
        category_dir.mkdir(exist_ok=True)
        
        self.stats['total'] += len(urls)
        self.category_progress[category_name] = {'completed': 0, 'total': len(urls)}
        
        tasks = [
            self.download_file(url, filename, category_dir)
            for url, filename in urls
        ]
        
        start_time = time.time()
        completed = 0
        
        for task in asyncio.as_completed(tasks):
            await task
            completed += 1
            self.category_progress[category_name]['completed'] = completed
            
            if completed % 5 == 0 or completed == len(tasks):
                if self.progress_callback:
                    total_completed = sum(cat['completed'] for cat in self.category_progress.values())
                    total_files = sum(cat['total'] for cat in self.category_progress.values())
                    progress_percentage = int((total_completed / max(total_files, 1)) * 100)
                    
                    if completed == len(tasks):
                        final_msg = f"{category_name}: {completed}/{len(tasks)} files (completed)"
                        self.progress_callback(final_msg, progress_percentage)
                    else:
                        progress_msg = f"{category_name}: {completed}/{len(tasks)} files"
                        self.progress_callback(progress_msg, progress_percentage)

    def _get_categories_config(self, username, limit_posts=None):
        return {
            'posts': {
                'filename': f"{username}_posts.json",
                'extractor': lambda f: self.extract_urls_from_posts(f, username, limit_posts)
            },
            'reels': {
                'filename': f"{username}_reels.json", 
                'extractor': lambda f: self.extract_urls_from_reels(f, username)
            },
            'tagged': {
                'filename': f"{username}_tagged.json",
                'extractor': lambda f: self.extract_urls_from_tagged(f, username)
            },
            'stories': {
                'filename': f"{username}_stories.json",
                'extractor': lambda f: self.extract_urls_from_stories(f, username)
            },
            'highlights': {
                'filename': f"{username}_highlights.json",
                'extractor': lambda f: self.extract_urls_from_highlights(f, username)            }
        }

    async def download_all_media(self, data_dir=None, username=None, limit_posts=None):
        if data_dir is None:
            data_dir = os.path.join(tempfile.gettempdir(), "instagrammediabatchdownloader")
            
        self.stats['start_time'] = time.time()
        
        data_path = Path(data_dir)
        
        if username is None:
            username = self._detect_username_from_files(data_path)
            if username is None:
                error_msg = "Error: Could not detect username from files."
                if self.progress_callback:
                    self.progress_callback(error_msg, 0)
                else:
                    print(error_msg)                
                return
        
        categories = self._get_categories_config(username, limit_posts)
        download_tasks = []
        
        for category_name, config in categories.items():
            file_path = data_path / config['filename']
            
            if file_path.exists():
                urls = config['extractor'](file_path)
                if urls:
                    task = self.download_category(urls, category_name, username)
                    download_tasks.append(task)
        
        if not download_tasks:
            no_tasks_msg = "No download tasks created!"
            if self.progress_callback:
                self.progress_callback(no_tasks_msg, 0)
            else:
                print(no_tasks_msg)
            return
            
        await asyncio.gather(*download_tasks)
        
        self._print_final_stats()

    def _print_final_stats(self):
        total_time = time.time() - self.stats['start_time']
        
        stats_lines = [
            f"Total time: {total_time:.1f} seconds",
            f"Total files: {self.stats['total']}",
            f"Downloaded: {self.stats['downloaded']}",
            f"Skipped: {self.stats['skipped']}",
            f"Failed: {self.stats['failed']}"
        ]
        
        if self.progress_callback:
            for line in stats_lines:
                self.progress_callback(line, 0)
        else:
            print(f"\nTotal time: {total_time:.1f} seconds")
            print(f"Total files: {self.stats['total']}")
            print(f"Downloaded: {self.stats['downloaded']}")
            print(f"Skipped: {self.stats['skipped']}")
            print(f"Failed: {self.stats['failed']}")


async def main():
    data_directory = os.path.join(tempfile.gettempdir(), "instagrammediabatchdownloader")
    max_concurrent = 25
    limit_posts = None
    username = "lyq01777"
    
    user_pictures = os.path.join(os.path.expanduser("~"), "Pictures")
    output_directory = os.path.join(user_pictures, username)
    
    async with InstagramMediaDownloader(
        output_dir=output_directory,
        max_concurrent=max_concurrent
    ) as downloader:
        
        await downloader.download_all_media(
            data_dir=data_directory,
            username=username,
            limit_posts=limit_posts
        )
    
    print(f"\nDownload process completed!")
    print(f"Check your files in: {output_directory}")

if __name__ == "__main__":
    asyncio.run(main())