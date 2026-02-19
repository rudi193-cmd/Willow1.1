import sys
import sqlite3
import argparse
from pathlib import Path

REGISTRY_PATH = Path("C:/Users/Sean/Documents/GitHub/die-namic-system/bridge_ring")
WILLOW_ROOT = Path("C:/Users/Sean/Documents/GitHub/Willow")

sys.path.insert(0, str(REGISTRY_PATH))

from instance_registry import register_instance


def create_user_dirs(username: str) -> None:
    user_artifacts = WILLOW_ROOT / "artifacts" / username
    (user_artifacts / "pending").mkdir(parents=True, exist_ok=True)
    (user_artifacts / "processed").mkdir(parents=True, exist_ok=True)


def init_user_knowledge_db(username: str) -> None:
    db_path = WILLOW_ROOT / "artifacts" / username / "knowledge.db"
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS atoms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL, source TEXT, created TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS entities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, type TEXT, created TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS gaps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question TEXT NOT NULL, created TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit()
    conn.close()


def create_instructions_file(username: str, display_name: str, trust_level: int) -> None:
    trust_names = {0: "OBSERVER", 1: "WORKER", 2: "OPERATOR", 3: "ENGINEER", 4: "ARCHITECT"}
    trust_name = trust_names.get(trust_level, "WORKER")
    path = WILLOW_ROOT / "artifacts" / username / "CLAUDE_PROJECT_INSTRUCTIONS.txt"
    path.write_text(f"""# Willow User Project Instructions
Username: {username}
Display Name: {display_name}
Trust Level: {trust_level} ({trust_name})
Data: artifacts/{username}/
Pending: artifacts/{username}/pending/
Processed: artifacts/{username}/processed/
Knowledge: artifacts/{username}/knowledge.db
""", encoding="utf-8")


def register_user(username: str, display_name: str, trust_level: int = 1) -> None:
    create_user_dirs(username)
    init_user_knowledge_db(username)
    create_instructions_file(username, display_name, trust_level)
    register_instance(
        instance_id=username, name=display_name,
        instance_type="user", trust_level=trust_level,
        escalates_to="human-chief", metadata={"admin": trust_level >= 4}
    )
    print(f"Registered: {username} ({display_name}) trust={trust_level}")


def main():
    parser = argparse.ArgumentParser(description="Register a Willow user")
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--trust-level", type=int, default=1, choices=[0,1,2,3,4])
    args = parser.parse_args()
    register_user(args.username, args.display_name, args.trust_level)


if __name__ == "__main__":
    main()
