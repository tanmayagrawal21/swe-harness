"""Workflow spec: a tool-agnostic YAML description of roles, gates, the merge rule, whips and rules."""

from __future__ import annotations

import copy
import fnmatch
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROLE_KINDS = {"author", "gate", "observer"}


class SpecError(ValueError):
    pass


@dataclass
class Role:
    name: str
    kind: str
    model: str = ""
    prompt: str = ""  # role prompt text (loaded from the prompt file)
    tools: list[str] = field(default_factory=list)
    approve: str = "APPROVE"  # first-line verdict token meaning "pass"
    block: str = "REQUEST CHANGES"
    scope: list[str] = field(default_factory=list)  # file globs; empty = every PR
    trigger: str = ""  # observers only: after_merge | episode_end

    def in_scope(self, files: list[str]) -> bool:
        if not self.scope:
            return True
        return any(fnmatch.fnmatch(f, pat) for f in files for pat in self.scope)


@dataclass
class SquashMessage:
    subject: str
    body: str


@dataclass
class MergeRule:
    merger: str
    requires: list[str]
    same_sha: bool = True
    ci_green: bool = True
    main_ancestor: bool = True
    squash: SquashMessage | None = None  # None = forge default (concatenated commit messages)


@dataclass
class Whip:
    roles: list[str]
    silent_seconds: float
    max_restarts: int = 2


@dataclass
class Workflow:
    name: str
    description: str
    roles: dict[str, Role]
    gates: list[str]
    merge: MergeRule
    round_cap: int
    whips: list[Whip]
    rules: dict[str, str]
    source: Path | None = None

    @property
    def author(self) -> Role:
        return next(r for r in self.roles.values() if r.kind == "author")

    def whip_for(self, role: str) -> Whip | None:
        return next((w for w in self.whips if role in w.roles), None)

    def observers(self, trigger: str) -> list[Role]:
        return [r for r in self.roles.values() if r.kind == "observer" and r.trigger == trigger]


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)  # lists and scalars replace
    return out


def load_raw(path: Path) -> dict:
    data = yaml.safe_load(path.read_text()) or {}
    for r in (data.get("roles") or {}).values():  # prompt paths are relative to the file declaring them
        if isinstance(r, dict) and r.get("prompt"):
            r["prompt"] = str((path.parent / r["prompt"]).resolve())
    parent = data.pop("extends", None)
    if parent:
        data = _deep_merge(load_raw((path.parent / parent).resolve()), data)
    return data


def load(path: str | Path) -> Workflow:
    path = Path(path).resolve()
    return parse(load_raw(path), base_dir=path.parent, source=path)


def parse(data: dict, base_dir: Path, source: Path | None = None) -> Workflow:
    roles: dict[str, Role] = {}
    for name, r in (data.get("roles") or {}).items():
        kind = r.get("kind")
        if kind not in ROLE_KINDS:
            raise SpecError(f"role {name}: kind must be one of {sorted(ROLE_KINDS)}")
        prompt = ""
        if r.get("prompt"):
            prompt = (base_dir / r["prompt"]).read_text()
        verdicts = r.get("verdicts") or {}
        roles[name] = Role(
            name=name, kind=kind, model=r.get("model", ""), prompt=prompt, tools=list(r.get("tools") or []),
            approve=verdicts.get("approve", "APPROVE"), block=verdicts.get("block", "REQUEST CHANGES"),
            scope=list(r.get("scope") or []), trigger=r.get("trigger", ""),
        )
    if sum(r.kind == "author" for r in roles.values()) != 1:
        raise SpecError("exactly one author role is required")

    gates = list(data.get("gates") or [])
    for g in gates:
        if g not in roles or roles[g].kind != "gate":
            raise SpecError(f"gate {g!r} is not a role of kind 'gate'")

    m = data.get("merge") or {}
    sq = m.get("squash_message")
    merge = MergeRule(
        merger=m.get("merger", ""), requires=list(m.get("requires") or []),
        same_sha=bool(m.get("same_sha", True)), ci_green=bool(m.get("ci_green", True)),
        main_ancestor=bool(m.get("main_ancestor", True)),
        squash=SquashMessage(sq["subject"], sq["body"]) if sq else None,
    )
    if merge.merger not in roles:
        raise SpecError(f"merge.merger {merge.merger!r} is not a role")
    for g in merge.requires:
        if g not in gates:
            raise SpecError(f"merge.requires {g!r} is not an active gate")

    whips = [Whip(list(w["roles"]), float(w["silent_seconds"]), int(w.get("max_restarts", 2)))
             for w in data.get("whips") or []]
    round_cap = int(data.get("round_cap", 3))
    if round_cap < 1:
        raise SpecError("round_cap must be >= 1")
    return Workflow(
        name=data.get("name", source.stem if source else "workflow"), description=data.get("description", ""),
        roles=roles, gates=gates, merge=merge, round_cap=round_cap, whips=whips,
        rules=dict(data.get("rules") or {}), source=source,
    )
