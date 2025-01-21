from gallery_dl import job, config
import os

def get_media(url):
    config.set((), "directory", ["{username}"])
    current_dir = os.path.dirname(os.path.abspath(__file__))
    config.set((), "base-directory", current_dir)
    config.set((), "filename", "{username}_{date}_{num}.{extension}")
    return job.DownloadJob(url).run()

if __name__ == "__main__":
    url = "https://www.instagram.com/takomayuyi/posts"
    get_media(url)