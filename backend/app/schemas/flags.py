"""Flag and targeting schemas, with the validation the backend enforces on every save."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from featureflags.evaluation import OPERATORS

FlagKind = Literal["boolean", "string", "number", "json"]
Scalar = str | int | float | bool
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")
MAX_TARGETS = 10_000
MAX_RULES = 200
TOTAL_WEIGHT = 100_000


class Clause(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attribute: str = Field(min_length=1, max_length=100)
    op: str
    values: list[Scalar] = Field(min_length=1, max_length=1000)
    negate: bool = False

    @field_validator("op")
    @classmethod
    def known_op(cls, v: str) -> str:
        # The engine ignores unknown ops for forward-compatibility; the API must not accept them.
        if v not in OPERATORS:
            raise ValueError(f"unknown operator {v!r}; expected one of {sorted(OPERATORS)}")
        return v


class WeightedVariation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variation: int = Field(ge=0)
    weight: int = Field(ge=0, le=TOTAL_WEIGHT)


class Rollout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["rollout", "experiment"] = "rollout"
    bucket_by: str | None = None
    variations: list[WeightedVariation] = Field(min_length=1)

    @model_validator(mode="after")
    def weights(self) -> Rollout:
        total = sum(v.weight for v in self.variations)
        if total != TOTAL_WEIGHT:
            raise ValueError(f"rollout weights must sum to {TOTAL_WEIGHT} (100%), got {total}")
        indexes = [v.variation for v in self.variations]
        if len(indexes) != len(set(indexes)):
            raise ValueError("each variation may appear only once in a rollout")
        return self


class Serve(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variation: int | None = Field(default=None, ge=0)
    rollout: Rollout | None = None

    @model_validator(mode="after")
    def exactly_one(self) -> Serve:
        if (self.variation is None) == (self.rollout is None):
            raise ValueError("serve must have exactly one of 'variation' or 'rollout'")
        return self

    def indexes(self) -> list[int]:
        if self.variation is not None:
            return [self.variation]
        assert self.rollout is not None
        return [v.variation for v in self.rollout.variations]

    def wire(self) -> dict:
        return self.model_dump(exclude_none=True)


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = Field(default=None, max_length=100)
    description: str = Field(default="", max_length=500)
    clauses: list[Clause] = Field(min_length=1, max_length=50)
    serve: Serve


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variation: int = Field(ge=0)
    values: list[str] = Field(max_length=MAX_TARGETS)


class FlagConfigIn(BaseModel):
    """The per-environment targeting a user edits in the dashboard."""

    model_config = ConfigDict(extra="forbid")
    on: bool
    off_variation: int | None = Field(default=None, ge=0)
    targets: list[Target] = Field(default_factory=list)
    rules: list[Rule] = Field(default_factory=list, max_length=MAX_RULES)
    fallthrough: Serve

    def semantic_errors(self, n_variations: int) -> list[str]:
        """Checks that need the flag's variations. Returns human-readable problems."""
        errors: list[str] = []

        def check(idx: int | None, where: str) -> None:
            if idx is not None and not 0 <= idx < n_variations:
                errors.append(f"{where}: variation {idx} does not exist (flag has {n_variations})")

        check(self.off_variation, "off_variation")
        for i in self.fallthrough.indexes():
            check(i, "fallthrough")
        seen_users: dict[str, int] = {}
        for t in self.targets:
            check(t.variation, "targets")
            for user_id in t.values:
                if user_id in seen_users and seen_users[user_id] != t.variation:
                    errors.append(f"targets: user {user_id!r} is targeted to two variations")
                seen_users[user_id] = t.variation
        rule_ids: set[str] = set()
        for n, rule in enumerate(self.rules):
            for i in rule.serve.indexes():
                check(i, f"rules[{n}]")
            if rule.id:
                if rule.id in rule_ids:
                    errors.append(f"rules[{n}]: duplicate rule id {rule.id!r}")
                rule_ids.add(rule.id)
        return errors

    def normalized(self) -> dict[str, Any]:
        """Storage/wire form: rule ids filled in, targets merged per variation, serves compact."""
        targets: dict[int, list[str]] = {}
        for t in self.targets:
            bucket = targets.setdefault(t.variation, [])
            bucket.extend(v for v in t.values if v not in bucket)
        return {
            "on": self.on,
            "off_variation": self.off_variation,
            "targets": [{"variation": v, "values": vals} for v, vals in sorted(targets.items())],
            "rules": [
                {
                    "id": r.id or uuid.uuid4().hex[:8],
                    "description": r.description,
                    "clauses": [c.model_dump() for c in r.clauses],
                    "serve": r.serve.wire(),
                }
                for r in self.rules
            ],
            "fallthrough": self.fallthrough.wire(),
        }


def _variation_matches_kind(kind: str, v: Any) -> bool:
    if kind == "boolean":
        return isinstance(v, bool)
    if kind == "string":
        return isinstance(v, str)
    if kind == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return True


class FlagCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    kind: FlagKind = "boolean"
    variations: list[Any] | None = None
    client_side: bool = False

    @field_validator("key")
    @classmethod
    def key_format(cls, v: str) -> str:
        if not KEY_RE.match(v):
            raise ValueError("key must be lowercase letters, digits, '.', '_' or '-' (max 100)")
        return v

    @model_validator(mode="after")
    def check_variations(self) -> FlagCreate:
        if self.kind == "boolean":
            if self.variations not in (None, [True, False]):
                raise ValueError("boolean flags always have variations [true, false]")
            self.variations = [True, False]
            return self
        if not self.variations or len(self.variations) < 2:
            raise ValueError("non-boolean flags need at least two variations")
        if len(self.variations) > 20:
            raise ValueError("at most 20 variations")
        bad = [v for v in self.variations if not _variation_matches_kind(self.kind, v)]
        if bad:
            raise ValueError(f"variations {bad!r} are not of kind {self.kind}")
        if self.kind != "json" and len(set(map(repr, self.variations))) != len(self.variations):
            raise ValueError("variations must be unique")
        return self


class FlagUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    client_side: bool | None = None


class FlagConfigOut(BaseModel):
    environment_key: str
    on: bool
    off_variation: int | None
    targets: list[dict]
    rules: list[dict]
    fallthrough: dict
    version: int
    updated_at: datetime | None = None


class FlagOut(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    description: str
    kind: str
    variations: list[Any]
    client_side: bool
    archived: bool
    created_at: datetime
    environments: dict[str, FlagConfigOut] = Field(default_factory=dict)


class EvaluateIn(BaseModel):
    user: dict[str, Any]
