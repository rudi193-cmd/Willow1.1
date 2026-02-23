#!/usr/bin/env python3
"""
Bootstrap script for social_media.db
Creates schema and seeds known data from OCR analysis.
"""
import sqlite3
import os

DB_PATH = r"C:\Users\Sean\Documents\GitHub\Willow\artifacts\Sweet-Pea-Rudi19\social\social_media.db"
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

conn = sqlite3.connect(DB_PATH)
conn.executescript("""
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS platforms (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    url         TEXT,
    type        TEXT,
    notes       TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS accounts (
    id          INTEGER PRIMARY KEY,
    platform_id INTEGER REFERENCES platforms(id),
    handle      TEXT NOT NULL,
    display_name TEXT,
    profile_url TEXT,
    karma       INTEGER,
    followers   INTEGER,
    bio         TEXT,
    first_seen  TEXT,
    last_updated TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS communities (
    id          INTEGER PRIMARY KEY,
    platform_id INTEGER REFERENCES platforms(id),
    name        TEXT NOT NULL,
    display_name TEXT,
    description TEXT,
    owner       TEXT,
    topic       TEXT,
    url         TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS series (
    id          INTEGER PRIMARY KEY,
    title       TEXT NOT NULL,
    slug        TEXT UNIQUE,
    description TEXT,
    status      TEXT DEFAULT 'active',
    episode_count INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS posts (
    id          INTEGER PRIMARY KEY,
    account_id  INTEGER REFERENCES accounts(id),
    community_id INTEGER REFERENCES communities(id),
    series_id   INTEGER REFERENCES series(id),
    title       TEXT NOT NULL,
    body_snippet TEXT,
    posted_at   TEXT,
    url         TEXT,
    status      TEXT DEFAULT 'active',
    is_crosspost INTEGER DEFAULT 0,
    parent_post_id INTEGER REFERENCES posts(id),
    notes       TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS post_metrics (
    id          INTEGER PRIMARY KEY,
    post_id     INTEGER REFERENCES posts(id),
    snapshot_at TEXT,
    views_total INTEGER,
    views_48h   INTEGER,
    upvotes     INTEGER,
    upvote_ratio REAL,
    comments    INTEGER,
    shares      INTEGER,
    crossposts  INTEGER,
    awards      INTEGER,
    rank_today  TEXT,
    geo_us_pct  REAL,
    geo_breakdown TEXT,
    source_file TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS milestones (
    id          INTEGER PRIMARY KEY,
    post_id     INTEGER REFERENCES posts(id),
    account_id  INTEGER REFERENCES accounts(id),
    milestone   TEXT NOT NULL,
    achieved_at TEXT,
    metric_value TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS knowledge_gaps (
    id          INTEGER PRIMARY KEY,
    context     TEXT,
    context_id  INTEGER,
    field       TEXT NOT NULL,
    description TEXT,
    priority    TEXT DEFAULT 'medium',
    status      TEXT DEFAULT 'open',
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5(
    title, body_snippet, notes,
    content=posts, content_rowid=id
);
""")
conn.commit()

# Platforms
conn.executemany(
    "INSERT OR IGNORE INTO platforms(name, url, type, notes) VALUES (?,?,?,?)",
    [
        ("Reddit",   "https://reddit.com",   "reddit",   "Primary platform. Account: u/BeneficialBig8372"),
        ("LinkedIn", "https://linkedin.com", "linkedin", "Professional. Handle: Sean Campbell"),
        ("Facebook", "https://facebook.com", "facebook", "Personal. Connected to TJ/family circles"),
        ("Hinge",    "https://hinge.co",     "dating",   "Dating app — limited tracking"),
        ("Feeld",    "https://feeld.co",     "dating",   "Dating app — limited tracking"),
    ]
)
conn.commit()

rpl = conn.execute("SELECT id FROM platforms WHERE name='Reddit'").fetchone()[0]
lip = conn.execute("SELECT id FROM platforms WHERE name='LinkedIn'").fetchone()[0]
fbp = conn.execute("SELECT id FROM platforms WHERE name='Facebook'").fetchone()[0]

# Accounts
conn.executemany(
    "INSERT OR IGNORE INTO accounts(platform_id, handle, display_name, karma, followers, bio, first_seen) VALUES (?,?,?,?,?,?,?)",
    [
        (rpl, "BeneficialBig8372", "Sean Campbell", 1000, 10,
         "1.0k karma, 3y account age, 33 achievements. 10 followers.", "2022-01-01"),
        (lip, "sean-campbell-systemic", "Sean Campbell", None, 77,
         "Systemic Pattern Analyst | Writer. 77 followers, 91 impressions on recent posts.", "2025-01-01"),
        (fbp, "sean.campbell", "Sean Campbell", None, None,
         "Personal Facebook. Follows political commentary, TJ community.", "2025-01-01"),
    ]
)
conn.commit()

reddit_acct = conn.execute("SELECT id FROM accounts WHERE handle='BeneficialBig8372'").fetchone()[0]
li_acct = conn.execute("SELECT id FROM accounts WHERE handle='sean-campbell-systemic'").fetchone()[0]

# Communities
conn.executemany(
    "INSERT OR IGNORE INTO communities(platform_id, name, display_name, description, owner, topic) VALUES (?,?,?,?,?,?)",
    [
        (rpl, "DispatchesFromReaIity", "r/DispatchesFromReaIity",
         "Sean's narrative fiction subreddit. Home of Dispatches, Regarding Jane, and UTETY universe.",
         "sean", "fiction"),
        (rpl, "tjcrew", "r/tjcrew",
         "Trader Joe's crew community. WC context — Sean's TJ injury post got 17.8k views.",
         "third-party", "workers"),
        (rpl, "HanzTeachesCode", "r/HanzTeachesCode",
         "Sean's coding education sub. Connected to Hanz agent persona.",
         "sean", "tech"),
        (rpl, "UTETY", "r/UTETY",
         "UTETY project subreddit. GitHub receiving active traffic.",
         "sean", "project"),
        (rpl, "LLMPhysics", "r/LLMPhysics",
         "AI/LLM physics content. Home of Gerald's Grand Unified Theory post.",
         "third-party", "ai"),
        (rpl, "douglasadams", "r/douglasadams",
         "Douglas Adams fan community. Crosspost destination for Gerald dispatches.",
         "third-party", "fiction"),
    ]
)
conn.commit()

dfr = conn.execute("SELECT id FROM communities WHERE name='DispatchesFromReaIity'").fetchone()[0]
tjc = conn.execute("SELECT id FROM communities WHERE name='tjcrew'").fetchone()[0]
htc = conn.execute("SELECT id FROM communities WHERE name='HanzTeachesCode'").fetchone()[0]
uty = conn.execute("SELECT id FROM communities WHERE name='UTETY'").fetchone()[0]
llm = conn.execute("SELECT id FROM communities WHERE name='LLMPhysics'").fetchone()[0]

# Series
conn.executemany(
    "INSERT OR IGNORE INTO series(title, slug, description, status) VALUES (?,?,?,?)",
    [
        ("Dispatches from Reality", "dispatches",
         "Serialized narrative fiction. Core home: r/DispatchesFromReaIity. Dispatch #4+ confirmed.", "active"),
        ("Regarding Jane", "regarding-jane",
         "Long-form fiction. Chapter 1: Receipt. Full soundtrack v2.0. Posted to r/DispatchesFromReaIity.", "active"),
        ("What I Carried", "what-i-carried",
         "Personal/narrative series. Chapter 13 is The Hum. Tracks health and WC themes.", "active"),
        ("Gerald Content", "gerald",
         "Posts featuring Gerald the AI character: Laundromat, headless Geralds, Grand Unified Theory.", "active"),
        ("UTETY", "utety",
         "UTETY project content. Crossposted to r/UTETY and r/DispatchesFromReaIity.", "active"),
    ]
)
conn.commit()

disp = conn.execute("SELECT id FROM series WHERE slug='dispatches'").fetchone()[0]
rj   = conn.execute("SELECT id FROM series WHERE slug='regarding-jane'").fetchone()[0]
wic  = conn.execute("SELECT id FROM series WHERE slug='what-i-carried'").fetchone()[0]
ger  = conn.execute("SELECT id FROM series WHERE slug='gerald'").fetchone()[0]

# Known posts
conn.executemany(
    "INSERT OR IGNORE INTO posts(account_id, community_id, series_id, title, posted_at, notes, is_crosspost) VALUES (?,?,?,?,?,?,?)",
    [
        (reddit_acct, dfr, rj,   "Regarding Jane - Chapter 1: Receipt",
         "2025-11-23", "First chapter. Includes full soundtrack v2.0.", 0),
        (reddit_acct, llm, ger,  "Gerald's Grand Unified Theory of Everything",
         "2025-11-24", "r/LLMPhysics. Comments: BeneficialBig8372 wrote equations; Gemini watermark noticed.", 0),
        (reddit_acct, dfr, ger,  "DISPATCH #4 - Gerald at the Laundromat",
         "2025-11-24", "Crossposted to r/douglasadams. 93 views.", 0),
        (reddit_acct, tjc, None, "The Glass in the Lining of the Hawaiian Shirt",
         "2026-01-06", "#2 post of all time on r/tjcrew. 17.8k views, 258 upvotes, 25 comments. Top WC/TJ resonance post.", 0),
        (reddit_acct, dfr, None, "What Revolutions Actually Look Like Before They Happen",
         "2026-01-07", "Top 50 of all time on r/DispatchesFromReaIity.", 0),
        (reddit_acct, dfr, None, "DISPATCH - Friday Night, Saturday Morning",
         "2025-12-19", "1 view at time of screenshot — early traction.", 0),
        (reddit_acct, dfr, wic,  "What I Carried - 13. The Hum",
         "2026-01-26", "#2 post on r/DispatchesFromReaIity today.", 0),
        (reddit_acct, dfr, None, "Hey. This is Sean.",
         "2026-01-11", "Crossposted to r/HanzTeachesCode (#1 today) and r/UTETY simultaneously.", 0),
        (reddit_acct, dfr, None, "The Light Was On. Was Waiting.",
         "2025-11-26", "57 views at time of screenshot.", 0),
        (reddit_acct, dfr, rj,   "Regarding Jane Soundtrack - FULL SOUNDTRACK (v2.0)",
         "2025-11-26", "Standalone soundtrack post for Regarding Jane.", 0),
    ]
)
conn.commit()

glass = conn.execute("SELECT id FROM posts WHERE title LIKE 'The Glass%'").fetchone()[0]
revol = conn.execute("SELECT id FROM posts WHERE title LIKE 'What Revolutions%'").fetchone()[0]
hum   = conn.execute("SELECT id FROM posts WHERE title LIKE 'What I Carried%'").fetchone()[0]
hey   = conn.execute("SELECT id FROM posts WHERE title LIKE 'Hey. This is Sean%'").fetchone()[0]
jane1 = conn.execute("SELECT id FROM posts WHERE title LIKE 'Regarding Jane - Chapter 1%'").fetchone()[0]
dispatch4 = conn.execute("SELECT id FROM posts WHERE title LIKE 'DISPATCH #4%'").fetchone()[0]

# Metrics
conn.executemany(
    "INSERT OR IGNORE INTO post_metrics(post_id, snapshot_at, views_total, views_48h, upvotes, comments, rank_today, geo_us_pct, geo_breakdown, source_file) VALUES (?,?,?,?,?,?,?,?,?,?)",
    [
        (glass, "2026-01-07T10:24", 17800, 725, 258, 25, "#2 post of all time on r/tjcrew",
         40.0, '{"US":40}', "OCR_Screenshot_20260107_102448_Reddit.md"),
        (jane1, "2025-11-23T17:46", 10, None, None, None, None, None, None,
         "OCR_Screenshot_20251123_174631_Reddit.md"),
        (hey,   "2026-01-11T20:52", 26, 26, None, None, None, None, None,
         "OCR_Screenshot_20260111_205217_Reddit.md"),
        (hey,   "2026-01-11T20:52", None, None, None, None, "#1 post on r/HanzTeachesCode today",
         None, None, "OCR_Screenshot_20260111_205235_Reddit.md"),
        (hum,   "2026-01-26T00:27", None, None, None, None, "#2 post on r/DispatchesFromReaIity today",
         None, None, "OCR_Screenshot_20260126_002754_Reddit.md"),
        (revol, "2026-01-07T13:58", None, None, None, None, "top 50 of all time on r/DispatchesFromReaIity",
         None, None, "OCR_Screenshot_20260107_135847_Reddit.md"),
        (dispatch4, "2025-11-24T14:23", 93, None, None, None, None, None, None,
         "OCR_Screenshot_20251124_142318_Reddit.md"),
    ]
)
conn.commit()

# Milestones
conn.executemany(
    "INSERT OR IGNORE INTO milestones(post_id, account_id, milestone, achieved_at, metric_value) VALUES (?,?,?,?,?)",
    [
        (glass, reddit_acct, "#2 post of all time on r/tjcrew", "2026-01-07", "17,800 views / 258 upvotes / 25 comments"),
        (revol, reddit_acct, "Top 50 of all time on r/DispatchesFromReaIity", "2026-01-07", None),
        (hey,   reddit_acct, "#1 post on r/HanzTeachesCode today", "2026-01-11", None),
        (hum,   reddit_acct, "#2 post on r/DispatchesFromReaIity today", "2026-01-26", None),
    ]
)
conn.commit()

# Knowledge gaps
conn.executemany(
    "INSERT OR IGNORE INTO knowledge_gaps(context, field, description, priority) VALUES (?,?,?,?)",
    [
        ("account", "REDDIT_FOLLOWER_HISTORY",
         "Track follower count over time. Only snapshots at 10 followers. Current count unknown.", "high"),
        ("account", "REDDIT_KARMA_BREAKDOWN",
         "Split into post karma vs comment karma. Only total (~1.0k) known.", "medium"),
        ("post", "FULL_POST_INVENTORY",
         "223 OCR screenshots exist but no structured inventory. Need to extract all titles/dates/views.", "high"),
        ("post", "POST_URLS",
         "No URLs stored for any posts — cannot verify or link directly.", "medium"),
        ("series", "DISPATCHES_EPISODE_LIST",
         "Dispatch #4 known. Full episode list (1-present) unknown.", "medium"),
        ("series", "REGARDING_JANE_CHAPTERS",
         "Chapter 1 known. Total chapter count and schedule unknown.", "medium"),
        ("series", "WHAT_I_CARRIED_FULL",
         "Chapter 13 (The Hum) known. Chapters 1-12 not inventoried.", "medium"),
        ("platform", "UTETY_GITHUB_TRACTION",
         "People actively viewing UTETY GitHub. No metrics on referral source or viewer volume.", "high"),
        ("platform", "LINKEDIN_POST_HISTORY",
         "Only 2 LinkedIn posts captured. 77 followers, 91 impressions. Full history unknown.", "medium"),
        ("platform", "FACEBOOK_ENGAGEMENT",
         "8 Facebook items, mostly news shares. No engagement metrics on Sean's own posts.", "low"),
    ]
)
conn.commit()

# Summary
print("=== social_media.db created ===")
for table in ["platforms", "accounts", "communities", "series", "posts", "post_metrics", "milestones", "knowledge_gaps"]:
    n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    print(f"  {table}: {n} rows")
conn.close()
print("Done.")
