"""Content schema for guided lessons. Mirrors LessonContent in
frontend/components/lessons/types.ts field for field (keep the two in sync).

Authored fixtures (content/*.json) also carry each question's answer key
(`answer`). Keys never reach a student: sanitize_for_student() strips them, and
the student API only ever sends feedback derived from them.

validate_content() checks the structure (unknown block types or fields fail)
and then the cross-references a structural check can't see, collecting every
problem into one ContentError.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class ContentError(Exception):
    """Every problem found in a lesson's content, one message per problem."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


class _InlineMarker:
    """Marks Inline text so the markup check can find every Inline field."""


INLINE = _InlineMarker()

# **bold**, `code`, [[ltr text]]; never HTML.
Inline = Annotated[str, INLINE]
Key = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")]
Label = Annotated[int, Field(ge=0, le=1)]  # 0 = no purchase, 1 = purchase
DepthKind = Literal["limited", "unlimited"]
SectionLabel = Literal["understand", "try", "check"]

MAX_DEPTH = 50
MIN_TRAINING_EXAMPLES = 20
MAX_TRAINING_EXAMPLES = 720


class _Model(BaseModel):
    # Strict: the JSON types must match the TypeScript ones (no "3" for 3).
    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="before")
    @classmethod
    def _optional_means_omitted(cls, data: Any) -> Any:
        # A TypeScript `field?: T` may be left out but is never null. Fields
        # that may be null (`T | null`) are required here, so every field with
        # a None default is one of the former.
        if isinstance(data, dict):
            for name, field in cls.model_fields.items():
                if name in data and data[name] is None and not field.is_required() and field.default is None:
                    raise ValueError(f"'{name}' may be left out but not null")
        return data


# ---------------------------------------------------------------------------
# Content (types.ts: Content)
# ---------------------------------------------------------------------------


class TreeNode(_Model):
    id: int
    is_leaf: bool
    feature: str | None
    threshold: float | None  # go left when value <= threshold
    left: int | None
    right: int | None
    prediction: Label
    training_examples: Annotated[int, Field(ge=0)] | None = None
    class_counts: Annotated[list[Annotated[int, Field(ge=0)]], Field(min_length=2, max_length=2)] | None = None


class ManualCustomer(_Model):
    id: Key
    label: Inline
    visits_30d: float
    days_since_purchase: float


class TableColumn(_Model):
    label: Inline
    ltr: bool | None = None


class SplitPoint(_Model):
    value: float
    label: Label


class TreeExample(_Model):
    visits_30d: float
    days_since_purchase: float


class SuggestedRun(_Model):
    depth_kind: DepthKind
    depth: int | None
    training_examples: int
    note: Inline


class TextBlock(_Model):
    type: Literal["text"]
    body: list[Inline]


class SectionBlock(_Model):
    type: Literal["section"]
    label: SectionLabel
    title: Inline | None = None
    blocks: list[Block]


class CalloutBlock(_Model):
    type: Literal["callout"]
    tone: Literal["info", "warn", "note"]
    title: Inline | None = None
    body: list[Inline]


class ExpanderBlock(_Model):
    type: Literal["expander"]
    title: Inline
    blocks: list[Block]


class ListBlock(_Model):
    type: Literal["list"]
    ordered: bool | None = None
    items: list[Inline]


class TableBlock(_Model):
    type: Literal["table"]
    caption: Inline | None = None
    columns: list[TableColumn]
    rows: list[list[Inline]]


class CodeBlock(_Model):
    type: Literal["code"]
    caption: Inline | None = None
    code: str
    highlight_lines: list[int] | None = None


class DownloadBlock(_Model):
    type: Literal["download"]
    asset: str
    label: Inline
    description: Inline | None = None


class PromptBlock(_Model):
    type: Literal["prompt"]
    title: Inline
    text: str
    note: Inline | None = None


class ColabBlock(_Model):
    type: Literal["colab"]
    notebook_asset: str
    section: Inline | None = None
    instructions: list[Inline]
    return_note: Inline


class LinkBlock(_Model):
    type: Literal["link"]
    target: Literal["peer_review", "lesson_list"]
    label: Inline
    description: Inline | None = None


class ManualTreeBlock(_Model):
    type: Literal["manual_tree"]
    caption: Inline | None = None
    feature_labels: dict[str, Inline]
    root: int
    nodes: list[TreeNode]
    customers: list[ManualCustomer]


class SplitIllustrationBlock(_Model):
    type: Literal["split_illustration"]
    caption: Inline | None = None
    feature_label: Inline
    points: list[SplitPoint]
    candidate_thresholds: list[float]


class ActualTreeBlock(_Model):
    type: Literal["actual_tree"]
    asset: str  # the exported model JSON (decision-tree-actual.json)
    caption: Inline | None = None
    examples: list[TreeExample]


class QuestionBlock(_Model):
    type: Literal["question"]
    question: str


class ExperimentLogBlock(_Model):
    type: Literal["experiment_log"]
    min_complete: int
    suggested_runs: list[SuggestedRun]


class CommitmentBlock(_Model):
    type: Literal["commitment"]


class SummaryBlock(_Model):
    type: Literal["summary"]


class AckBlock(_Model):
    type: Literal["ack"]
    key: Key
    label: Inline
    description: Inline | None = None


Block = Annotated[
    Union[
        TextBlock,
        SectionBlock,
        CalloutBlock,
        ExpanderBlock,
        ListBlock,
        TableBlock,
        CodeBlock,
        DownloadBlock,
        PromptBlock,
        ColabBlock,
        LinkBlock,
        ManualTreeBlock,
        SplitIllustrationBlock,
        ActualTreeBlock,
        QuestionBlock,
        ExperimentLogBlock,
        CommitmentBlock,
        SummaryBlock,
        AckBlock,
    ],
    Field(discriminator="type"),
]

SectionBlock.model_rebuild()
ExpanderBlock.model_rebuild()


class AnsweredRule(_Model):
    type: Literal["answered"]
    question: str


class AckRule(_Model):
    type: Literal["ack"]
    key: str


class ExperimentsRule(_Model):
    type: Literal["experiments"]
    min_complete: int


class CommitmentRule(_Model):
    type: Literal["commitment"]


CompletionRule = Annotated[
    Union[AnsweredRule, AckRule, ExperimentsRule, CommitmentRule], Field(discriminator="type")
]


class LessonStep(_Model):
    key: Key
    letter: Annotated[str, Field(min_length=1, max_length=4)]  # A..G, or a short marker for the optional extension
    title: Inline
    goal: Inline  # the guiding question of the step
    optional: bool | None = None  # optional steps never count toward required progress
    blocks: list[Block]
    completion: list[CompletionRule]
    next_hint: Inline | None = None


class ChoiceOption(_Model):
    id: Key
    text: Inline


class ChoiceAnswerKey(_Model):
    correct: list[str]
    feedback: dict[str, Inline]  # per option
    misconceptions: dict[str, Annotated[str, Field(min_length=1, max_length=120)]]  # per wrong option
    explanation: Inline


class FreeTextAnswerKey(_Model):
    sample_reasoning: list[Inline]
    rubric: list[Inline]


class SingleChoiceQuestion(_Model):
    key: Key
    step: str
    mode: Literal["practice", "check"]
    prompt: Inline
    context: Inline | None = None
    type: Literal["single_choice"]
    options: Annotated[list[ChoiceOption], Field(min_length=2)]
    explain: Literal["none", "optional", "required"] | None = None
    explain_prompt: Inline | None = None
    answer: ChoiceAnswerKey  # stripped before anything reaches a student


class FreeTextQuestion(_Model):
    key: Key
    step: str
    mode: Literal["practice", "check"]
    prompt: Inline
    context: Inline | None = None
    type: Literal["free_text"]
    min_chars: Annotated[int, Field(ge=1, le=5000)] | None = None
    placeholder: Inline | None = None
    answer: FreeTextAnswerKey  # stripped before anything reaches a student


Question = Annotated[Union[SingleChoiceQuestion, FreeTextQuestion], Field(discriminator="type")]


class Asset(_Model):
    path: Annotated[str, Field(pattern=r"^/[A-Za-z0-9._/-]+$", max_length=500)]
    filename: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]+$", max_length=200)]
    mime: Annotated[str, Field(min_length=3, max_length=100)]
    label: Inline
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class LessonContent(_Model):
    schema_version: Literal[1]
    slug: Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=64)]
    title: Annotated[str, Field(min_length=1, max_length=255)]
    guiding_question: Inline
    course_code: Annotated[str, Field(min_length=1, max_length=64)]
    date: str | None = None
    intro: Inline | None = None
    assets: dict[str, Asset]
    steps: Annotated[list[LessonStep], Field(min_length=1)]
    questions: dict[str, Question]


# ---------------------------------------------------------------------------
# Requests (types.ts: Requests)
# ---------------------------------------------------------------------------


class _Request(BaseModel):
    # Numbers must be JSON numbers (strict: no "3", no true); ranges and
    # field-level messages are checked by the service.
    model_config = ConfigDict(extra="forbid")


StrictNumber = Annotated[float, Field(strict=True)]
StrictCount = Annotated[int, Field(strict=True, ge=0)]


class Answer(_Request):
    choice: str | None = Field(default=None, max_length=64)
    text: str | None = Field(default=None, max_length=20000)


class ProgressPatch(_Request):
    expected_revision: StrictCount  # 0 before the first save
    current_step_key: str | None = Field(default=None, max_length=64)
    viewed_add: list[str] = Field(default_factory=list, max_length=100)
    acks_add: list[str] = Field(default_factory=list, max_length=100)
    acks_remove: list[str] = Field(default_factory=list, max_length=100)
    drafts: dict[str, str | None] = Field(default_factory=dict)  # null deletes the draft


class AttemptInput(_Request):
    request_id: str = Field(max_length=64)
    question_key: str = Field(max_length=64)
    answer: Answer


class RevealInput(_Request):
    request_id: str = Field(max_length=64)


class ExperimentInput(_Request):
    expected_revision: StrictCount | None = None  # null to create
    depth_kind: str | None = Field(default=None, max_length=16)
    depth: StrictNumber | None = None  # limited: 1..50; unlimited: null (Colab's 0)
    training_examples: StrictNumber | None = None
    train_accuracy_pct: StrictNumber | None = None  # 0..100
    validation_accuracy_pct: StrictNumber | None = None
    baseline_validation_pct: StrictNumber | None = None
    hypothesis: str = Field(default="", max_length=20000)
    observation: str = Field(default="", max_length=20000)
    explanation: str = Field(default="", max_length=20000)


class CommitmentInput(_Request):
    request_id: str = Field(max_length=64)
    run_uuid: str | None = Field(default=None, max_length=64)
    depth_kind: str | None = Field(default=None, max_length=16)
    depth: StrictNumber | None = None
    training_examples: StrictNumber | None = None
    justification: str = Field(default="", max_length=20000)


class FinalInput(_Request):
    final_accuracy_pct: StrictNumber | None = None  # required; checked with the others
    final_precision_pct: StrictNumber | None = None
    final_recall_pct: StrictNumber | None = None
    final_note: str = Field(default="", max_length=20000)


# ---------------------------------------------------------------------------
# Hashing, parsing, sanitizing
# ---------------------------------------------------------------------------


def canonical_json(obj: Any) -> str:
    if isinstance(obj, BaseModel):
        obj = obj.model_dump(mode="json", exclude_unset=True)
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def canonical_hash(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def question_hash(question: Any) -> str:
    """Identifies the exact question a student answered, answer key included."""
    return canonical_hash(question)


def parse_content_json(text: str) -> dict:
    """json.loads that refuses duplicate object keys (json.loads keeps the last
    one silently, which would hide a duplicated question or asset)."""
    duplicates: list[str] = []

    def _pairs(pairs: list[tuple[str, Any]]) -> dict:
        seen: dict[str, Any] = {}
        for key, value in pairs:
            if key in seen:
                duplicates.append(key)
            seen[key] = value
        return seen

    try:
        data = json.loads(text, object_pairs_hook=_pairs)
    except json.JSONDecodeError as exc:
        raise ContentError([f"not valid JSON: {exc}"]) from exc
    if duplicates:
        raise ContentError([f"duplicate JSON key '{k}'" for k in dict.fromkeys(duplicates)])
    if not isinstance(data, dict):
        raise ContentError(["the lesson must be a JSON object"])
    return data


def _strip_answers(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_answers(v) for k, v in value.items() if k != "answer"}
    if isinstance(value, list):
        return [_strip_answers(v) for v in value]
    return value


def sanitize_for_student(content: LessonContent | dict) -> dict:
    """The content with every answer key removed (a new dict)."""
    if isinstance(content, BaseModel):
        content = content.model_dump(mode="json", exclude_unset=True)
    return _strip_answers(copy.deepcopy(content))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _loc(parts: tuple) -> str:
    out = ""
    for part in parts:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out or "(lesson)"


def _markup_problem(text: str) -> str | None:
    """Unbalanced **bold**, `code` or [[ltr]] markup, if any. Code spans are
    taken first; ** and [[ ]] inside them are literal."""
    if text.count("`") % 2:
        return "unbalanced ` (code)"
    outside = re.sub(r"`[^`]*`", "", text)
    if outside.count("**") % 2:
        return "unbalanced ** (bold)"
    depth = 0
    for token in re.findall(r"\[\[|\]\]", outside):
        if token == "[[":
            if depth:
                return "nested [[ (ltr)"
            depth = 1
        else:
            if not depth:
                return "]] without [["
            depth = 0
    return "unclosed [[ (ltr)" if depth else None


def _matches(value: Any, annotation: Any) -> bool:
    """Whether value is an instance of this union member."""
    while get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]
    if get_origin(annotation) in (Union, types.UnionType):
        return any(_matches(value, a) for a in get_args(annotation))
    base = get_origin(annotation) or annotation
    return isinstance(base, type) and isinstance(value, base)


def _inline_texts(value: Any, annotation: Any, path: str, out: list[tuple[str, str]]) -> None:
    """Collect (path, text) for every Inline string inside a validated model."""
    if value is None:
        return
    if isinstance(value, BaseModel):
        for name, field in type(value).model_fields.items():
            sub = getattr(value, name)
            sub_path = f"{path}.{name}" if path else name
            if any(m is INLINE for m in field.metadata):
                if isinstance(sub, str):
                    out.append((sub_path, sub))
                continue
            _inline_texts(sub, field.annotation, sub_path, out)
        return
    origin = get_origin(annotation)
    if origin is Annotated:
        base, *meta = get_args(annotation)
        if any(m is INLINE for m in meta):
            if isinstance(value, str):
                out.append((path, value))
            return
        _inline_texts(value, base, path, out)
    elif origin in (Union, types.UnionType):
        arg = next((a for a in get_args(annotation) if _matches(value, a)), None)
        if arg is not None:
            _inline_texts(value, arg, path, out)
    elif origin is list and isinstance(value, list):
        (item_type,) = get_args(annotation)
        for i, item in enumerate(value):
            _inline_texts(item, item_type, f"{path}[{i}]", out)
    elif origin is dict and isinstance(value, dict):
        _, item_type = get_args(annotation)
        for k, item in value.items():
            _inline_texts(item, item_type, f"{path}.{k}", out)


def iter_blocks(blocks: list, path: str = "") -> Iterator[tuple[Any, str]]:
    """Every block, nested ones included, with a readable path."""
    for i, block in enumerate(blocks):
        here = f"{path}.blocks[{i}]"
        yield block, here
        nested = getattr(block, "blocks", None) if not isinstance(block, dict) else block.get("blocks")
        if nested:
            yield from iter_blocks(nested, here)


def _check_tree(where: str, root: int, nodes: list[TreeNode], features: set[str] | None, errors: list[str]) -> None:
    by_id: dict[int, TreeNode] = {}
    for node in nodes:
        if node.id in by_id:
            errors.append(f"{where}: duplicate node id {node.id}")
        by_id[node.id] = node
    if root not in by_id:
        errors.append(f"{where}: root {root} is not a node")
        return
    for node in nodes:
        if node.is_leaf:
            if node.left is not None or node.right is not None:
                errors.append(f"{where}: leaf {node.id} has children")
            continue
        if node.feature is None or node.threshold is None:
            errors.append(f"{where}: node {node.id} needs a feature and a threshold")
        elif features is not None and node.feature not in features:
            errors.append(f"{where}: node {node.id} uses feature '{node.feature}' with no label")
        for side in ("left", "right"):
            child = getattr(node, side)
            if child is None or child not in by_id:
                errors.append(f"{where}: node {node.id} {side} child {child} does not exist")
    # Every node reachable from the root exactly once (a tree, no cycles).
    seen: set[int] = set()
    stack = [root]
    while stack:
        node_id = stack.pop()
        if node_id in seen:
            errors.append(f"{where}: node {node_id} is reached twice (not a tree)")
            return
        seen.add(node_id)
        node = by_id.get(node_id)
        if node is not None and not node.is_leaf:
            stack.extend(c for c in (node.left, node.right) if c is not None and c in by_id)
    unreachable = sorted(set(by_id) - seen)
    if unreachable:
        errors.append(f"{where}: nodes {unreachable} are not reachable from the root")


def _asset_file(assets_root: Path, asset: Asset) -> Path | None:
    if ".." in asset.path.split("/"):
        return None
    return assets_root / asset.path.lstrip("/")


def _check_assets(content: LessonContent, assets_root: Path, errors: list[str]) -> None:
    for key, asset in content.assets.items():
        path = _asset_file(assets_root, asset)
        if path is None:
            errors.append(f"assets.{key}: path must not contain '..'")
            continue
        if not path.is_file():
            errors.append(f"assets.{key}: file {asset.path} is missing")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != asset.sha256:
            errors.append(f"assets.{key}: sha256 of {asset.path} is {digest}, not {asset.sha256}")


def _check_actual_tree(where: str, content: LessonContent, block: ActualTreeBlock, assets_root: Path, errors: list[str]) -> None:
    asset = content.assets.get(block.asset)
    path = _asset_file(assets_root, asset) if asset else None
    if path is None or not path.is_file():
        return  # reported with the assets
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        nodes = [TreeNode.model_validate(n) for n in data["nodes"]]
        root = data["root"]
    except (ValueError, KeyError, TypeError, ValidationError) as exc:
        errors.append(f"{where}: {asset.path} is not a tree export ({type(exc).__name__})")
        return
    labels = data.get("feature_labels_he")
    _check_tree(f"{where} ({asset.path})", root, nodes, set(labels) if isinstance(labels, dict) else None, errors)


def _semantic_errors(content: LessonContent, assets_root: Path | None) -> list[str]:
    errors: list[str] = []
    steps = content.steps
    step_keys = [s.key for s in steps]
    step_index = {k: i for i, k in enumerate(step_keys)}

    for key in dict.fromkeys(k for k in step_keys if step_keys.count(k) > 1):
        errors.append(f"steps: duplicate step key '{key}'")
    letters = [s.letter for s in steps]
    for letter in dict.fromkeys(x for x in letters if letters.count(x) > 1):
        errors.append(f"steps: duplicate step letter '{letter}'")

    seen_optional = None
    for step in steps:
        if step.optional:
            seen_optional = seen_optional or step.key
        elif seen_optional:
            errors.append(f"steps.{step.key}: required step comes after optional step '{seen_optional}'")
    if all(s.optional for s in steps):
        errors.append("steps: the lesson needs at least one required step")

    # Questions: key matches, step exists, answer key consistent with options.
    for qkey, q in content.questions.items():
        where = f"questions.{qkey}"
        if q.key != qkey:
            errors.append(f"{where}: key '{q.key}' does not match its entry '{qkey}'")
        if q.step not in step_index:
            errors.append(f"{where}: step '{q.step}' does not exist")
        if isinstance(q, SingleChoiceQuestion):
            ids = [o.id for o in q.options]
            for dup in dict.fromkeys(i for i in ids if ids.count(i) > 1):
                errors.append(f"{where}: duplicate option id '{dup}'")
            key = q.answer
            if not key.correct:
                errors.append(f"{where}: answer.correct is empty")
            for c in key.correct:
                if c not in ids:
                    errors.append(f"{where}: answer.correct '{c}' is not an option")
            if set(key.correct) >= set(ids):
                errors.append(f"{where}: every option is marked correct")
            for option_id in ids:
                if option_id not in key.feedback:
                    errors.append(f"{where}: answer.feedback missing for option '{option_id}'")
            for option_id in key.feedback:
                if option_id not in ids:
                    errors.append(f"{where}: answer.feedback for unknown option '{option_id}'")
            wrong = set(ids) - set(key.correct)
            for option_id in key.misconceptions:
                if option_id not in wrong:
                    errors.append(f"{where}: answer.misconceptions '{option_id}' is not a wrong option")
            if q.explain_prompt is not None and q.explain in (None, "none"):
                errors.append(f"{where}: explain_prompt without explain")

    # Blocks: question references, acks, assets, trees, per step.
    referenced: dict[str, str] = {}
    ack_steps: dict[str, str] = {}
    step_blocks: dict[str, set[str]] = {}
    for step in steps:
        types_here: set[str] = set()
        for block, where in iter_blocks(step.blocks, f"steps.{step.key}"):
            types_here.add(block.type)
            if isinstance(block, QuestionBlock):
                q = content.questions.get(block.question)
                if q is None:
                    errors.append(f"{where}: unknown question '{block.question}'")
                elif block.question in referenced:
                    errors.append(f"{where}: question '{block.question}' is shown more than once")
                elif q.step != step.key:
                    errors.append(f"{where}: question '{block.question}' belongs to step '{q.step}'")
                referenced.setdefault(block.question, step.key)
            elif isinstance(block, AckBlock):
                if block.key in ack_steps:
                    errors.append(f"{where}: ack key '{block.key}' is declared more than once")
                ack_steps.setdefault(block.key, step.key)
            elif isinstance(block, (DownloadBlock, ActualTreeBlock)):
                if block.asset not in content.assets:
                    errors.append(f"{where}: unknown asset '{block.asset}'")
                elif isinstance(block, ActualTreeBlock) and assets_root is not None:
                    _check_actual_tree(where, content, block, assets_root, errors)
            elif isinstance(block, ColabBlock):
                if block.notebook_asset not in content.assets:
                    errors.append(f"{where}: unknown asset '{block.notebook_asset}'")
            elif isinstance(block, ManualTreeBlock):
                _check_tree(where, block.root, block.nodes, set(block.feature_labels), errors)
                ids = [c.id for c in block.customers]
                for dup in dict.fromkeys(i for i in ids if ids.count(i) > 1):
                    errors.append(f"{where}: duplicate customer id '{dup}'")
            elif isinstance(block, TableBlock):
                for r, row in enumerate(block.rows):
                    if len(row) != len(block.columns):
                        errors.append(f"{where}: row {r} has {len(row)} cells for {len(block.columns)} columns")
            elif isinstance(block, CodeBlock):
                lines = block.code.count("\n") + 1
                for n in block.highlight_lines or []:
                    if not 1 <= n <= lines:
                        errors.append(f"{where}: highlight line {n} is outside the code (1–{lines})")
            elif isinstance(block, ExperimentLogBlock):
                if block.min_complete < 1:
                    errors.append(f"{where}: min_complete must be at least 1")
                for r, run in enumerate(block.suggested_runs):
                    problem = settings_problem(run.depth_kind, run.depth, run.training_examples)
                    if problem:
                        errors.append(f"{where}.suggested_runs[{r}]: {problem}")
        step_blocks[step.key] = types_here

    for qkey in content.questions:
        if qkey not in referenced:
            errors.append(f"questions.{qkey}: not shown by any question block")

    # Completion rules.
    for step in steps:
        where = f"steps.{step.key}.completion"
        if not step.completion:
            errors.append(f"{where}: the step has no completion rules")
        for rule in step.completion:
            if isinstance(rule, AnsweredRule):
                q = content.questions.get(rule.question)
                if q is None:
                    errors.append(f"{where}: unknown question '{rule.question}'")
                elif q.step != step.key:
                    errors.append(f"{where}: question '{rule.question}' belongs to step '{q.step}'")
            elif isinstance(rule, AckRule):
                if ack_steps.get(rule.key) != step.key:
                    errors.append(f"{where}: ack '{rule.key}' is not declared by an ack block in this step")
            elif isinstance(rule, ExperimentsRule):
                if rule.min_complete < 1:
                    errors.append(f"{where}: experiments.min_complete must be at least 1")
                if "experiment_log" not in step_blocks.get(step.key, set()):
                    errors.append(f"{where}: experiments rule without an experiment_log block in this step")
            elif isinstance(rule, CommitmentRule):
                if "commitment" not in step_blocks.get(step.key, set()):
                    errors.append(f"{where}: commitment rule without a commitment block in this step")

    # Inline markup.
    texts: list[tuple[str, str]] = []
    _inline_texts(content, LessonContent, "", texts)
    for path, text in texts:
        problem = _markup_problem(text)
        if problem:
            errors.append(f"{path}: {problem}")

    if assets_root is not None:
        _check_assets(content, assets_root, errors)
    return errors


def settings_problem(depth_kind: str | None, depth: Any, training_examples: Any) -> str | None:
    """Why a run's settings are impossible (English, for authors), or None."""
    if depth_kind == "limited":
        if not isinstance(depth, int) or isinstance(depth, bool) or not 1 <= depth <= MAX_DEPTH:
            return f"a limited depth must be a whole number 1–{MAX_DEPTH} (0 in Colab means unlimited)"
    elif depth_kind == "unlimited":
        if depth is not None:
            return "an unlimited depth has no number"
    if training_examples is not None and (
        not isinstance(training_examples, int)
        or isinstance(training_examples, bool)
        or not MIN_TRAINING_EXAMPLES <= training_examples <= MAX_TRAINING_EXAMPLES
    ):
        return f"training_examples must be a whole number {MIN_TRAINING_EXAMPLES}–{MAX_TRAINING_EXAMPLES}"
    return None


def validate_content(raw: dict, assets_root: Path | None = None) -> LessonContent:
    """The validated content, or ContentError listing every problem. With
    assets_root, asset files must exist under it with the declared sha256."""
    try:
        content = LessonContent.model_validate(raw)
    except ValidationError as exc:
        raise ContentError([f"{_loc(e['loc'])}: {e['msg']}" for e in exc.errors()]) from None
    errors = _semantic_errors(content, assets_root)
    if errors:
        raise ContentError(errors)
    return content
