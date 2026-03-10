"""
sync_notion.py
==============
Pulls published posts from a Notion database and writes them as
Hugo-compatible Markdown files inside content/posts/.

v2 — adds image support:
  • Detects Notion "image" blocks (both uploaded files and external URLs)
  • Downloads uploaded images locally (Notion's file URLs expire after ~1 hour)
  • Saves each post as a Hugo Page Bundle so images live next to the post:
      content/posts/<slug>/index.md
      content/posts/<slug>/image-0.jpg
      content/posts/<slug>/image-1.png
  • References images with relative paths so they work everywhere

Requirements:
    pip install notion-client python-slugify requests

Environment variables (set these as GitHub Secrets):
    NOTION_TOKEN       — your Notion integration secret key
    NOTION_DATABASE_ID — the ID of your "Posts" Notion database
"""

import os
import sys
import re
import mimetypes
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests  # for downloading images
from notion_client import Client
from slugify import slugify

# ---------------------------------------------------------------------------
# Configuration — read from environment variables
# ---------------------------------------------------------------------------

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")

# Root directory for all posts (Hugo Page Bundle style)
# Each post lives at: content/posts/<slug>/index.md
OUTPUT_DIR = Path("content/posts")

# Timeout (seconds) for image downloads — don't hang forever
IMAGE_DOWNLOAD_TIMEOUT = 30


def validate_config():
    """Make sure the required environment variables are set before we start."""
    if not NOTION_TOKEN:
        print("ERROR: NOTION_TOKEN environment variable is not set.")
        sys.exit(1)
    if not NOTION_DATABASE_ID:
        print("ERROR: NOTION_DATABASE_ID environment variable is not set.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Notion helpers
# ---------------------------------------------------------------------------

def get_plain_text(rich_text_array: list) -> str:
    """
    Notion returns text fields as arrays of 'rich text' objects.
    This helper extracts just the plain string from them.
    """
    if not rich_text_array:
        return ""
    return "".join(block.get("plain_text", "") for block in rich_text_array)


def fetch_published_posts(notion: Client) -> list:
    """
    Query the Notion database and return only pages where
    the 'Published' checkbox is True.
    """
    print(f"Fetching published posts from database: {NOTION_DATABASE_ID}")

    results = []
    has_more = True
    start_cursor = None

    while has_more:
        response = notion.databases.query(
            database_id=NOTION_DATABASE_ID,
            filter={
                "property": "Published",
                "checkbox": {"equals": True},
            },
            sorts=[{"property": "Date", "direction": "descending"}],
            **({"start_cursor": start_cursor} if start_cursor else {}),
        )
        results.extend(response.get("results", []))
        has_more = response.get("has_more", False)
        start_cursor = response.get("next_cursor")

    print(f"Found {len(results)} published post(s).")
    return results


# ---------------------------------------------------------------------------
# Image handling
# ---------------------------------------------------------------------------

def guess_image_extension(url: str, content_type: str = "") -> str:
    """
    Work out the file extension for a downloaded image.

    We try three methods in order:
      1. Look at the Content-Type header from the HTTP response
      2. Parse the extension from the URL itself
      3. Fall back to .jpg
    """
    # Method 1: Content-Type header (most reliable)
    if content_type:
        # e.g. "image/png" → ".png"
        ext = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if ext:
            # mimetypes can return ".jpe" for JPEG — normalise it
            return ".jpg" if ext in (".jpe", ".jpeg") else ext

    # Method 2: URL path extension
    parsed = urlparse(url)
    path_ext = Path(parsed.path).suffix.lower()
    if path_ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".avif"):
        return path_ext

    # Method 3: Default
    return ".jpg"


def download_image(url: str, dest_dir: Path, index: int) -> str | None:
    """
    Download an image from `url` into `dest_dir`.

    Returns the local filename (e.g. "image-0.png") on success,
    or None if the download fails (so we can fall back to the URL).

    Parameters:
        url      — the image URL (may be an expiring Notion S3 link)
        dest_dir — the post's Page Bundle directory
        index    — counter used to generate unique filenames
    """
    try:
        response = requests.get(url, timeout=IMAGE_DOWNLOAD_TIMEOUT)
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "")
        ext = guess_image_extension(url, content_type)

        # e.g. image-0.png, image-1.jpg, …
        filename = f"image-{index}{ext}"
        dest_path = dest_dir / filename

        dest_dir.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(response.content)

        print(f"    📷 Downloaded image → {dest_path}")
        return filename

    except Exception as e:
        print(f"    ⚠️  Could not download image (will use URL instead): {e}")
        return None


# ---------------------------------------------------------------------------
# Block → Markdown conversion
# ---------------------------------------------------------------------------

def convert_blocks_to_markdown(blocks: list, post_dir: Path) -> str:
    """
    Convert Notion blocks to Markdown text.

    `post_dir` is the Page Bundle directory for this post.
    Images are downloaded there; other files reference it.

    Supported block types:
        paragraph, heading_1/2/3, bulleted_list_item,
        numbered_list_item, code, quote, callout, divider,
        image  ← NEW in v2
    """
    lines = []
    numbered_list_counter = 0
    image_counter = 0  # unique index per post for image filenames

    for block in blocks:
        block_type = block.get("type")
        data = block.get(block_type, {})

        text = get_plain_text(data.get("rich_text", []))

        if block_type != "numbered_list_item":
            numbered_list_counter = 0

        # ----- Text blocks -----

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
            language = data.get("language", "")
            lines.append(f"```{language}\n{text}\n```")

        elif block_type == "quote":
            lines.append(f"> {text}")

        elif block_type == "callout":
            emoji = data.get("icon", {}).get("emoji", "ℹ️")
            lines.append(f"> {emoji} {text}")

        elif block_type == "divider":
            lines.append("---")

        # ----- Image block (NEW in v2) -----

        elif block_type == "image":
            # Notion images have two possible sources:
            #   "file"     → uploaded by the user (URL expires in ~1 hour!)
            #   "external" → embedded from an external URL (permanent)
            image_type = data.get("type")  # "file" or "external"

            if image_type == "file":
                # Expiring S3 URL — we MUST download it now
                raw_url = data.get("file", {}).get("url", "")
            elif image_type == "external":
                # Permanent external URL — downloading is optional but cleaner
                raw_url = data.get("external", {}).get("url", "")
            else:
                raw_url = ""

            # Alt text comes from the caption (optional in Notion)
            caption = get_plain_text(data.get("caption", []))
            alt_text = caption if caption else f"Image {image_counter}"

            if raw_url:
                if image_type == "file":
                    # Always download uploaded files — the URL will expire
                    local_filename = download_image(raw_url, post_dir, image_counter)
                    if local_filename:
                        # Relative path → works in Hugo Page Bundle
                        lines.append(f"![{alt_text}]({local_filename})")
                    else:
                        # Download failed — embed the (soon-to-expire) URL as fallback
                        lines.append(f"![{alt_text}]({raw_url})")
                else:
                    # External URLs are permanent — link directly, no download needed
                    # (We still track the counter for consistency)
                    lines.append(f"![{alt_text}]({raw_url})")

                image_counter += 1
            else:
                print(f"    ⚠️  Image block has no URL — skipping.")

        else:
            # Skip unsupported block types (embeds, videos, PDFs, etc.)
            pass

        lines.append("")  # blank line between blocks

    return "\n".join(lines).strip()


def fetch_page_content(notion: Client, page_id: str, post_dir: Path) -> str:
    """
    Fetch all blocks from a Notion page and convert them to Markdown.
    `post_dir` is passed through to convert_blocks_to_markdown for image downloads.
    """
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


# ---------------------------------------------------------------------------
# Hugo front matter + file generation
# ---------------------------------------------------------------------------

def extract_post_metadata(page: dict) -> dict:
    """
    Pull all metadata from a Notion page object and return as a plain dict.
    """
    props = page.get("properties", {})

    title_blocks = props.get("Title", {}).get("title", [])
    title = get_plain_text(title_blocks) or "Untitled"

    slug_blocks = props.get("Slug", {}).get("rich_text", [])
    slug_raw = get_plain_text(slug_blocks)
    slug = slug_raw.strip() if slug_raw.strip() else slugify(title)

    date_obj = props.get("Date", {}).get("date") or {}
    date_str = date_obj.get("start", "")
    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    desc_blocks = props.get("Description", {}).get("rich_text", [])
    description = get_plain_text(desc_blocks)

    tag_options = props.get("Tags", {}).get("multi_select", [])
    tags = [t["name"] for t in tag_options]

    return {
        "title": title,
        "slug": slug,
        "date": date_str,
        "description": description,
        "tags": tags,
        "notion_id": page["id"],
    }


def build_hugo_front_matter(meta: dict) -> str:
    """Build a TOML front matter block from post metadata."""
    tags_toml = "[" + ", ".join(f'"{t}"' for t in meta["tags"]) + "]"

    return f"""+++
title       = "{meta['title']}"
date        = "{meta['date']}"
slug        = "{meta['slug']}"
description = "{meta['description']}"
tags        = {tags_toml}
draft       = false
+++"""


def write_post(meta: dict, content: str):
    """
    Write the post as a Hugo Page Bundle.

    Structure created:
        content/posts/<slug>/
            index.md        ← the post Markdown
            image-0.jpg     ← downloaded images (if any)
            image-1.png
            …

    Hugo automatically treats index.md inside a directory as a Page Bundle,
    making all sibling files available as page resources.
    """
    # Create the post's own directory (the "bundle")
    post_dir = OUTPUT_DIR / meta["slug"]
    post_dir.mkdir(parents=True, exist_ok=True)

    filename = post_dir / "index.md"
    front_matter = build_hugo_front_matter(meta)

    with open(filename, "w", encoding="utf-8") as f:
        f.write(front_matter)
        f.write("\n\n")
        f.write(content)

    print(f"  ✓ Written: {filename}")
    return filename


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    validate_config()

    notion = Client(auth=NOTION_TOKEN)
    posts = fetch_published_posts(notion)

    if not posts:
        print("No published posts found. Nothing to sync.")
        return

    written = []
    for page in posts:
        meta = extract_post_metadata(page)
        print(f"\nSyncing: {meta['title']} (slug: {meta['slug']})")

        # Build the post directory path so image downloads can go there
        post_dir = OUTPUT_DIR / meta["slug"]

        content = fetch_page_content(notion, page["id"], post_dir)
        filepath = write_post(meta, content)
        written.append(filepath)

    print(f"\n✅ Sync complete. {len(written)} post(s) written to {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
