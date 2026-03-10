import os
import sys
import mimetypes
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from notion_client import Client
from slugify import slugify

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")
NOTION_PROJECTS_DATABASE_ID = os.environ.get("NOTION_PROJECTS_DATABASE_ID")

POSTS_DIR = Path("content/posts")
PROJECTS_DIR = Path("content/projects")
IMAGE_DOWNLOAD_TIMEOUT = 30


def validate_config():
    if not NOTION_TOKEN:
        print("ERROR: NOTION_TOKEN is not set.")
        sys.exit(1)
    if not NOTION_DATABASE_ID:
        print("ERROR: NOTION_DATABASE_ID is not set.")
        sys.exit(1)


def get_plain_text(rich_text_array: list) -> str:
    if not rich_text_array:
        return ""
    return "".join(block.get("plain_text", "") for block in rich_text_array)


def fetch_published(notion: Client, database_id: str, sort_by: str = "Date") -> list:
    results = []
    has_more = True
    start_cursor = None
    while has_more:
        response = notion.databases.query(
            database_id=database_id,
            filter={"property": "Published", "checkbox": {"equals": True}},
            sorts=[{"property": sort_by, "direction": "descending"}],
            **({"start_cursor": start_cursor} if start_cursor else {}),
        )
        results.extend(response.get("results", []))
        has_more = response.get("has_more", False)
        start_cursor = response.get("next_cursor")
    return results


def guess_image_extension(url: str, content_type: str = "") -> str:
    if content_type:
        ext = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if ext:
            return ".jpg" if ext in (".jpe", ".jpeg") else ext
    parsed = urlparse(url)
    path_ext = Path(parsed.path).suffix.lower()
    if path_ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".avif"):
        return path_ext
    return ".jpg"


def download_image(url: str, dest_dir: Path, index: int) -> str | None:
    try:
        response = requests.get(url, timeout=IMAGE_DOWNLOAD_TIMEOUT)
        response.raise_for_status()
        ext = guess_image_extension(url, response.headers.get("Content-Type", ""))
        filename = f"image-{index}{ext}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        with open(dest_dir / filename, "wb") as f:
            f.write(response.content)
        return filename
    except Exception as e:
        print(f"    Failed to download image: {e}")
        return None


def convert_blocks_to_markdown(blocks: list, post_dir: Path) -> str:
    lines = []
    numbered_list_counter = 0
    image_counter = 0

    for block in blocks:
        block_type = block.get("type")
        data = block.get(block_type, {})
        text = get_plain_text(data.get("rich_text", []))

        if block_type != "numbered_list_item":
            numbered_list_counter = 0

        if block_type == "paragraph":
            lines.append(text if text else "")
        elif block_type == "heading_1":
            lines.append(f"# {text}")
        elif block_type == "heading_2":
            lines.append(f"## {text}")
        elif block_type == "heading_3":
            lines.append(f"### {text}")
        elif block_type == "bulleted_list_item":
            lines.append(f"- {text}")
        elif block_type == "numbered_list_item":
            numbered_list_counter += 1
            lines.append(f"{numbered_list_counter}. {text}")
        elif block_type == "code":
            lines.append(f"```{data.get('language', '')}\n{text}\n```")
        elif block_type == "quote":
            lines.append(f"> {text}")
        elif block_type == "callout":
            emoji = data.get("icon", {}).get("emoji", "ℹ️")
            lines.append(f"> {emoji} {text}")
        elif block_type == "divider":
            lines.append("---")
        elif block_type == "image":
            image_type = data.get("type")
            raw_url = data.get("file", {}).get("url", "") if image_type == "file" else data.get("external", {}).get("url", "")
            alt_text = get_plain_text(data.get("caption", [])) or f"Image {image_counter}"
            if raw_url:
                if image_type == "file":
                    local_filename = download_image(raw_url, post_dir, image_counter)
                    lines.append(f"![{alt_text}]({local_filename})" if local_filename else f"![{alt_text}]({raw_url})")
                else:
                    lines.append(f"![{alt_text}]({raw_url})")
                image_counter += 1

        lines.append("")

    return "\n".join(lines).strip()


def fetch_page_content(notion: Client, page_id: str, post_dir: Path) -> str:
    blocks = []
    has_more = True
    start_cursor = None
    while has_more:
        response = notion.blocks.children.list(
            block_id=page_id,
            **({"start_cursor": start_cursor} if start_cursor else {}),
        )
        blocks.extend(response.get("results", []))
        has_more = response.get("has_more", False)
        start_cursor = response.get("next_cursor")
    return convert_blocks_to_markdown(blocks, post_dir)


def extract_post_metadata(page: dict) -> dict:
    props = page.get("properties", {})
    title = get_plain_text(props.get("Title", {}).get("title", [])) or "Untitled"
    slug_raw = get_plain_text(props.get("Slug", {}).get("rich_text", []))
    slug = slug_raw.strip() if slug_raw.strip() else slugify(title)
    date_obj = props.get("Date", {}).get("date") or {}
    date_str = date_obj.get("start", "") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    description = get_plain_text(props.get("Description", {}).get("rich_text", []))
    tags = [t["name"] for t in props.get("Tags", {}).get("multi_select", [])]
    return {"title": title, "slug": slug, "date": date_str, "description": description, "tags": tags}


def extract_project_metadata(page: dict) -> dict:
    props = page.get("properties", {})
    title = get_plain_text(props.get("Name", {}).get("title", [])) or "Untitled Project"
    slug_raw = get_plain_text(props.get("Slug", {}).get("rich_text", []))
    slug = slug_raw.strip() if slug_raw.strip() else slugify(title)
    description = get_plain_text(props.get("Description", {}).get("rich_text", []))
    tags = [t["name"] for t in props.get("Tags", {}).get("multi_select", [])]
    project_url = props.get("URL", {}).get("url") or ""
    github_url = props.get("GitHub", {}).get("url") or ""
    return {
        "title": title,
        "slug": slug,
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "description": description,
        "tags": tags,
        "projectURL": project_url,
        "githubURL": github_url,
    }


def build_front_matter(meta: dict, extra: dict = None) -> str:
    tags_toml = "[" + ", ".join(f'"{t}"' for t in meta["tags"]) + "]"
    lines = [
        "+++",
        f'title       = "{meta["title"]}"',
        f'date        = "{meta["date"]}"',
        f'slug        = "{meta["slug"]}"',
        f'description = "{meta["description"]}"',
        f"tags        = {tags_toml}",
    ]
    if extra:
        for k, v in extra.items():
            lines.append(f'{k} = "{v}"')
    lines.append("draft       = false")
    lines.append("+++")
    return "\n".join(lines)


def write_page(meta: dict, content: str, output_dir: Path, extra_fm: dict = None) -> Path:
    post_dir = output_dir / meta["slug"]
    post_dir.mkdir(parents=True, exist_ok=True)
    filename = post_dir / "index.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(build_front_matter(meta, extra_fm))
        f.write("\n\n")
        f.write(content)
    print(f"  ✓ {filename}")
    return filename


def main():
    validate_config()
    notion = Client(auth=NOTION_TOKEN)

    print("\n📝 Syncing Posts...")
    posts = fetch_published(notion, NOTION_DATABASE_ID)
    print(f"Found {len(posts)} post(s).")
    for page in posts:
        meta = extract_post_metadata(page)
        post_dir = POSTS_DIR / meta["slug"]
        content = fetch_page_content(notion, page["id"], post_dir)
        write_page(meta, content, POSTS_DIR)

    if NOTION_PROJECTS_DATABASE_ID:
        print("\n🚀 Syncing Projects...")
        try:
            projects = fetch_published(notion, NOTION_PROJECTS_DATABASE_ID, sort_by="Name")
        except Exception:
            projects = notion.databases.query(
                database_id=NOTION_PROJECTS_DATABASE_ID,
                filter={"property": "Published", "checkbox": {"equals": True}},
            ).get("results", [])
        print(f"Found {len(projects)} project(s).")
        for page in projects:
            meta = extract_project_metadata(page)
            project_dir = PROJECTS_DIR / meta["slug"]
            content = fetch_page_content(notion, page["id"], project_dir)
            links = []
            if meta["projectURL"]:
                links.append(f"🔗 [Live Project]({meta['projectURL']})")
            if meta["githubURL"]:
                links.append(f"🐙 [GitHub]({meta['githubURL']})")
            if links:
                content = " · ".join(links) + "\n\n" + content
            write_page(meta, content, PROJECTS_DIR, {"projectURL": meta["projectURL"], "githubURL": meta["githubURL"]})
    else:
        print("\nℹ️  NOTION_PROJECTS_DATABASE_ID not set — skipping projects.")

    print("\n✅ Sync complete.")


if __name__ == "__main__":
    main()
