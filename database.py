import os
import json
import aiosqlite
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.path.join(os.getenv("DATA_DIR", "."), "birthdays.db")

class DatabaseManager:
    @staticmethod
    async def get_connection() -> aiosqlite.Connection:
        """Establish and return an asynchronous SQLite database connection."""
        conn = await aiosqlite.connect(DB_PATH)
        # Enable foreign key support
        await conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    @classmethod
    async def initialize(cls):
        """Create all database tables asynchronously if they do not exist."""
        print(f"[Database] Initializing database at: {os.path.abspath(DB_PATH)}")
        async with await cls.get_connection() as conn:
            # 1. Birthdays table (preserved schema)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS birthdays (
                    user_id INTEGER,
                    username TEXT,
                    birthday TEXT,
                    PRIMARY KEY (user_id, username)
                );
            """)

            # 2. Connection Chart table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS connections (
                    user1_id INTEGER,
                    user2_id INTEGER,
                    connection TEXT,
                    PRIMARY KEY (user1_id, user2_id, connection)
                );
            """)

            # 3. Workout Tracker Goals table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS workout_goals (
                    user_id INTEGER PRIMARY KEY,
                    goal INTEGER NOT NULL
                );
            """)

            # 4. Workout Tracker History table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS workout_history (
                    user_id INTEGER,
                    timestamp TEXT,
                    PRIMARY KEY (user_id, timestamp)
                );
            """)

            # 5. Workout Tracker Pending Warnings table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_workout_warnings (
                    user_id INTEGER PRIMARY KEY,
                    message_id INTEGER NOT NULL,
                    timestamp TEXT NOT NULL
                );
            """)

            # 6. Server Wrapped Metrics table (Lightweight aggregated tracking)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS server_wrapped_metrics (
                    guild_id INTEGER,
                    user_id INTEGER,
                    year INTEGER,
                    message_count INTEGER DEFAULT 0,
                    word_count INTEGER DEFAULT 0,
                    active_hours TEXT, -- Stored as a JSON array string representing 24 hourly buckets
                    reaction_count INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id, year)
                );
            """)

            # 7. Wordle Stats Cache Table (To avoid crawling channel history repeatedly)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS wordle_stats_cache (
                    message_id INTEGER PRIMARY KEY,
                    user_id INTEGER,
                    timestamp TEXT,
                    score TEXT, -- 1-6 or X
                    group_streak INTEGER
                );
            """)

            await conn.commit()
        print("[Database] All tables initialized successfully.")

    @classmethod
    async def run_migrations(cls):
        """Run safe data migrations from legacy JSON files into SQLite tables."""
        data_dir = os.getenv("DATA_DIR", ".")
        conn_chart_path = os.path.join(data_dir, "connection_chart.json")
        workout_data_path = os.path.join(data_dir, "workout_data.json")

        # 1. Migrate connection chart data
        if os.path.exists(conn_chart_path):
            print(f"[Database] Legacy connection_chart.json found. Migrating data...")
            try:
                with open(conn_chart_path, "r", encoding="utf-8") as f:
                    connections = json.load(f)
                
                async with await cls.get_connection() as conn:
                    migrated_count = 0
                    for conn_data in connections:
                        u1 = conn_data.get("user1")
                        u2 = conn_data.get("user2")
                        ctype = conn_data.get("connection")
                        if u1 is not None and u2 is not None and ctype is not None:
                            await conn.execute(
                                "INSERT OR IGNORE INTO connections (user1_id, user2_id, connection) VALUES (?, ?, ?);",
                                (int(u1), int(u2), str(ctype).lower().strip())
                            )
                            migrated_count += 1
                    await conn.commit()
                
                # Backup legacy file
                backup_path = conn_chart_path + ".bak"
                os.rename(conn_chart_path, backup_path)
                print(f"[Database] Successfully migrated {migrated_count} connections to SQLite. Backed up to {backup_path}")
            except Exception as e:
                print(f"[Database] Error migrating connection chart: {e}")

        # 2. Migrate workout tracker data
        if os.path.exists(workout_data_path):
            print(f"[Database] Legacy workout_data.json found. Migrating data...")
            try:
                with open(workout_data_path, "r", encoding="utf-8") as f:
                    workout_data = json.load(f)
                
                goals = workout_data.get("user_goals", {})
                workouts = workout_data.get("user_workouts", {})
                pending_warnings = workout_data.get("pending_reactions", {})

                async with await cls.get_connection() as conn:
                    # Migrate Goals
                    goals_count = 0
                    for uid_str, goal_val in goals.items():
                        # Unpack list values if they exist, else use int
                        goal_int = goal_val[0] if isinstance(goal_val, list) else goal_val
                        await conn.execute(
                            "INSERT OR REPLACE INTO workout_goals (user_id, goal) VALUES (?, ?);",
                            (int(uid_str), int(goal_int))
                        )
                        goals_count += 1

                    # Migrate Workout logs
                    workouts_count = 0
                    for uid_str, ts_list in workouts.items():
                        uid = int(uid_str)
                        for ts in ts_list:
                            await conn.execute(
                                "INSERT OR IGNORE INTO workout_history (user_id, timestamp) VALUES (?, ?);",
                                (uid, ts)
                            )
                            workouts_count += 1

                    # Migrate Pending warnings
                    warnings_count = 0
                    for uid_str, warning_data in pending_warnings.items():
                        msg_id = warning_data.get("message_id")
                        ts = warning_data.get("timestamp")
                        if msg_id and ts:
                            await conn.execute(
                                "INSERT OR REPLACE INTO pending_workout_warnings (user_id, message_id, timestamp) VALUES (?, ?, ?);",
                                (int(uid_str), int(msg_id), str(ts))
                            )
                            warnings_count += 1
                    
                    await conn.commit()
                
                # Backup legacy file
                backup_path = workout_data_path + ".bak"
                os.rename(workout_data_path, backup_path)
                print(f"[Database] Successfully migrated workouts ({goals_count} goals, {workouts_count} logs, {warnings_count} warnings) to SQLite. Backed up to {backup_path}")
            except Exception as e:
                print(f"[Database] Error migrating workout tracker: {e}")
