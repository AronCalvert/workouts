from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .models import (
    ExercisePlan,
    SessionPerformedLine,
    SetPlan,
    WorkoutPlan,
    WorkoutSummary,
)


class Database:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
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
            "SELECT id, name FROM workouts ORDER BY created_at DESC, id DESC"
        )
        return [
            WorkoutSummary(id=int(r["id"]), name=str(r["name"])) for r in cur.fetchall()
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
                "SELECT id, name, exercise_type, order_index, rest_seconds, timed_seconds"
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
            "SELECT id, workout_id, name, exercise_type, order_index, rest_seconds, timed_seconds"
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
                   ps.reps, ps.weight_kg, ps.duration_seconds
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
            )
            for r in cur.fetchall()
        ]

    # helpers

    @staticmethod
    def _validate_exercise(
        name: str,
        exercise_type: str,
        num_sets: int,
        target_reps: int | None,
        target_weight_kg: float | None,
        timed_seconds: int | None,
    ) -> tuple[str, int | None, float | None, int | None]:
        """Validate and normalise exercise fields. Returns (name, tr, tw, ts)."""
        name = name.strip()
        if not name:
            raise ValueError("Exercise name is required")
        if exercise_type not in ("reps", "timed"):
            raise ValueError("exercise_type must be 'reps' or 'timed'")
        if num_sets < 1 or num_sets > 50:
            raise ValueError("Number of sets must be between 1 and 50")
        if exercise_type == "reps":
            tr = int(target_reps) if target_reps is not None else 10
            if tr < 0 or tr > 999:
                raise ValueError("Target reps must be between 0 and 999")
            tw = target_weight_kg
            if tw is not None and (tw < 0 or tw > 999):
                raise ValueError("Weight must be between 0 and 999 kg")
            return name, tr, tw, None
        else:
            ts = int(timed_seconds) if timed_seconds is not None else 30
            if ts < 1 or ts > 3600:
                raise ValueError("Timed duration must be between 1 and 3600 seconds")
            return name, None, None, ts

    # mutations

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
        num_sets: int,
        target_reps: int | None,
        target_weight_kg: float | None,
    ) -> int:
        name, tr, tw, ts = self._validate_exercise(
            name, exercise_type, num_sets, target_reps, target_weight_kg, timed_seconds
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
            for i in range(num_sets):
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
        num_sets: int,
        target_reps: int | None,
        target_weight_kg: float | None,
    ) -> None:
        if not self._conn.execute(
            "SELECT id FROM exercises WHERE id = ?", (exercise_id,)
        ).fetchone():
            raise ValueError("Exercise not found")
        name, tr, tw, ts = self._validate_exercise(
            name, exercise_type, num_sets, target_reps, target_weight_kg, timed_seconds
        )
        rest_seconds = max(0, min(600, int(rest_seconds)))

        with self._conn:
            self._conn.execute(
                "UPDATE exercises SET name = ?, exercise_type = ?, rest_seconds = ?, timed_seconds = ? WHERE id = ?",
                (name.strip(), exercise_type, rest_seconds, ts, exercise_id),
            )
            self._conn.execute("DELETE FROM sets WHERE exercise_id = ?", (exercise_id,))
            for i in range(num_sets):
                self._insert_set(exercise_id, i, target_reps=tr, target_weight_kg=tw)

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

    def start_session(self, workout_id: int) -> int:
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO workout_sessions(workout_id) VALUES (?)", (workout_id,)
            )
        return int(cur.lastrowid)

    def finish_session(self, session_id: int) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE workout_sessions SET finished_at = datetime('now') WHERE id = ? AND finished_at IS NULL",
                (session_id,),
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
    ) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO performed_sets(
                  session_id, exercise_id, set_id, order_index, reps, weight_kg, duration_seconds, completed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, exercise_id, order_index) DO UPDATE SET
                  set_id = excluded.set_id, reps = excluded.reps, weight_kg = excluded.weight_kg,
                  duration_seconds = excluded.duration_seconds, completed = excluded.completed
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
    try:
        db = Database(default_db_path(app_id))
    except PermissionError:
        db = Database(Path.cwd() / ".data" / "workouts.db")
    db.init_schema()
    return db
