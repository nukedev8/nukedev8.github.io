"""
sync_notion.py
==============
Pulls published posts AND projects from Notion databases and writes them
as Hugo-compatible Markdown files.

Posts  → content/posts/<slug>/index.md
Projects → content/projects/<slug>/index.md

Environment variables (set these as GitHub Secrets):
    NOTION_TOKEN                — your Notion integration secret key
    NOTION_DATABASE_ID          — ID of your "Posts" database
    NOTION_PROJECTS_DATABASE_ID — ID of your "Projects" database (optional)
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
NOTION_PROJECTS_DATABASE_ID = os.environ.get("NOTION_PROJECTS_DATABASE_ID")

# Output directories
POSTS_DIR   = Path("content/posts")
PROJECTS_DIR = Path("content/projects")

IMAGE_DOWNLOAD_TIMEOUT = 30


def validate_config():
    """Make sure the required environment variables are set before we start."""
    if not NOTION_TOKEN:
        print("ERROR: NOTION_TOKEN environment variable is not set.")
        sys.exit(1)
    if not NOTION_DATABASE_ID:
        print("ERROR: NOTION_DATABASE_ID environment variable is not set.")
        sys.exit(1)
    if not NOTION_PROJECTS_DATABASE_ID:
        print("ℹ️  NOTION_PROJECTS_DATABASE_ID not set — skipping projects sync.")
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

    # --- DEBUG: show actual property names when nothing is found ---
    # Check the CI logs for this output if posts aren't syncing
    if not results:
        print("\n🔍 DEBUG: 0 posts found. Inspecting your database properties...")
        try:
            debug_resp = notion.databases.query(database_id=NOTION_DATABASE_ID, page_size=1)
            pages = debug_resp.get("results", [])
            if pages:
                print("  Properties in your database:")
                for name, val in pages[0].get("properties", {}).items():
                    print(f"    '{name}' (type: {val.get('type')})")
                print("\n  Script expects: 'Title', 'Slug', 'Published' (checkbox ✅), 'Date', 'Description', 'Tags'")
            else:
                print("  Database is empty — add a page and tick 'Published'.")
        except Exception as e:
            print(f"  DEBUG fetch failed: {e}")

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


def write_post(meta: dict, content: str, output_dir: Path = None):
    """
    Write the page as a Hugo Page Bundle to the given output_dir.
    Defaults to POSTS_DIR if not specified.
    """
    if output_dir is None:
        output_dir = POSTS_DIR

    post_dir = output_dir / meta["slug"]
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
# Projects — separate Notion database
# ---------------------------------------------------------------------------

def extract_project_metadata(page: dict) -> dict:
    """
    Pull metadata from a Notion Projects database page.

    Expected Notion properties:
        Name        (title)
        Slug        (rich text)
        Published   (checkbox)
        Description (rich text)
        Tags        (multi-select)
        URL         (url)       — live project link
        GitHub      (url)       — source code link
    """
    props = page.get("properties", {})

    name_blocks = props.get("Name", {}).get("title", [])
    title = get_plain_text(name_blocks) or "Untitled Project"

    slug_blocks = props.get("Slug", {}).get("rich_text", [])
    slug_raw = get_plain_text(slug_blocks)
    slug = slug_raw.strip() if slug_raw.strip() else slugify(title)

    desc_blocks = props.get("Description", {}).get("rich_text", [])
    description = get_plain_text(desc_blocks)

    tag_options = props.get("Tags", {}).get("multi_select", [])
    tags = [t["name"] for t in tag_options]

    project_url = props.get("URL", {}).get("url") or ""
    github_url  = props.get("GitHub", {}).get("url") or ""

    return {
        "title": title,
        "slug": slug,
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "description": description,
        "tags": tags,
        "projectURL": project_url,
        "githubURL": github_url,
    }


def build_project_front_matter(meta: dict) -> str:
    """Build TOML front matter for a project page."""
    tags_toml = "[" + ", ".join(f'"{ t}"' for t in meta["tags"]) + "]"
    return f"""+++
title       = "{meta['title']}"
date        = "{meta['date']}"
slug        = "{meta['slug']}"
description = "{meta['description']}"
tags        = {tags_toml}
projectURL  = "{meta['projectURL']}"
githubURL   = "{meta['githubURL']}"
draft       = false
+++"""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    validate_config()
    notion = Client(auth=NOTION_TOKEN)

    # --- Sync Posts ---
    print("\n📝 Syncing Posts...")
    posts = fetch_published_posts(notion)
    written_posts = []
    for page in posts:
        meta = extract_post_metadata(page)
        print(f"  Syncing: {meta['title']} (slug: {meta['slug']})")
        post_dir = POSTS_DIR / meta["slug"]
        content = fetch_page_content(notion, page["id"], post_dir)
        written_posts.append(write_post(meta, content, POSTS_DIR))
    print(f"✅ Posts: {len(written_posts)} written.")

    # --- Sync Projects (optional) ---
    if NOTION_PROJECTS_DATABASE_ID:
        print("\n🚀 Syncing Projects...")
        projects_response = notion.databases.query(
            database_id=NOTION_PROJECTS_DATABASE_ID,
            filter={"property": "Published", "checkbox": {"equals": True}},
        )
        project_pages = projects_response.get("results", [])
        print(f"Found {len(project_pages)} published project(s).")

        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        written_projects = []
        for page in project_pages:
            meta = extract_project_metadata(page)
            print(f"  Syncing: {meta['title']} (slug: {meta['slug']})")
            project_dir = PROJECTS_DIR / meta["slug"]
            content = fetch_page_content(notion, page["id"], project_dir)

            # Append live links to the content if provided
            links = []
            if meta["projectURL"]:
                links.append(f"🔗 [Live Project]({meta['projectURL']})")
            if meta["githubURL"]:
                links.append(f"🐙 [GitHub]({meta['githubURL']})")
            if links:
                content = " · ".join(links) + "\n\n" + content

            written_projects.append(write_post(meta, content, PROJECTS_DIR))
        print(f"✅ Projects: {len(written_projects)} written.")
    else:
        print("\nℹ️  Projects skipped (NOTION_PROJECTS_DATABASE_ID not set).")


if __name__ == "__main__":
    main()
