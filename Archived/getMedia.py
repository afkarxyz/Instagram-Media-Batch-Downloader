import os
import sys
from gallery_dl import job, config, extractor

gallery_dl_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, gallery_dl_path)

def get_media(url):
    config.set((), "directory", ["{username}"])
    current_dir = os.path.dirname(os.path.abspath(__file__))
    config.set((), "base-directory", current_dir)
    config.set((), "filename", "{username}_{date}_{num}.{extension}")
    
    config.set(("extractor", "instagram"), "cookies", {
        "sessionid": ""
    })
    
    extr = extractor.find(url)
    if extr is None:
        raise ValueError(f"No extractor found for URL: {url}")
    
    return job.DownloadJob(extr).run()

if __name__ == "__main__":
    url = "https://www.instagram.com/takomayuyi/posts"
    get_media(url)
