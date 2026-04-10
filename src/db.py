from __future__ import annotations

import datetime
import os
import sqlite3
from pathlib import Path

from .models import (
    ExercisePlan,
    SessionInfo,
    SessionPerformedLine,
    SetPlan,
    WorkoutPlan,
    WorkoutSummary,
)


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Database:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        self._conn.close()

    def init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS workouts (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS exercises (
              id INTEGER PRIMARY KEY,
              workout_id INTEGER NOT NULL,
              name TEXT NOT NULL,
              exercise_type TEXT NOT NULL CHECK (exercise_type IN ('reps', 'timed')),
              order_index INTEGER NOT NULL,
              rest_seconds INTEGER NOT NULL DEFAULT 90,
              timed_seconds INTEGER,
              FOREIGN KEY (workout_id) REFERENCES workouts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sets (
              id INTEGER PRIMARY KEY,
              exercise_id INTEGER NOT NULL,
              order_index INTEGER NOT NULL,
              target_reps INTEGER,
              target_weight_kg REAL,
              FOREIGN KEY (exercise_id) REFERENCES exercises(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS workout_sessions (
              id INTEGER PRIMARY KEY,
              workout_id INTEGER NOT NULL,
              started_at TEXT NOT NULL DEFAULT (datetime('now')),
              finished_at TEXT,
              FOREIGN KEY (workout_id) REFERENCES workouts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS performed_sets (
              id INTEGER PRIMARY KEY,
              session_id INTEGER NOT NULL,
              exercise_id INTEGER NOT NULL,
              set_id INTEGER,
              order_index INTEGER NOT NULL,
              reps INTEGER,
              weight_kg REAL,
              duration_seconds INTEGER,
              completed INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              UNIQUE(session_id, exercise_id, order_index),
              FOREIGN KEY (session_id) REFERENCES workout_sessions(id) ON DELETE CASCADE,
              FOREIGN KEY (exercise_id) REFERENCES exercises(id) ON DELETE CASCADE,
              FOREIGN KEY (set_id) REFERENCES sets(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_exercises_workout_order
              ON exercises(workout_id, order_index);
            CREATE INDEX IF NOT EXISTS idx_sets_exercise_order
              ON sets(exercise_id, order_index);
            CREATE INDEX IF NOT EXISTS idx_sessions_workout_time
              ON workout_sessions(workout_id, started_at);
            """
        )
        self._conn.commit()
        self._migrate()

    def _migrate(self) -> None:
        for stmt in [
            "ALTER TABLE exercises ADD COLUMN superset_group INTEGER DEFAULT NULL",
            "ALTER TABLE performed_sets ADD COLUMN notes TEXT",
        ]:
            try:
                self._conn.execute(stmt)
                self._conn.commit()
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e):
                    raise

    # row mappers

    @staticmethod
    def _row_to_exercise(r: sqlite3.Row) -> ExercisePlan:
        return ExercisePlan(
            id=int(r["id"]),
            name=str(r["name"]),
            exercise_type=str(r["exercise_type"]),
            order_index=int(r["order_index"]),
            rest_seconds=int(r["rest_seconds"]),
            timed_seconds=int(r["timed_seconds"])
            if r["timed_seconds"] is not None
            else None,
            superset_group=int(r["superset_group"])
            if r["superset_group"] is not None
            else None,
        )

    @staticmethod
    def _row_to_set(r: sqlite3.Row) -> SetPlan:
        return SetPlan(
            id=int(r["id"]),
            exercise_id=int(r["exercise_id"]),
            order_index=int(r["order_index"]),
            target_reps=int(r["target_reps"]) if r["target_reps"] is not None else None,
            target_weight_kg=float(r["target_weight_kg"])
            if r["target_weight_kg"] is not None
            else None,
        )

    # queries

    def list_workouts(self) -> list[WorkoutSummary]:
        cur = self._conn.execute(
            """
            SELECT w.id, w.name,
                   COUNT(DISTINCT e.id) AS exercise_count,
                   COUNT(s.id)          AS set_count
            FROM workouts w
            LEFT JOIN exercises e ON e.workout_id = w.id
            LEFT JOIN sets s      ON s.exercise_id = e.id
            GROUP BY w.id
            ORDER BY w.created_at DESC, w.id DESC
            """
        )
        return [
            WorkoutSummary(
                id=int(r["id"]),
                name=str(r["name"]),
                exercise_count=int(r["exercise_count"]),
                set_count=int(r["set_count"]),
            )
            for r in cur.fetchall()
        ]

    def get_workout_plan(self, workout_id: int) -> WorkoutPlan | None:
        w = self._conn.execute(
            "SELECT id, name FROM workouts WHERE id = ?", (workout_id,)
        ).fetchone()
        if w is None:
            return None

        exercises = [
            self._row_to_exercise(r)
            for r in self._conn.execute(
                "SELECT id, name, exercise_type, order_index, rest_seconds, timed_seconds, superset_group"
                " FROM exercises WHERE workout_id = ? ORDER BY order_index ASC",
                (workout_id,),
            ).fetchall()
        ]

        sets_by_exercise_id: dict[int, list[SetPlan]] = {}
        for r in self._conn.execute(
            "SELECT id, exercise_id, order_index, target_reps, target_weight_kg"
            " FROM sets WHERE exercise_id IN (SELECT id FROM exercises WHERE workout_id = ?)"
            " ORDER BY exercise_id ASC, order_index ASC",
            (workout_id,),
        ).fetchall():
            sp = self._row_to_set(r)
            sets_by_exercise_id.setdefault(sp.exercise_id, []).append(sp)

        return WorkoutPlan(
            workout=WorkoutSummary(id=int(w["id"]), name=str(w["name"])),
            exercises=exercises,
            sets_by_exercise_id=sets_by_exercise_id,
        )

    def get_exercise_details(
        self, exercise_id: int
    ) -> tuple[ExercisePlan, list[SetPlan]] | None:
        row = self._conn.execute(
            "SELECT id, workout_id, name, exercise_type, order_index, rest_seconds, timed_seconds, superset_group"
            " FROM exercises WHERE id = ?",
            (exercise_id,),
        ).fetchone()
        if row is None:
            return None

        sets = [
            self._row_to_set(r)
            for r in self._conn.execute(
                "SELECT id, exercise_id, order_index, target_reps, target_weight_kg"
                " FROM sets WHERE exercise_id = ? ORDER BY order_index ASC",
                (exercise_id,),
            ).fetchall()
        ]
        return self._row_to_exercise(row), sets

    def get_session_performed_lines(
        self, session_id: int
    ) -> list[SessionPerformedLine]:
        cur = self._conn.execute(
            """
            SELECT e.name AS exercise_name, e.exercise_type, ps.order_index AS set_ord,
                   ps.reps, ps.weight_kg, ps.duration_seconds, ps.notes
            FROM performed_sets ps
            JOIN exercises e ON e.id = ps.exercise_id
            WHERE ps.session_id = ? AND ps.completed = 1
            ORDER BY e.order_index ASC, ps.order_index ASC
            """,
            (session_id,),
        )
        return [
            SessionPerformedLine(
                exercise_name=str(r["exercise_name"]),
                exercise_type=str(r["exercise_type"]),
                set_number=int(r["set_ord"]) + 1,
                reps=int(r["reps"]) if r["reps"] is not None else None,
                weight_kg=float(r["weight_kg"]) if r["weight_kg"] is not None else None,
                duration_seconds=int(r["duration_seconds"])
                if r["duration_seconds"] is not None
                else None,
                notes=str(r["notes"]) if r["notes"] is not None else None,
            )
            for r in cur.fetchall()
        ]

    # helpers

    @staticmethod
    def _validate_exercise(
        name: str,
        exercise_type: str,
        set_configs: list[tuple[int | None, float | None]],
        timed_seconds: int | None,
    ) -> tuple[str, list[tuple[int | None, float | None]], int | None]:
        """Validate and normalise exercise fields. Returns (name, validated_set_configs, ts)."""
        name = name.strip()
        if not name:
            raise ValueError("Exercise name is required")
        if exercise_type not in ("reps", "timed"):
            raise ValueError("exercise_type must be 'reps' or 'timed'")
        if not (1 <= len(set_configs) <= 50):
            raise ValueError("Number of sets must be between 1 and 50")
        if exercise_type == "reps":
            validated: list[tuple[int | None, float | None]] = []
            for reps, weight in set_configs:
                tr = int(reps) if reps is not None else 10
                if tr < 0 or tr > 999:
                    raise ValueError("Target reps must be between 0 and 999")
                tw = weight
                if tw is not None and (tw < 0 or tw > 999):
                    raise ValueError("Weight must be between 0 and 999 kg")
                validated.append((tr, tw))
            return name, validated, None
        else:
            ts = int(timed_seconds) if timed_seconds is not None else 30
            if ts < 1 or ts > 7200:
                raise ValueError("Timed duration must be between 1 and 7200 seconds")
            return name, [(None, None)] * len(set_configs), ts

    # mutations

    def rename_workout(self, workout_id: int, name: str) -> None:
        name = name.strip()
        if not name:
            raise ValueError("Workout name is required")
        if not self._conn.execute(
            "SELECT id FROM workouts WHERE id = ?", (workout_id,)
        ).fetchone():
            raise ValueError("Workout not found")
        with self._conn:
            self._conn.execute(
                "UPDATE workouts SET name = ? WHERE id = ?", (name, workout_id)
            )

    def duplicate_workout(self, workout_id: int, new_name: str) -> int:
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("Workout name is required")
        plan = self.get_workout_plan(workout_id)
        if plan is None:
            raise ValueError("Workout not found")
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO workouts(name) VALUES (?)", (new_name,)
            )
            new_workout_id = int(cur.lastrowid)

            # Remap old superset group IDs to fresh ones to avoid collisions
            old_groups = sorted(
                {
                    ex.superset_group
                    for ex in plan.exercises
                    if ex.superset_group is not None
                }
            )
            group_id_map: dict[int, int] = {}
            if old_groups:
                max_group = int(
                    self._conn.execute(
                        "SELECT COALESCE(MAX(superset_group), 0) AS m FROM exercises"
                    ).fetchone()["m"]
                )
                for old_gid in old_groups:
                    max_group += 1
                    group_id_map[old_gid] = max_group

            ex_id_map: dict[int, int] = {}
            for ex in plan.exercises:
                new_group = (
                    group_id_map[ex.superset_group]
                    if ex.superset_group is not None
                    else None
                )
                new_ex_cur = self._conn.execute(
                    "INSERT INTO exercises"
                    " (workout_id, name, exercise_type, order_index, rest_seconds, timed_seconds, superset_group)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        new_workout_id,
                        ex.name,
                        ex.exercise_type,
                        ex.order_index,
                        ex.rest_seconds,
                        ex.timed_seconds,
                        new_group,
                    ),
                )
                ex_id_map[ex.id] = int(new_ex_cur.lastrowid)

            for ex in plan.exercises:
                new_ex_id = ex_id_map[ex.id]
                for s in plan.sets_by_exercise_id.get(ex.id, []):
                    self._conn.execute(
                        "INSERT INTO sets(exercise_id, order_index, target_reps, target_weight_kg)"
                        " VALUES (?, ?, ?, ?)",
                        (new_ex_id, s.order_index, s.target_reps, s.target_weight_kg),
                    )
        return new_workout_id

    def create_workout(self, name: str) -> int:
        name = name.strip()
        if not name:
            raise ValueError("Workout name is required")
        with self._conn:
            cur = self._conn.execute("INSERT INTO workouts(name) VALUES (?)", (name,))
        return int(cur.lastrowid)

    def add_exercise_to_workout(
        self,
        workout_id: int,
        *,
        name: str,
        exercise_type: str,
        rest_seconds: int,
        timed_seconds: int | None,
        set_configs: list[tuple[int | None, float | None]],
    ) -> int:
        name, validated_configs, ts = self._validate_exercise(
            name, exercise_type, set_configs, timed_seconds
        )
        rest_seconds = max(0, min(600, int(rest_seconds)))

        order_index = (
            int(
                self._conn.execute(
                    "SELECT COALESCE(MAX(order_index), -1) AS m FROM exercises WHERE workout_id = ?",
                    (workout_id,),
                ).fetchone()["m"]
            )
            + 1
        )

        with self._conn:
            ex_id = self._insert_exercise(
                workout_id,
                name=name,
                exercise_type=exercise_type,
                order_index=order_index,
                rest_seconds=rest_seconds,
                timed_seconds=ts,
            )
            for i, (tr, tw) in enumerate(validated_configs):
                self._insert_set(ex_id, i, target_reps=tr, target_weight_kg=tw)
        return ex_id

    def update_exercise(
        self,
        exercise_id: int,
        *,
        name: str,
        exercise_type: str,
        rest_seconds: int,
        timed_seconds: int | None,
        set_configs: list[tuple[int | None, float | None]],
    ) -> None:
        if not self._conn.execute(
            "SELECT id FROM exercises WHERE id = ?", (exercise_id,)
        ).fetchone():
            raise ValueError("Exercise not found")
        name, validated_configs, ts = self._validate_exercise(
            name, exercise_type, set_configs, timed_seconds
        )
        rest_seconds = max(0, min(600, int(rest_seconds)))

        with self._conn:
            self._conn.execute(
                "UPDATE exercises SET name = ?, exercise_type = ?, rest_seconds = ?, timed_seconds = ? WHERE id = ?",
                (name, exercise_type, rest_seconds, ts, exercise_id),
            )
            self._conn.execute("DELETE FROM sets WHERE exercise_id = ?", (exercise_id,))
            for i, (tr, tw) in enumerate(validated_configs):
                self._insert_set(exercise_id, i, target_reps=tr, target_weight_kg=tw)

    def move_exercise_to_position(
        self, workout_id: int, exercise_id: int, target_index: int
    ) -> None:

        rows = self._conn.execute(
            "SELECT id, superset_group FROM exercises WHERE workout_id = ? ORDER BY order_index ASC",
            (workout_id,),
        ).fetchall()
        ids = [int(r["id"]) for r in rows]
        if exercise_id not in ids:
            raise ValueError("Exercise not found in workout")

        sg_map = {int(r["id"]): r["superset_group"] for r in rows}
        dragged_group = sg_map[exercise_id]
        if dragged_group is not None:
            cluster = [eid for eid in ids if sg_map[eid] == dragged_group]
        else:
            cluster = [exercise_id]

        for eid in cluster:
            ids.remove(eid)
        target_index = max(0, min(target_index, len(ids)))
        for offset, eid in enumerate(cluster):
            ids.insert(target_index + offset, eid)

        with self._conn:
            for i, eid in enumerate(ids):
                self._conn.execute(
                    "UPDATE exercises SET order_index = ? WHERE id = ?", (i, eid)
                )

    def swap_exercise_order(
        self, workout_id: int, exercise_id_a: int, exercise_id_b: int
    ) -> None:
        a = self._conn.execute(
            "SELECT order_index FROM exercises WHERE id = ? AND workout_id = ?",
            (exercise_id_a, workout_id),
        ).fetchone()
        b = self._conn.execute(
            "SELECT order_index FROM exercises WHERE id = ? AND workout_id = ?",
            (exercise_id_b, workout_id),
        ).fetchone()
        if a is None or b is None:
            raise ValueError("Exercise not found in workout")
        with self._conn:
            self._conn.execute(
                "UPDATE exercises SET order_index = ? WHERE id = ?",
                (b["order_index"], exercise_id_a),
            )
            self._conn.execute(
                "UPDATE exercises SET order_index = ? WHERE id = ?",
                (a["order_index"], exercise_id_b),
            )

    def delete_workout(self, workout_id: int) -> None:
        if not self._conn.execute(
            "SELECT id FROM workouts WHERE id = ?", (workout_id,)
        ).fetchone():
            raise ValueError("Workout not found")
        with self._conn:
            self._conn.execute("DELETE FROM workouts WHERE id = ?", (workout_id,))

    def delete_exercise_from_workout(self, workout_id: int, exercise_id: int) -> None:
        if not self._conn.execute(
            "SELECT id FROM exercises WHERE id = ? AND workout_id = ?",
            (exercise_id, workout_id),
        ).fetchone():
            raise ValueError("Exercise not found in this workout")
        with self._conn:
            self._conn.execute("DELETE FROM exercises WHERE id = ?", (exercise_id,))
            # Unlink any exercises whose superset group now has only one member
            self._conn.execute(
                """
                UPDATE exercises SET superset_group = NULL
                WHERE workout_id = ?
                  AND superset_group IS NOT NULL
                  AND superset_group IN (
                    SELECT superset_group FROM exercises
                    WHERE workout_id = ?
                    GROUP BY superset_group
                    HAVING COUNT(*) < 2
                  )
                """,
                (workout_id, workout_id),
            )
            for i, r in enumerate(
                self._conn.execute(
                    "SELECT id FROM exercises WHERE workout_id = ? ORDER BY order_index ASC",
                    (workout_id,),
                ).fetchall()
            ):
                self._conn.execute(
                    "UPDATE exercises SET order_index = ? WHERE id = ?",
                    (i, int(r["id"])),
                )

    def set_exercises_as_superset(
        self, workout_id: int, exercise_ids: list[int]
    ) -> None:
        """Link two or more exercises as a superset group."""
        if len(exercise_ids) < 2:
            raise ValueError("Need at least 2 exercises for a superset")
        for eid in exercise_ids:
            row = self._conn.execute(
                "SELECT superset_group FROM exercises WHERE id = ? AND workout_id = ?",
                (eid, workout_id),
            ).fetchone()
            if row is None:
                raise ValueError("Exercise not found in this workout")
        existing_group: int | None = None
        for eid in exercise_ids:
            row = self._conn.execute(
                "SELECT superset_group FROM exercises WHERE id = ? AND workout_id = ?",
                (eid, workout_id),
            ).fetchone()
            if row["superset_group"] is not None:
                existing_group = int(row["superset_group"])
                break
        if existing_group is None:
            max_group = self._conn.execute(
                "SELECT COALESCE(MAX(superset_group), 0) AS m FROM exercises WHERE workout_id = ?",
                (workout_id,),
            ).fetchone()["m"]
            existing_group = int(max_group) + 1
        placeholders = ",".join("?" * len(exercise_ids))
        with self._conn:
            self._conn.execute(
                f"UPDATE exercises SET superset_group = ? WHERE id IN ({placeholders}) AND workout_id = ?",
                (existing_group, *exercise_ids, workout_id),
            )

    def unlink_exercise_from_superset(self, workout_id: int, exercise_id: int) -> None:
        """Remove an exercise from its superset group, also unlinking any lone partner."""
        with self._conn:
            self._conn.execute(
                "UPDATE exercises SET superset_group = NULL WHERE id = ? AND workout_id = ?",
                (exercise_id, workout_id),
            )
            self._conn.execute(
                """
                UPDATE exercises SET superset_group = NULL
                WHERE workout_id = ?
                  AND superset_group IS NOT NULL
                  AND superset_group IN (
                    SELECT superset_group FROM exercises
                    WHERE workout_id = ?
                    GROUP BY superset_group
                    HAVING COUNT(*) < 2
                  )
                """,
                (workout_id, workout_id),
            )

    def consolidate_superset(self, workout_id: int, exercise_ids: list[int]) -> None:
        """Reorder exercises so all superset members are contiguous, anchored at the
        position of whichever member currently appears first in the workout order."""
        member_set = set(exercise_ids)
        rows = self._conn.execute(
            "SELECT id FROM exercises WHERE workout_id = ? ORDER BY order_index ASC",
            (workout_id,),
        ).fetchall()
        ids = [int(r["id"]) for r in rows]

        members = [eid for eid in ids if eid in member_set]
        others = [eid for eid in ids if eid not in member_set]

        # Find where the first member sits, then adjust for members that precede it
        # (they'll be pulled out of `others`, shifting the insertion point down)
        first_pos = next((i for i, eid in enumerate(ids) if eid in member_set), None)
        if first_pos is None:
            return
        members_before_first = sum(1 for eid in ids[:first_pos] if eid in member_set)
        insert_pos = first_pos - members_before_first

        new_order = others[:insert_pos] + members + others[insert_pos:]
        with self._conn:
            for i, eid in enumerate(new_order):
                self._conn.execute(
                    "UPDATE exercises SET order_index = ? WHERE id = ?", (i, eid)
                )

    def get_sessions_for_month(self, year: int, month: int) -> list[int]:
        """Return day-of-month numbers (1–31) that have at least one finished session."""
        if not (1 <= month <= 12):
            raise ValueError(f"Month must be 1–12, got {month}")
        month_str = f"{year:04d}-{month:02d}"
        cur = self._conn.execute(
            """
            SELECT DISTINCT CAST(strftime('%d', started_at) AS INTEGER) AS day
            FROM workout_sessions
            WHERE started_at LIKE ? AND finished_at IS NOT NULL
            """,
            (f"{month_str}%",),
        )
        return [int(r["day"]) for r in cur.fetchall()]

    def get_sessions_for_date(
        self, year: int, month: int, day: int
    ) -> list[SessionInfo]:
        """Return finished sessions for a specific calendar date, oldest first."""
        if not (1 <= month <= 12):
            raise ValueError(f"Month must be 1–12, got {month}")
        if not (1 <= day <= 31):
            raise ValueError(f"Day must be 1–31, got {day}")
        date_str = f"{year:04d}-{month:02d}-{day:02d}"
        cur = self._conn.execute(
            """
            SELECT ws.id, w.name AS workout_name, ws.started_at
            FROM workout_sessions ws
            JOIN workouts w ON w.id = ws.workout_id
            WHERE ws.started_at LIKE ? AND ws.finished_at IS NOT NULL
            ORDER BY ws.started_at ASC
            """,
            (f"{date_str}%",),
        )
        return [
            SessionInfo(
                session_id=int(r["id"]),
                workout_name=str(r["workout_name"]),
                started_at=str(r["started_at"]),
            )
            for r in cur.fetchall()
        ]

    def start_session(self, workout_id: int) -> int:
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO workout_sessions(workout_id, started_at) VALUES (?, ?)",
                (workout_id, _now()),
            )
        return int(cur.lastrowid)

    def delete_session(self, session_id: int) -> None:
        with self._conn:
            self._conn.execute(
                "DELETE FROM workout_sessions WHERE id = ?", (session_id,)
            )

    def finish_session(self, session_id: int) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE workout_sessions SET finished_at = ? WHERE id = ? AND finished_at IS NULL",
                (_now(), session_id),
            )

    def set_performed_set(
        self,
        *,
        session_id: int,
        exercise_id: int,
        set_id: int | None,
        order_index: int,
        completed: bool,
        reps: int | None,
        weight_kg: float | None,
        duration_seconds: int | None,
        notes: str | None = None,
    ) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO performed_sets(
                  session_id, exercise_id, set_id, order_index, reps, weight_kg,
                  duration_seconds, completed, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, exercise_id, order_index) DO UPDATE SET
                  set_id = excluded.set_id, reps = excluded.reps, weight_kg = excluded.weight_kg,
                  duration_seconds = excluded.duration_seconds, completed = excluded.completed,
                  notes = excluded.notes
                """,
                (
                    session_id,
                    exercise_id,
                    set_id,
                    order_index,
                    reps,
                    weight_kg,
                    duration_seconds,
                    1 if completed else 0,
                    notes,
                ),
            )

    def _insert_exercise(
        self,
        workout_id: int,
        *,
        name: str,
        exercise_type: str,
        order_index: int,
        rest_seconds: int,
        timed_seconds: int | None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO exercises(workout_id, name, exercise_type, order_index, rest_seconds, timed_seconds)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (workout_id, name, exercise_type, order_index, rest_seconds, timed_seconds),
        )
        return int(cur.lastrowid)

    def _insert_set(
        self,
        exercise_id: int,
        order_index: int,
        *,
        target_reps: int | None,
        target_weight_kg: float | None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO sets(exercise_id, order_index, target_reps, target_weight_kg) VALUES (?, ?, ?, ?)",
            (exercise_id, order_index, target_reps, target_weight_kg),
        )
        return int(cur.lastrowid)


def default_db_path(app_id: str) -> Path:
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return base / app_id.replace("/", "_") / "workouts.db"


def open_default_db(app_id: str) -> Database:
    path = default_db_path(app_id)
    try:
        db = Database(path)
    except PermissionError:
        import sys
        fallback = Path.cwd() / ".data" / "workouts.db"
        print(
            f"Warning: cannot open database at {path!r}, "
            f"falling back to {fallback!r}.",
            file=sys.stderr,
        )
        db = Database(fallback)
    db.init_schema()
    return db
