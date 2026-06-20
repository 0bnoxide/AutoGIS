import os
import shutil
import time


def download_one(layer, objectid, attachment_id, dest_path, retries,
                 backoff_seconds, sleep=time.sleep):
    dest_dir = os.path.dirname(dest_path)
    os.makedirs(dest_dir, exist_ok=True)

    attempt = 0
    while True:
        try:
            saved = layer.attachments.download(
                oid=objectid, attachment_id=attachment_id, save_path=dest_dir)
            if isinstance(saved, (list, tuple)):
                saved = saved[0]
            if os.path.abspath(saved) != os.path.abspath(dest_path):
                shutil.move(saved, dest_path)
            return
        except Exception:
            if attempt >= retries:
                raise
            attempt += 1
            sleep(backoff_seconds * attempt)
