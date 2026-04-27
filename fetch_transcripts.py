"""
YouTube Transcript Fetcher
Fetches transcripts from YouTube videos using YTFetcher (for channel listing)
and youtube-transcript-api (for transcripts, including auto-generated)
V4 - Supports auto-generated transcripts

Usage:
    python fetch_transcripts.py --channel FedorKrasheninnikov --max-results 30
    python fetch_transcripts.py --channel BaunovTube --max-results 300
"""

import argparse
import os
import re
import unicodedata
from html import unescape

import pandas as pd
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from openai import OpenAI
from ytfetcher import YTFetcher
from ytfetcher.config import FetchOptions
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled

# ── CLI arguments ────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="Fetch YouTube transcripts")
parser.add_argument("--channel", required=True, help="YouTube channel handle")
parser.add_argument("--max-results", type=int, default=30,
                    help="Max videos to fetch (default: 30, use 300 for full scan)")
parser.add_argument("--output-dir", default=".",
                    help="Root output directory (default: repo root)")
args = parser.parse_args()

CHANNEL_NAME = args.channel
MAX_RESULTS   = args.max_results
OUTPUT_ROOT   = args.output_dir

# ── API keys from environment ────────────────────────────────────────────────

YOUTUBE_API_KEY    = os.environ["YOUTUBE_API_KEY"]
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]

openrouter_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

# ── Transcript fetching ──────────────────────────────────────────────────────

def fetch_transcript(video_id):
    try:
        ytt = YouTubeTranscriptApi()                        # ← instantiate first
        transcript_list = ytt.list(video_id)               # ← .list() not .list_transcripts()

        transcript = None

        try:
            transcript = transcript_list.find_manually_created_transcript(['ru', 'en'])
        except NoTranscriptFound:
            pass

        if not transcript:
            try:
                transcript = transcript_list.find_generated_transcript(['ru', 'en'])
            except NoTranscriptFound:
                pass

        if not transcript:
            try:
                transcript = next(iter(transcript_list))
            except StopIteration:
                pass

        if not transcript:
            print(f"  ✗ No transcript found in any language")
            return None, None

        data = transcript.fetch()
        text = " ".join(entry.text for entry in data)      # ← entry.text not entry['text']
        lang = transcript.language_code
        kind = "auto-generated" if transcript.is_generated else "manual"
        print(f"  ✓ Transcript: {len(text)} chars [{lang}, {kind}]")
        return text, lang

    except TranscriptsDisabled:
        print(f"  ✗ Transcripts are disabled for this video")
        return None, None
    except Exception as e:
        print(f"  ✗ Transcript error: {e}")
        return None, None

# ── Helpers ──────────────────────────────────────────────────────────────────

def clean_comment_html(html_text):
    """Convert HTML comment with timestamp links to clean markdown list."""
    if not html_text:
        return None

    text = unescape(html_text)
    pattern = r'<a[^>]*>\d+:\d+</a>\s*([^<]+)(?:<br>|$)'
    matches = re.findall(pattern, text)

    if matches:
        lines = [f"- {t.strip()}" for t in matches if t.strip()]
        return '\n'.join(lines)
    else:
        text = re.sub(r'<br\s*/?>', '\n', text)
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\n+', '\n', text)
        text = re.sub(r' +', ' ', text)
        return text.strip()


def load_existing_transcripts(transcripts_folder):
    """Return set of video_ids that already have transcript files."""
    if not os.path.exists(transcripts_folder):
        print(f"ℹ No existing transcript folder found. Starting fresh.")
        return set()

    existing = set()
    for filename in os.listdir(transcripts_folder):
        if filename.endswith('.md') and filename != 'README.md':
            filepath = os.path.join(transcripts_folder, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                    match = re.search(r'video_id:\s*(\S+)', content)
                    if match:
                        existing.add(match.group(1))
            except Exception as e:
                print(f"⚠ Error reading {filename}: {e}")

    print(f"✓ Found {len(existing)} existing transcripts")
    return existing


def get_video_publish_date(video_id):
    """Return publish date string (YYYY-MM-DD) or None."""
    try:
        response = youtube.videos().list(
            part="snippet", id=video_id, hl='ru'
        ).execute()

        if response.get('items'):
            published_at = response['items'][0]['snippet'].get('publishedAt')
            if published_at:
                return published_at.split('T')[0]
        return None
    except Exception as e:
        print(f"  ⚠ Error fetching publish date: {e}")
        return None


def generate_machine_summary(video_title, transcript):
    """Generate a Russian summary using OpenRouter."""
    try:
        transcript_for_llm = transcript[:100000]
        print(f"  Generating AI summary...")

        response = openrouter_client.chat.completions.create(
            model="openrouter/free",
            messages=[{
                "role": "user",
                "content": f"""This is a transcript of a YouTube video titled "{video_title}".

Please provide:
1. A brief 2-3 sentence summary of the main topic
2. 3-5 key points discussed (as a bullet list), speaker opinion on each or what he thinks will happen or what we learnt from this.
3. People or countries mentioned in the talk.

Write in Russian.

Transcript:
{transcript_for_llm}"""
            }]
        )

        summary = response.choices[0].message.content
        print(f"  ✓ AI summary generated ({len(summary)} chars)")
        return summary
    except Exception as e:
        print(f"  ⚠ Could not generate AI summary: {e}")
        return None


def get_comment_by_user(video_id, target_username="mitakka7490"):
    """Return comment dict by target user or None."""
    try:
        target_normalized = target_username.lower().replace('@', '')

        response = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=100,
            order="relevance"
        ).execute()

        def match_author(snippet):
            author_display = snippet['authorDisplayName']
            author_url     = snippet.get('authorChannelUrl', '')
            author_norm    = author_display.lower().replace('@', '')
            channel_handle = author_url.split('@')[-1].lower() if '@' in author_url else ''
            return (target_normalized in author_norm or
                    author_norm in target_normalized or
                    target_normalized == channel_handle)

        def extract_comment(item):
            snippet = item['snippet']['topLevelComment']['snippet']
            if match_author(snippet):
                print(f"  ℹ Matched: '{snippet['authorDisplayName']}'")
                return {
                    'text': clean_comment_html(snippet['textDisplay']),
                    'author': snippet['authorDisplayName'],
                    'like_count': snippet.get('likeCount', 0)
                }
            return None

        for item in response.get('items', []):
            result = extract_comment(item)
            if result:
                return result

        page_count = 1
        while 'nextPageToken' in response and page_count < 3:
            page_count += 1
            response = youtube.commentThreads().list(
                part="snippet",
                videoId=video_id,
                maxResults=100,
                pageToken=response['nextPageToken'],
                order="relevance"
            ).execute()
            for item in response.get('items', []):
                result = extract_comment(item)
                if result:
                    return result

        print(f"  ℹ Checked {page_count} page(s), no match found")
        return None

    except HttpError as e:
        print(f"  ⚠ HTTP error fetching comments: {e}")
        return None
    except Exception as e:
        print(f"  ⚠ Error: {e}")
        return None


def safe_filename(video_id, title):
    """Build a GitHub Pages-safe NFC filename from video_id + title."""
    clean = re.sub(r'[^\w\s-]', '', title)
    clean = re.sub(r'[-\s]+', '-', clean)
    clean = clean.strip('-_')[:50]
    clean = unicodedata.normalize('NFC', clean)
    if clean.startswith('_'):
        clean = clean.lstrip('_')
    if not clean:
        clean = "untitled"
    safe_id = video_id.lstrip('_')
    return f"{safe_id}-{clean}.md"


def write_transcript_file(filepath, row):
    """Write a single transcript markdown file."""
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("---\n")
        f.write(f"title: \"{row['title']}\"\n")
        f.write(f"video_id: {row['video_id']}\n")
        f.write(f"url: {row['url']}\n")
        if pd.notna(row['published_at']):
            f.write(f"date: {row['published_at']}\n")
        f.write(f"duration: {row['duration']}\n")
        f.write(f"views: {row['view_count']}\n")
        f.write(f"transcript_language: {row.get('transcript_language', 'unknown')}\n")
        f.write("---\n\n")

        f.write(f"# {row['title']}\n\n")
        if pd.notna(row['published_at']):
            f.write(f"**Published:** {row['published_at']}\n\n")

        f.write("## Video Information\n\n")
        f.write(f"- **URL**: [{row['url']}]({row['url']})\n")
        f.write(f"- **Video ID**: `{row['video_id']}`\n")
        f.write(f"- **Duration**: {row['duration']} seconds\n")
        f.write(f"- **Views**: {row['view_count']:,}\n\n")

        if pd.notna(row['summary']) and row['summary']:
            f.write("## Summary\n\n")
            f.write(f"{row['summary']}\n\n")

        if pd.notna(row['machine_summary']) and row['machine_summary']:
            f.write("## Machine Summary\n\n")
            f.write(f"{row['machine_summary']}\n\n")

        f.write("## Transcript\n\n")
        f.write(row['transcript'])


def update_readme(transcripts_folder, channel_name):
    """Regenerate README.md from all transcript files in the folder."""
    readme_path = os.path.join(transcripts_folder, 'README.md')
    all_videos = []

    for filename in os.listdir(transcripts_folder):
        if not filename.endswith('.md') or filename == 'README.md':
            continue
        filepath = os.path.join(transcripts_folder, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            title_match    = re.search(r'title:\s*"([^"]+)"', content)
            video_id_match = re.search(r'video_id:\s*(\S+)', content)
            date_match     = re.search(r'^date:\s*(\S+)', content, re.MULTILINE) or \
                             re.search(r'published_at:\s*(\S+)', content)
            views_match    = re.search(r'views:\s*(\d+)', content)

            if title_match and video_id_match:
                all_videos.append({
                    'filename':     filename,
                    'title':        title_match.group(1),
                    'video_id':     video_id_match.group(1),
                    'published_at': date_match.group(1) if date_match else None,
                    'views':        int(views_match.group(1)) if views_match else 0
                })
        except Exception as e:
            print(f"⚠ Error reading {filename} for README: {e}")

    all_videos.sort(key=lambda x: x['published_at'] or '', reverse=True)

    with open(readme_path, 'w', encoding='utf-8') as f:
        f.write(f"# {channel_name} - Video Transcripts\n\n")
        f.write(f"This folder contains {len(all_videos)} video transcripts.\n\n")
        f.write("## Videos\n\n")
        for video in all_videos:
            if video['published_at']:
                f.write(f"- **{video['published_at']}** - [{video['title']}](./{video['filename']})")
            else:
                f.write(f"- [{video['title']}](./{video['filename']})")
            if video['views'] > 0:
                f.write(f" - {video['views']:,} views")
            f.write("\n")

    print(f"✓ README updated with {len(all_videos)} videos → {readme_path}")


# ── Main ─────────────────────────────────────────────────────────────────────

transcripts_folder = os.path.join(OUTPUT_ROOT, CHANNEL_NAME)
os.makedirs(transcripts_folder, exist_ok=True)

existing_video_ids = load_existing_transcripts(transcripts_folder)

# YTFetcher is only used for channel video listing, NOT for transcript fetching
options = FetchOptions(languages=['ru', 'en'])

print(f"\nFetching up to {MAX_RESULTS} videos from @{CHANNEL_NAME}...")
fetcher = YTFetcher.from_channel(
    channel_handle=CHANNEL_NAME,
    max_results=MAX_RESULTS,
    options=options
)

print("Fetching video list...")
channel_data = fetcher.fetch_youtube_data()

print(f"\nFound {len(channel_data)} videos")
print("=" * 80)

results = []

for idx, video_data in enumerate(channel_data, 1):
    print(f"\n[{idx}/{len(channel_data)}] {video_data.metadata.title}")
    print(f"  ID: {video_data.video_id} | {video_data.metadata.url}")

    if video_data.video_id in existing_video_ids:
        print(f"  ✓ Already exists — skipping")
        print("-" * 80)
        continue

    user_comment = get_comment_by_user(video_data.video_id)
    if user_comment:
        print(f"  ✓ Comment by {user_comment['author']} ({user_comment['like_count']} likes)")
    else:
        print(f"  ℹ No comment by @mitakka7490")

    published_at = get_video_publish_date(video_data.video_id)
    if published_at:
        print(f"  Published: {published_at}")

    # Fetch transcript directly via youtube-transcript-api (handles auto-generated)
    full_transcript, transcript_language = fetch_transcript(video_data.video_id)

    if full_transcript:
        machine_summary = generate_machine_summary(video_data.metadata.title, full_transcript)

        results.append({
            'video_id':            video_data.video_id,
            'title':               video_data.metadata.title,
            'description':         video_data.metadata.description,
            'url':                 video_data.metadata.url,
            'published_at':        published_at,
            'duration':            video_data.metadata.duration,
            'view_count':          video_data.metadata.view_count,
            'summary':             user_comment['text'] if user_comment else None,
            'summary_author':      user_comment['author'] if user_comment else None,
            'summary_likes':       user_comment['like_count'] if user_comment else None,
            'machine_summary':     machine_summary,
            'transcript':          full_transcript,
            'transcript_language': transcript_language,
            'segment_count':       len(full_transcript.split()),
            'character_count':     len(full_transcript)
        })
        print(f"  Preview: {full_transcript[:200]}...")
    else:
        print(f"  ✗ Skipping — no transcript available")

    print("-" * 80)

# Save results
if results:
    df = pd.DataFrame(results)
    print(f"\n{'='*80}")
    print(f"Fetched {len(results)} new transcripts ({len(existing_video_ids)} already existed)")

    for _, row in df.iterrows():
        fname    = safe_filename(row['video_id'], row['title'])
        filepath = os.path.join(transcripts_folder, fname)
        write_transcript_file(filepath, row)
        print(f"✓ Saved {fname}")
else:
    print("\n⚠ No new transcripts fetched")

# Always regenerate README
update_readme(transcripts_folder, CHANNEL_NAME)

print(f"\nDone. Files in: {transcripts_folder}")
