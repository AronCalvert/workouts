from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ExerciseType = Literal["reps", "timed"]


@dataclass(frozen=True, slots=True)
class WorkoutSummary:
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class ExercisePlan:
    id: int
    name: str
    exercise_type: ExerciseType
    order_index: int
    rest_seconds: int
    timed_seconds: int | None


@dataclass(frozen=True, slots=True)
class SetPlan:
    id: int
    exercise_id: int
    order_index: int
    target_reps: int | None
    target_weight_kg: float | None


@dataclass(frozen=True, slots=True)
class WorkoutPlan:
    workout: WorkoutSummary
    exercises: list[ExercisePlan]
    sets_by_exercise_id: dict[int, list[SetPlan]]


@dataclass(frozen=True, slots=True)
class SessionPerformedLine:
    """One logged set row for session summary."""

    exercise_name: str
    exercise_type: ExerciseType
    set_number: int
    reps: int | None
    weight_kg: float | None
    duration_seconds: int | None
