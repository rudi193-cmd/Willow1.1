#!/usr/bin/env python3
import argparse
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Optional

import git
from git import Repo, GitCommandError

# Constants
DEFAULT_INTERVAL = 300  # 5 minutes in seconds
LOG_FILE = Path(__file__).parent.parent / "core" / "safe_sync.log"
SAFE_REPO_DEFAULT = Path(__file__).parent.parent.parent / "SAFE"  # ../SAFE relative to Willow

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class SafeSyncDaemon:
    def __init__(self, safe_path: Path, interval: int):
        self.safe_path = safe_path
        self.interval = interval
        self.running = False
        self.last_sync_time = 0
        self.repo: Optional[Repo] = None

    def initialize_repo(self) -> None:
        """Initialize the git repository."""
        try:
            self.repo = Repo(self.safe_path)
            logger.info(f"Initialized SAFE repo at {self.safe_path}")
        except git.InvalidGitRepositoryError:
            logger.error(f"Invalid git repository at {self.safe_path}")
            raise
        except Exception as e:
            logger.error(f"Error initializing repo: {e}")
            raise

    def query_new_continuity_entries(self) -> list:
        """Query knowledge database for new continuity entries since last sync."""
        # Placeholder for actual database query logic
        logger.info("Querying for new continuity entries...")
        # Simulate some entries
        return [
            {"id": 1, "conversation": "Sample conversation 1", "handoff": "Handoff details 1"},
            {"id": 2, "conversation": "Sample conversation 2", "handoff": "Handoff details 2"}
        ]

    def format_as_markdown(self, entries: list) -> str:
        """Format continuity entries as markdown."""
        markdown = ""
        for entry in entries:
            markdown += f"## Entry {entry['id']}\n\n"
            markdown += f"**Conversation:** {entry['conversation']}\n\n"
            markdown += f"**Handoff:** {entry['handoff']}\n\n"
            markdown += "---\n\n"
        return markdown

    def append_to_safe_repo(self, markdown_content: str) -> None:
        """Append formatted markdown to SAFE repo files."""
        continuity_file = self.safe_path / "continuity.md"
        try:
            with open(continuity_file, "a") as f:
                f.write(markdown_content)
            logger.info(f"Appended {len(markdown_content.split('---'))} entries to {continuity_file}")
        except IOError as e:
            logger.error(f"Error writing to continuity file: {e}")
            raise

    def git_commit_changes(self) -> str:
        """Commit changes to the SAFE repo."""
        try:
            repo = self.repo
            repo.git.add(A=True)
            commit_message = f"Sync continuity entries at {time.strftime('%Y-%m-%d %H:%M:%S')}"
            commit = repo.index.commit(commit_message)
            logger.info(f"Committed changes with hash: {commit.hexsha}")
            return commit.hexsha
        except GitCommandError as e:
            logger.error(f"Git operation failed: {e}")
            raise

    def sync(self) -> None:
        """Perform a full sync cycle."""
        try:
            if self.repo is None:
                self.initialize_repo()
            entries = self.query_new_continuity_entries()
            if not entries:
                logger.info("No new entries to sync")
                return

            markdown_content = self.format_as_markdown(entries)
            self.append_to_safe_repo(markdown_content)
            commit_hash = self.git_commit_changes()
            logger.info(f"Sync completed. Entries: {len(entries)}, Commit: {commit_hash}")
            self.last_sync_time = time.time()
        except Exception as e:
            logger.error(f"Sync failed: {e}")

    def run(self) -> None:
        """Run the daemon."""
        self.running = True
        logger.info(f"Starting SAFE sync daemon (interval: {self.interval}s)")

        try:
            while self.running:
                self.sync()
                time.sleep(self.interval)
        except KeyboardInterrupt:
            logger.info("Shutting down gracefully...")
        finally:
            self.running = False
            logger.info("Daemon stopped")

def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="SAFE Continuity Sync Daemon")
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL,
        help=f"Sync interval in seconds (default: {DEFAULT_INTERVAL})"
    )
    parser.add_argument(
        "--safe-path",
        type=Path,
        default=SAFE_REPO_DEFAULT,
        help=f"Path to SAFE repository (default: {SAFE_REPO_DEFAULT})"
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run as a daemon"
    )
    return parser.parse_args()

def main():
    args = parse_args()
    daemon = SafeSyncDaemon(args.safe_path, args.interval)

    if args.daemon:
        daemon.run()
    else:
        # Single run mode
        daemon.sync()

if __name__ == "__main__":
    main()
