import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any


def _resolve_db_path() -> Path:
    """Resolve DB path in priority order: env var → project-root/data/ → cwd/data/.

    Honours ``MASE_DB_PATH`` so users can repoint storage anywhere
    (e.g. ``~/.mase/memory.db`` or a tmpfs in CI). Falls back to a path
    derived from this file's location, which works on every OS and any
    clone directory — no more hard-coded ``E:\\MASE-demo``.
    """
    env = os.environ.get("MASE_DB_PATH")
    if env:
        return Path(env).expanduser().resolve()
    # mase_tools/memory/db_core.py -> project root is parents[2]
    project_root = Path(__file__).resolve().parents[2]
    return project_root / "data" / "mase_memory.db"


DB_PATH = _resolve_db_path()

# Track which db files we've already migrated this process so that the
# `get_connection()` hot path doesn't re-run DDL on every call. This is the
# unified entry point that replaces the old module-level `init_db()` side-effect
# (which fired at import time and made every test suite touch real disk).
_SCHEMA_READY: set[str] = set()


def _ensure_schema(db_path: Path) -> None:
    key = str(db_path)
    if key in _SCHEMA_READY:
        return
    # 1) legacy baseline (entity_state, fts triggers, supersede columns, …)
    _create_legacy_schema(db_path)
    # 2) forward migrations on top (schema_version-tracked evolutions)
    try:
        from src.mase.schema_migrations import migrate as _migrate  # noqa: PLC0415
    except ImportError:
        try:
            from mase.schema_migrations import migrate as _migrate  # noqa: PLC0415
        except ImportError:
            _migrate = None
    if _migrate is not None:
        try:
            _migrate(db_path)
        except sqlite3.OperationalError as exc:
            # Real DDL failure: log and re-raise. Silent skip would let the
            # process run on a half-migrated schema and explode later in
            # business code with cryptic SQL errors. Loud failure here is
            # ten times cheaper to debug than ghost SQL errors downstream.
            import logging
            logging.getLogger("mase.memory").error(
                "schema_migration_failed db_path=%s err=%s", db_path, exc,
            )
            raise
        except ImportError:
            # Import-time failure of the migrations module is a packaging bug;
            # tolerate so that bare `import db_core` still works in stripped envs.
            pass
    _SCHEMA_READY.add(key)

# 预定义的 Profile 模板（实体维度约束），防模型乱造属性名
PROFILE_TEMPLATES = [
    "user_preferences",  # 用户喜好、厌恶、习惯
    "people_relations",  # 人物、职业、亲属关系
    "project_status",    # 项目代号、进度、配置
    "finance_budget",    # 预算、花销、金额记录
    "location_events",   # 去过的地方、居住地、活动地点
    "general_facts"      # 兜底事实
]

def get_connection() -> sqlite3.Connection:
    # Honour the module-level DB_PATH (so tests can monkeypatch it), but
    # always re-check the env var first in case it was set after import.
    env = os.environ.get("MASE_DB_PATH")
    db_path = Path(env).expanduser().resolve() if env else DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_schema(db_path)
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    # Concurrency safety: WAL lets readers run alongside one writer, busy_timeout
    # eliminates the SQLITE_BUSY storm when the async GC agent and the main
    # notetaker race. synchronous=NORMAL is the standard WAL pairing.
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
    except sqlite3.DatabaseError:
        # Some older SQLite builds reject WAL on network filesystems; fall back silently.
        pass
    return conn

def init_db():
    """Backwards-compat entry point. Real work happens in `_create_legacy_schema`,
    invoked lazily by `get_connection` -> `_ensure_schema`. Tests and examples that
    still call `init_db()` directly remain supported."""
    env = os.environ.get("MASE_DB_PATH")
    db_path = Path(env).expanduser().resolve() if env else DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _create_legacy_schema(db_path)
    _SCHEMA_READY.add(str(db_path))


def _create_legacy_schema(db_path: Path) -> None:
    """Create the MASE 2.0 white-box memory schema on a fresh DB (idempotent)."""
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    try:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
        except sqlite3.DatabaseError:
            pass
        cursor = conn.cursor()
        
        # 1. 创建流水账表 (Append Only)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT,
                role TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 2. 创建基于 FTS5 的虚拟全文检索表
        # 使用 unicode61 tokenize 分词
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                content,
                tokenize='unicode61'
            )
        """)
        
        # 3. 创建实体状态表 (Upsert)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS entity_state (
                category TEXT,
                entity_key TEXT,
                entity_value TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (category, entity_key)
            )
        """)

        # 3.1 fact-supersede 审计历史表 (Mem0-style: 每次 UPDATE 留底)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS entity_state_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                entity_key TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                superseded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                supersede_reason TEXT,
                source_log_id INTEGER
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_eshist_key ON entity_state_history(category, entity_key)"
        )

        # 3.2 memory_log 增加 supersede 标记列 (老库自动迁移)
        cursor.execute("PRAGMA table_info(memory_log)")
        cols = {row[1] for row in cursor.fetchall()}
        if "superseded_at" not in cols:
            cursor.execute("ALTER TABLE memory_log ADD COLUMN superseded_at DATETIME")
        if "superseded_by" not in cols:
            cursor.execute("ALTER TABLE memory_log ADD COLUMN superseded_by INTEGER")
        if "supersede_reason" not in cols:
            cursor.execute("ALTER TABLE memory_log ADD COLUMN supersede_reason TEXT")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_log_superseded ON memory_log(superseded_at)"
        )
        
        # 4. 建立触发器：当 memory_log 有新记录时，自动同步到 FTS 检索表
        # 注意: fts5 中的 rowid 不能显式指定 content_rowid 的列名去 insert，而是可以直接用 rowid
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS memory_log_ai AFTER INSERT ON memory_log
            BEGIN
                INSERT INTO memory_fts(rowid, content) VALUES (new.id, new.content);
            END;
        """)
        
        # 建立触发器：删除时同步删除 (可选)
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS memory_log_ad AFTER DELETE ON memory_log
            BEGIN
                DELETE FROM memory_fts WHERE rowid = old.id;
            END;
        """)
        
        conn.commit()
    finally:
        conn.close()

def add_event_log(thread_id: str, role: str, content: str) -> int:
    """写入流水账"""
    with closing(get_connection()) as conn, conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO memory_log (thread_id, role, content) VALUES (?, ?, ?)",
            (thread_id, role, content)
        )
        return cursor.lastrowid

def search_event_log(keywords: list[str], limit: int = 5) -> list[dict[str, Any]]:
    """使用 BM25 算法在流水账中做全文检索"""
    if not keywords:
        return []
    
    # 构建 FTS5 查询语句，例如: '预算 OR 追加'
    # 为了防止 SQL 注入或格式错误，过滤掉双引号
    clean_keywords = [k.replace('"', "").replace("'", "") for k in keywords if k.strip()]
    # 对于中文环境，由于 FTS5 的 unicode61 默认按空格或标点分词，
    # 如果不自己实现自定义分词器，一个简单的 workaround 是用通配符或 LIKE 结合
    # 这里我们使用简单的 match，同时如果没匹配到我们用 like 兜底（或者改成分字插入）
    match_query = " OR ".join(f'"{k}"' for k in clean_keywords)
    
    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        try:
            # 尝试全文检索
            cursor.execute('''
                SELECT m.id, m.thread_id, m.role, m.content, m.timestamp, f.rank as score
                FROM memory_fts f
                JOIN memory_log m ON f.rowid = m.id
                WHERE memory_fts MATCH ? AND m.superseded_at IS NULL
                ORDER BY rank
                LIMIT ?
            ''', (match_query, limit))
            results = [dict(row) for row in cursor.fetchall()]
            
            # 如果 FTS 因为中文分词没搜到，启动白盒机制：Like 兜底查询
            if not results:
                like_conditions = " OR ".join("content LIKE ?" for _ in clean_keywords)
                like_params = tuple(f"%{k}%" for k in clean_keywords)
                cursor.execute(f'''
                    SELECT id, thread_id, role, content, timestamp, 0 as score
                    FROM memory_log
                    WHERE ({like_conditions}) AND superseded_at IS NULL
                    LIMIT ?
                ''', like_params + (limit,))
                results = [dict(row) for row in cursor.fetchall()]
                
            return results
        except sqlite3.OperationalError as e:
            print(f"FTS Search Error: {e}")
            return []

def upsert_entity_fact(category: str, key: str, value: str, *, reason: str | None = None, source_log_id: int | None = None):
    """更新或插入实体状态（对抗时间篡改的核心）。

    更新时把旧值写入 ``entity_state_history``，形成审计链 (Mem0-style)。
    """
    if category not in PROFILE_TEMPLATES:
        category = "general_facts"

    with closing(get_connection()) as conn, conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT entity_value FROM entity_state WHERE category = ? AND entity_key = ?",
            (category, key),
        )
        row = cursor.fetchone()
        old_value = row["entity_value"] if row else None

        # ON CONFLICT(category, entity_key) 依赖于 PRIMARY KEY 约束
        cursor.execute('''
            INSERT INTO entity_state (category, entity_key, entity_value, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(category, entity_key)
            DO UPDATE SET
                entity_value=excluded.entity_value,
                updated_at=CURRENT_TIMESTAMP
        ''', (category, key, value))

        # 仅当值真正变化时记录一条历史
        if old_value is not None and old_value != value:
            cursor.execute(
                """
                INSERT INTO entity_state_history
                    (category, entity_key, old_value, new_value, supersede_reason, source_log_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (category, key, old_value, value, reason or "user_correction", source_log_id),
            )


def get_entity_fact_history(category: str | None = None, entity_key: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """查询事实审计链。无参 → 全表最新若干条；指定 (category, key) → 该字段全部历史。"""
    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        if category and entity_key:
            cursor.execute(
                "SELECT * FROM entity_state_history WHERE category=? AND entity_key=? ORDER BY id DESC",
                (category, entity_key),
            )
        elif category:
            cursor.execute(
                "SELECT * FROM entity_state_history WHERE category=? ORDER BY id DESC LIMIT ?",
                (category, limit),
            )
        else:
            cursor.execute(
                "SELECT * FROM entity_state_history ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        return [dict(row) for row in cursor.fetchall()]


def supersede_log_entries(keywords: list[str], replacement_log_id: int, reason: str = "user_correction") -> int:
    """把所有 FTS 命中 ``keywords`` 的 *未被覆盖* 流水账标记为 superseded。

    用于"我之前说错了" 类型的更正：旧的不删除（保留审计），但默认搜索/事实表不再返回。
    返回标记的行数。
    """
    if not keywords:
        return 0
    clean = [k.replace('"', "").replace("'", "") for k in keywords if k.strip()]
    if not clean:
        return 0
    match_query = " OR ".join(f'"{k}"' for k in clean)

    with closing(get_connection()) as conn, conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                '''
                SELECT m.id FROM memory_fts f
                JOIN memory_log m ON f.rowid = m.id
                WHERE memory_fts MATCH ? AND m.superseded_at IS NULL AND m.id != ?
                ''',
                (match_query, replacement_log_id),
            )
            ids = [row["id"] for row in cursor.fetchall()]
        except sqlite3.OperationalError:
            ids = []

        # FTS miss → LIKE 兜底（中文场景）
        if not ids:
            like_conditions = " OR ".join("content LIKE ?" for _ in clean)
            like_params = tuple(f"%{k}%" for k in clean)
            cursor.execute(
                f'''
                SELECT id FROM memory_log
                WHERE ({like_conditions}) AND superseded_at IS NULL AND id != ?
                ''',
                like_params + (replacement_log_id,),
            )
            ids = [row["id"] for row in cursor.fetchall()]

        if not ids:
            return 0

        placeholders = ",".join("?" * len(ids))
        cursor.execute(
            f"""
            UPDATE memory_log
            SET superseded_at=CURRENT_TIMESTAMP, superseded_by=?, supersede_reason=?
            WHERE id IN ({placeholders})
            """,
            (replacement_log_id, reason, *ids),
        )
        return len(ids)

def get_entity_facts(category: str = None) -> list[dict[str, Any]]:
    """获取最新的实体状态档案"""
    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        if category:
            cursor.execute('SELECT * FROM entity_state WHERE category = ? ORDER BY updated_at DESC', (category,))
        else:
            cursor.execute('SELECT * FROM entity_state ORDER BY category, updated_at DESC')
        return [dict(row) for row in cursor.fetchall()]

# NOTE: schema is created lazily on first `get_connection()` (see `_ensure_schema`).
# We deliberately do NOT call init_db() at import time so that `import db_core`
# is side-effect-free — tests/CLIs that need only a constant or helper no longer
# touch the disk.
