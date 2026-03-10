# My Notion Blog — Notion → Hugo → GitHub Pages

A minimal, beginner-friendly setup that lets you **write in Notion** and automatically **publish to GitHub Pages** using Hugo.
Powered by **[PaperMod](https://github.com/adityatelange/hugo-PaperMod)** — a fast, minimal, developer-friendly theme with dark/light mode, search, and a portfolio-style home page.
Supports **text, headings, lists, code blocks, and images** out of the box.

```
Notion (CMS)  →  Python script  →  Hugo (static site)  →  GitHub Pages
```

---

## Table of Contents

1. [Project Structure](#project-structure)
2. [How It Works](#how-it-works)
3. [Setup Guide](#setup-guide)
   - [Step 1: Fork / clone this repo](#step-1-fork--clone-this-repo)
   - [Step 2: Create a Notion Integration](#step-2-create-a-notion-integration)
   - [Step 3: Set up your Notion Database](#step-3-set-up-your-notion-database)
   - [Step 4: Configure GitHub Secrets](#step-4-configure-github-secrets)
   - [Step 5: Configure GitHub Pages](#step-5-configure-github-pages)
   - [Step 6: Install the Hugo theme](#step-6-install-the-hugo-theme)
   - [Step 7: Update hugo.toml](#step-7-update-hugotoml)
   - [Step 8: Push and watch it build!](#step-8-push-and-watch-it-build)
4. [Running Locally](#running-locally)
5. [Writing a New Post](#writing-a-new-post)
6. [Adding a Custom Domain](#adding-a-custom-domain)
7. [Troubleshooting](#troubleshooting)

---

## Project Structure

```
notion_website/
├── .github/
│   └── workflows/
│       └── deploy.yml          ← GitHub Actions: sync + build + deploy
├── content/
│   └── posts/
│       ├── my-first-post/      ← Hugo Page Bundle (one folder per post)
│       │   ├── index.md        ← post content + front matter
│       │   ├── image-0.jpg     ← images downloaded from Notion
│       │   └── image-1.png
│       └── another-post/
│           └── index.md
├── scripts/
│   ├── sync_notion.py          ← Python script: Notion → Markdown + images
│   └── requirements.txt        ← Python dependencies
├── themes/                     ← Hugo theme goes here (see Step 6)
├── hugo.toml                   ← Hugo site configuration
├── .gitignore
└── README.md
```

> **Page Bundles explained:** Instead of a single `my-post.md` file, each post
> gets its own folder (`my-post/index.md`). This lets Hugo treat images and
> other files inside that folder as "page resources" — they're served at the
> same URL as the post, which means relative image paths like `![alt](image-0.jpg)`
> just work.

---

## How It Works

1. You write a blog post in **Notion** and tick the **Published** checkbox.
2. You push any change to the `main` branch (or trigger the workflow manually).
3. **GitHub Actions** runs `sync_notion.py`, which:
   - Queries the Notion API for published posts
   - Downloads any images in the post body to the post's folder
   - Writes each post as `content/posts/<slug>/index.md`
4. Hugo compiles those files into a complete static website.
5. The built site is deployed to **GitHub Pages** automatically.

---

## Setup Guide

### Step 1: Fork / Clone This Repo

```bash
# Clone your fork
git clone https://github.com/<your-username>/<your-repo-name>.git
cd <your-repo-name>
```

---

### Step 2: Create a Notion Integration

An **Integration** is like an API key for your Notion workspace.

1. Go to [https://www.notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Click **"+ New integration"**
3. Give it a name (e.g. `Hugo Blog Sync`)
4. Set **Associated workspace** to your workspace
5. Under **Capabilities**, make sure **Read content** is checked  
   (you don't need Insert, Update, or Delete)
6. Click **Submit**
7. Copy the **Internal Integration Secret** — it looks like `secret_abc123...`  
   ⚠️ Keep this secret! Never commit it to Git.

---

### Step 3: Set Up Your Notion Database

Create a new **full-page database** in Notion (not an inline database).

Add these exact property names and types:

| Property Name | Type         | Notes                                      |
|---------------|--------------|--------------------------------------------|
| `Title`       | Title        | Built-in — already exists                  |
| `Slug`        | Text         | URL path, e.g. `my-first-post`             |
| `Published`   | Checkbox     | Only checked posts are synced              |
| `Date`        | Date         | Publication date shown in Hugo             |
| `Description` | Text         | Short summary for SEO / list pages         |
| `Tags`        | Multi-select | e.g. `python`, `hugo`, `tutorial`          |

**Connect your integration to this database:**

1. Open the database page in Notion
2. Click the `•••` menu (top right) → **"Add connections"**
3. Search for your integration name (e.g. `Hugo Blog Sync`) and click it

**Find your Database ID:**

The URL of your database page looks like:
```
https://www.notion.so/myworkspace/YOUR-DATABASE-ID?v=...
```
The Database ID is the 32-character string between the last `/` and the `?`.  
Example: `1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d`

---

### Step 4: Configure GitHub Secrets

Your Notion credentials must **never** be stored in Git. GitHub Secrets
keep them safe and inject them into the workflow at runtime.

1. Go to your GitHub repository
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **"New repository secret"** and add **both** of these:

| Secret Name           | Value                                                |
|-----------------------|------------------------------------------------------|
| `NOTION_TOKEN`        | Your integration secret (starts with `secret_...`)  |
| `NOTION_DATABASE_ID`  | Your 32-character database ID                        |

---

### Step 5: Configure GitHub Pages

1. Go to your GitHub repository → **Settings** → **Pages**
2. Under **Source**, select **"GitHub Actions"** ← important, not "Deploy from a branch"
3. Leave everything else as default

> **Note:** The first time you open this page, it might show "None" as the source.
> Just change it to "GitHub Actions" and save.

---

### Step 6: Install the Hugo Theme

This project uses **[PaperMod](https://github.com/adityatelange/hugo-PaperMod)** — a clean, fast,
minimalist developer theme with dark/light mode, full-text search, and a portfolio-style landing page.

The theme is already cloned into `themes/PaperMod/` as a git submodule. All you need to do is commit `.gitmodules`:

```bash
git add .gitmodules themes/PaperMod
git commit -m "Add PaperMod theme submodule"
```

**Personalise the home page** — open `hugo.toml` and update these lines:

```toml
[params.profileMode]
  title    = "Hey, I'm YOUR NAME 👋"   # ← your name
  subtitle = "Developer · Builder"      # ← your tagline
  imageUrl = "/avatar.jpg"              # ← replace static/avatar.jpg with your photo

[[params.socialIcons]]
  name = "github"
  url  = "https://github.com/yourhandle"  # ← your GitHub
```

> **Your avatar** — replace `static/avatar.jpg` with a square photo of yourself.
> Recommended size: 200×200px or larger (it is displayed at 120×120px).

> **Search page** — `content/search.md` is already created. It enables the `/search/` route
> in PaperMod automatically — no extra setup needed.

---

### Step 7: Update hugo.toml

Open `hugo.toml` and change these two lines to match your setup:

```toml
# Replace with your actual GitHub Pages URL
baseURL = "https://<your-username>.github.io/<your-repo-name>/"

# Change to whatever you want shown in the browser tab
title = "My Blog"
```

---

### Step 8: Push and Watch It Build!

```bash
git add .
git commit -m "Initial setup"
git push origin main
```

1. Go to the **Actions** tab in your GitHub repo
2. You should see the **"Deploy Hugo site to GitHub Pages"** workflow running
3. When it finishes (usually 1–2 minutes), visit your site at:  
   `https://<your-username>.github.io/<your-repo-name>/`

---

## Running Locally

Useful for testing before you push.

**Prerequisites:** Python 3.9+, Hugo extended (install from [gohugo.io/installation](https://gohugo.io/installation/))

```bash
# 1. Install Python dependencies
pip install -r scripts/requirements.txt

# 2. Create a local .env file (NEVER commit this file)
#    Copy your secrets here for local testing only:
#    NOTION_TOKEN=secret_abc123...
#    NOTION_DATABASE_ID=1a2b3c4d...

# 3. Load the env vars and run the sync
$env:NOTION_TOKEN="secret_abc123..."           # PowerShell
$env:NOTION_DATABASE_ID="1a2b3c4d..."          # PowerShell
python scripts/sync_notion.py

# 4. Start the Hugo dev server
hugo server -D

# Open http://localhost:1313 in your browser
```

---

## Writing a New Post

1. Open your Notion database
2. Click **"+ New"** to create a page
3. Fill in the properties:
   - **Title**: Your post title
   - **Slug**: A URL-safe name, e.g. `my-awesome-post` (no spaces, no capitals)
   - **Date**: The publication date
   - **Description**: A short summary (appears on the posts list page)
   - **Tags**: Add any relevant tags
   - **Published**: ☐ Leave unchecked while drafting; ☑ Check when ready to publish
4. Write your post content in the page body using Notion's editor
5. Push any change to `main` (or trigger the workflow manually) to deploy

> **Tip:** If you leave Slug blank, the script auto-generates one from the Title.

### Adding images to a post

Just drag-and-drop or paste images directly into the Notion page body — no extra
steps needed. The sync script handles two cases automatically:

| Image type | What the script does |
|---|---|
| **Uploaded** (dragged into Notion) | Downloaded immediately — Notion's URLs expire after ~1 hour |
| **External** (pasted as a URL / embed) | Linked directly — the URL is permanent |

Downloaded images are saved as `image-0.jpg`, `image-1.png`, etc. next to `index.md`
and referenced with a relative path in the Markdown (`![caption](image-0.jpg)`).

To add a caption, click the image in Notion and type in the caption field underneath it —
the caption becomes the Markdown alt text.

---

## Adding a Custom Domain

1. Buy a domain from any registrar (Namecheap, Cloudflare, etc.)
2. In your DNS settings, add a **CNAME** record:
   - **Name**: `www` (or `@` for apex)
   - **Value**: `<your-username>.github.io`
3. In GitHub → Settings → Pages → **Custom domain**, enter your domain
4. Tick **"Enforce HTTPS"** once the DNS propagates (can take up to 48 hours)
5. Update `baseURL` in `hugo.toml` to your custom domain:
   ```toml
   baseURL = "https://www.yourdomain.com/"
   ```

---

## Troubleshooting

### ❌ Workflow fails with "NOTION_TOKEN not set"

**Cause:** The GitHub Secret is missing or misspelled.  
**Fix:** Go to Settings → Secrets → Actions and confirm both `NOTION_TOKEN`
and `NOTION_DATABASE_ID` are present (exact case, no extra spaces).

---

### ❌ "Could not find database" / HTTP 404 from Notion API

**Cause:** The integration doesn't have access to the database.  
**Fix:** Open the database in Notion → `•••` menu → **Add connections** →
select your integration. Without this step, the API returns a 404.

---

### ❌ Posts are fetched but the site is blank / shows no posts

**Cause:** The theme is missing (not installed as a submodule).  
**Fix:** Run `git submodule add https://github.com/theNewDynamic/gohugo-theme-ananke themes/ananke`
and commit the result. Also check that `theme = "ananke"` in `hugo.toml` matches
the folder name inside `themes/`.

---

### ❌ GitHub Pages still shows the old site after deploy

**Cause:** Browser cache or DNS propagation.  
**Fix:** Hard-refresh (`Ctrl+Shift+R`) or open an incognito tab. Allow up to
10 minutes for the first deployment to become visible.

---

### ❌ Posts have the wrong URL / links are broken

**Cause:** `baseURL` in `hugo.toml` doesn't match your Pages URL.  
**Fix:** Update `baseURL` to exactly `https://<username>.github.io/<repo>/`
(include the trailing slash).

---

### ❌ GitHub Actions: "Resource not accessible by integration" on deploy step

**Cause:** Pages permissions aren't set correctly.  
**Fix:**
1. Settings → Pages → Source → set to **"GitHub Actions"** (not branch)
2. Settings → Actions → General → Workflow permissions → set to
   **"Read and write permissions"**

---

### ❌ `python-slugify` import error in CI

**Cause:** The package name on PyPI is `python-slugify` but the import is `from slugify import slugify`.
This is intentional — `pip install python-slugify` installs the `slugify` module.  
**Fix:** Make sure `requirements.txt` lists `python-slugify` (not `slugify`).
The `slugify` package on PyPI is a different, older library.

---

### ❌ Images appear broken / not loading

**Cause A:** You're using the old v1 of the script (text-only).  
**Fix:** Make sure you have the latest `sync_notion.py` — it downloads images locally.

**Cause B:** An image download failed during CI (network issue).  
**Fix:** Trigger the workflow again manually from the Actions tab. The script will
re-download all images from fresh Notion URLs.

**Cause C:** You embedded an external image that has since gone offline.  
**Fix:** In Notion, delete the image and re-upload it directly (don't paste a URL).
This makes it a Notion-hosted file that the script will download.

---

*Built with [Hugo](https://gohugo.io) · Powered by [Notion API](https://developers.notion.com) · Hosted on [GitHub Pages](https://pages.github.com)*
