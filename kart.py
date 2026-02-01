import os
import shutil
import time
import sqlite3
from datetime import datetime

# --- CONFIGURATION ---
EARTH_PATH = os.path.dirname(os.path.abspath(__file__))
ARTIFACTS_PATH = os.path.join(EARTH_PATH, "artifacts")

# Legacy global paths (used only when running standalone without --user)
DEFAULT_USER = "Sweet-Pea-Rudi19"

# --- DEFINITIONS ---
# L5: Narrative, Creative, "Our Bob", The Mann Convergence
L5_KEYWORDS = ["chapter", "draft", "prologue", "mann", "christoph", "thriller", "fictional", "narrative", "book", "story"]

# L6: Operational, Legal, Technical, FOIA, NVIDIA
L6_KEYWORDS = ["spec", "legal", "foia", "nvidia", "report", "governance", "ai usage", "framework", "technical", "instruction"]

# Screenshots / phone captures (by filename pattern)
SCREENSHOT_PATTERNS = ["screenshot", "screencap", "screen_shot", "screen shot"]
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}


def _user_paths(username):
    """Resolve per-user paths."""
    user_root = os.path.join(ARTIFACTS_PATH, username)
    return {
        "pending": os.path.join(user_root, "pending"),
        "narrative": os.path.join(user_root, "narrative"),
        "specs": os.path.join(user_root, "specs"),
        "screenshots": os.path.join(user_root, "screenshots"),
        "photos": os.path.join(user_root, "photos"),
        "documents": os.path.join(user_root, "documents"),
        "db": os.path.join(user_root, "willow_index.db"),
    }


def classify_iron(filename):
    """
    Fast pre-classifier based on filename keywords and extension.
    Returns: (category_folder, category_label) or (None, "UNCLASSIFIED")

    This is the fast-path fallback. aios_loop uses LLM routing first,
    kart catches what the LLM can't reach (offline, timeout, etc).
    """
    fn_lower = filename.lower()
    ext = os.path.splitext(fn_lower)[1]

    # Screenshots: filename pattern match (e.g. "Screenshot_20260131_111858_Facebook.jpg")
    if any(pat in fn_lower for pat in SCREENSHOT_PATTERNS):
        return "screenshots", "SCREENSHOTS"

    # Photos: image files that aren't screenshots (phone camera dumps, etc.)
    if ext in IMAGE_EXTENSIONS:
        return "photos", "PHOTOS"

    # L5: Narrative / Creative
    if any(keyword in fn_lower for keyword in L5_KEYWORDS):
        return "narrative", "L5_NARRATIVE"

    # L6: Operational / Technical / Legal
    if any(keyword in fn_lower for keyword in L6_KEYWORDS):
        return "specs", "L6_SPECS"

    # General documents (catch PDFs, text, markdown that didn't match above)
    if ext in {".pdf", ".txt", ".md", ".docx", ".sdocx"}:
        return "documents", "DOCUMENTS"

    return None, "UNCLASSIFIED"


def refine_ore(username=None):
    """
    Scans the user's pending folder and sorts files into L5 or L6.
    Per-user: artifacts/{username}/pending -> artifacts/{username}/{category}
    """
    username = username or DEFAULT_USER
    paths = _user_paths(username)

    if not os.path.exists(paths["pending"]):
        return

    db_path = paths["db"]
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    cursor = conn.cursor()

    # Ensure table exists
    cursor.execute("""CREATE TABLE IF NOT EXISTS file_registry (
        file_hash TEXT PRIMARY KEY,
        filename TEXT,
        ingest_date TEXT,
        category TEXT,
        status TEXT DEFAULT 'active',
        source TEXT,
        provider TEXT,
        archive_date TEXT,
        archive_path TEXT,
        deleted_date TEXT,
        flagged_reason TEXT,
        retain_context INTEGER DEFAULT 1
    )""")
    conn.commit()

    # Get already-processed filenames to avoid re-refining
    cursor.execute("SELECT filename FROM file_registry WHERE status='active'")
    already_processed = {row[0] for row in cursor.fetchall()}

    for filename in os.listdir(paths["pending"]):
        file_path = os.path.join(paths["pending"], filename)

        if not os.path.isfile(file_path):
            continue

        # Skip if already refined in a previous cycle
        if filename in already_processed:
            continue

        category_folder, category = classify_iron(filename)

        if category_folder:
            dest_dir = os.path.join(ARTIFACTS_PATH, username, category_folder)
            os.makedirs(dest_dir, exist_ok=True)
            dest_path = os.path.join(dest_dir, filename)

            try:
                # Handle collision: don't overwrite existing files
                if os.path.exists(dest_path):
                    stem, ext = os.path.splitext(filename)
                    dest_path = os.path.join(dest_dir, f"{stem}_{datetime.now().strftime('%H%M%S')}{ext}")

                shutil.move(file_path, dest_path)

                cursor.execute("""
                    UPDATE file_registry
                    SET status='active', category=?
                    WHERE filename=?
                """, (category, filename))

                if cursor.rowcount == 0:
                    cursor.execute("""
                        INSERT INTO file_registry (filename, ingest_date, category, status)
                        VALUES (?, ?, ?, 'active')
                    """, (filename, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), category))

                conn.commit()
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Refined [{username}]: {filename} -> {category}")

            except Exception as e:
                print(f"Error refining {filename}: {e}")

    conn.close()


if __name__ == "__main__":
    import sys

    username = DEFAULT_USER
    if "--user" in sys.argv:
        idx = sys.argv.index("--user")
        if idx + 1 < len(sys.argv):
            username = sys.argv[idx + 1]

    print(f"Initializing Kartikeya Refinery [User: {username}]...")

    while True:
        refine_ore(username)
        time.sleep(15)