import base64
import io
import json
import sys
from pathlib import Path

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from epcot_fw.config import settings  # noqa: E402

SNAPSHOT_PATH = Path(__file__).parent / "epcot_db_snapshot.json"

with open(SNAPSHOT_PATH) as f:
    data = json.load(f)

booth_urls = {b["image_url"] for b in data["booths"] if b.get("image_url")}
item_urls = {
    it["image_url"]
    for b in data["booths"]
    for it in b.get("items", [])
    if it.get("image_url")
}
urls = sorted(booth_urls | item_urls)
print(f"fetching {len(urls)} images ({len(booth_urls)} booth, {len(item_urls)} dish)...")

cache: dict[str, str] = {}
total_bytes = 0

with httpx.Client(headers={"User-Agent": settings.user_agent}, timeout=20, follow_redirects=True) as client:
    for i, url in enumerate(urls, 1):
        try:
            resp = client.get(url)
            resp.raise_for_status()
            img = Image.open(io.BytesIO(resp.content)).convert("RGB")
            img.thumbnail((480, 480))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=72, optimize=True)
            encoded = base64.b64encode(buf.getvalue()).decode("ascii")
            cache[url] = f"data:image/jpeg;base64,{encoded}"
            total_bytes += len(buf.getvalue())
            print(f"  [{i}/{len(urls)}] {len(buf.getvalue())/1024:.0f}KB  {url.split('/')[-1]}")
        except Exception as e:
            print(f"  [{i}/{len(urls)}] FAILED: {url} -> {e}")

print(f"total encoded size: {total_bytes/1024:.0f}KB")

for booth in data["booths"]:
    booth["image_data_uri"] = cache.get(booth.get("image_url"))
    for item in booth.get("items", []):
        item["image_data_uri"] = cache.get(item.get("image_url"))

with open(SNAPSHOT_PATH, "w") as f:
    json.dump(data, f)

print("done")
