"""
Tags filtering utilities for retrieval.

Provides SQL building functions for filtering memories by tags.
Supports four matching modes via TagsMatch enum:
- "any": OR matching, includes untagged memories (default, backward compatible)
- "all": AND matching, includes untagged memories
- "any_strict": OR matching, excludes untagged memories
- "all_strict": AND matching, excludes untagged memories

OR matching (any/any_strict): Memory matches if ANY of its tags overlap with request tags
AND matching (all/all_strict): Memory matches if ALL request tags are present in its tags

This module also exposes a compound boolean filter (`TagGroup` and friends)
that lets callers express arbitrary AND/OR/NOT predicates over leaf
`TagsMatch` clauses. Top-level groups are AND-ed together to mirror the
ergonomics of the legacy `tags` field while adding full boolean expressivity.
"""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

TagsMatch = Literal["any", "all", "any_strict", "all_strict"]


def _parse_tags_match(match: TagsMatch) -> tuple[str, bool]:
    """
    Parse TagsMatch into operator and include_untagged flag.

    Returns:
        Tuple of (operator, include_untagged)
        - operator: "&&" for any/any_strict, "@>" for all/all_strict
        - include_untagged: True for any/all, False for any_strict/all_strict
    """
    if match == "any":
        return "&&", True
    elif match == "all":
        return "@>", True
    elif match == "any_strict":
        return "&&", False
    elif match == "all_strict":
        return "@>", False
    else:
        # Default to "any" behavior
        return "&&", True


def build_tags_where_clause(
    tags: list[str] | None,
    param_offset: int = 1,
    table_alias: str = "",
    match: TagsMatch = "any",
) -> tuple[str, list, int]:
    """
    Build a SQL WHERE clause for filtering by tags.

    Supports four matching modes:
    - "any" (default): OR matching, includes untagged memories
    - "all": AND matching, includes untagged memories
    - "any_strict": OR matching, excludes untagged memories
    - "all_strict": AND matching, excludes untagged memories

    Args:
        tags: List of tags to filter by. If None or empty, returns empty clause (no filtering).
        param_offset: Starting parameter number for SQL placeholders (default 1).
        table_alias: Optional table alias prefix (e.g., "mu." for "memory_units mu").
        match: Matching mode. Defaults to "any".

    Returns:
        Tuple of (sql_clause, params, next_param_offset):
        - sql_clause: SQL WHERE clause string
        - params: List of parameter values to bind
        - next_param_offset: Next available parameter number

    Example:
        >>> clause, params, next_offset = build_tags_where_clause(['user_a'], 3, 'mu.', 'any_strict')
        >>> print(clause)  # "AND mu.tags IS NOT NULL AND mu.tags != '{}' AND mu.tags && $3"
    """
    if not tags:
        return "", [], param_offset

    column = f"{table_alias}tags" if table_alias else "tags"
    operator, include_untagged = _parse_tags_match(match)

    if include_untagged:
        # Include untagged memories (NULL or empty array) OR matching tags
        clause = f"AND ({column} IS NULL OR {column} = '{{}}' OR {column} {operator} ${param_offset})"
    else:
        # Strict: only memories with matching tags (exclude NULL and empty)
        clause = f"AND {column} IS NOT NULL AND {column} != '{{}}' AND {column} {operator} ${param_offset}"

    return clause, [tags], param_offset + 1


def build_tags_where_clause_simple(
    tags: list[str] | None,
    param_num: int,
    table_alias: str = "",
    match: TagsMatch = "any",
) -> str:
    """
    Build a simple SQL WHERE clause for tags filtering.

    This is a convenience version that returns just the clause string,
    assuming the caller will add the tags array to their params list.

    Args:
        tags: List of tags to filter by. If None or empty, returns empty string.
        param_num: Parameter number to use in the clause.
        table_alias: Optional table alias prefix.
        match: Matching mode. Defaults to "any".

    Returns:
        SQL clause string or empty string.
    """
    if not tags:
        return ""

    column = f"{table_alias}tags" if table_alias else "tags"
    operator, include_untagged = _parse_tags_match(match)

    if include_untagged:
        # Include untagged memories (NULL or empty array) OR matching tags
        return f"AND ({column} IS NULL OR {column} = '{{}}' OR {column} {operator} ${param_num})"
    else:
        # Strict: only memories with matching tags (exclude NULL and empty)
        return f"AND {column} IS NOT NULL AND {column} != '{{}}' AND {column} {operator} ${param_num}"


def filter_results_by_tags(
    results: list,
    tags: list[str] | None,
    match: TagsMatch = "any",
) -> list:
    """
    Filter retrieval results by tags in Python (for post-processing).

    Used when SQL filtering isn't possible (e.g., graph traversal results).

    Args:
        results: List of RetrievalResult objects with a 'tags' attribute.
        tags: List of tags to filter by. If None or empty, returns all results.
        match: Matching mode. Defaults to "any".

    Returns:
        Filtered list of results.
    """
    if not tags:
        return results

    _, include_untagged = _parse_tags_match(match)
    is_any_match = match in ("any", "any_strict")

    tags_set = set(tags)
    filtered = []

    for result in results:
        result_tags = getattr(result, "tags", None)

        # Check if untagged
        is_untagged = result_tags is None or len(result_tags) == 0

        if is_untagged:
            if include_untagged:
                filtered.append(result)
            # else: skip untagged
        else:
            result_tags_set = set(result_tags)
            if is_any_match:
                # Any overlap
                if result_tags_set & tags_set:
                    filtered.append(result)
            else:
                # All tags must be present
                if tags_set <= result_tags_set:
                    filtered.append(result)

    return filtered


# ---------------------------------------------------------------------------
# Compound boolean tag predicates (`tag_groups`)
# ---------------------------------------------------------------------------


class TagGroupLeaf(BaseModel):
    """A single tag predicate, semantically identical to the flat `tags` field.

    `tags` is a non-empty list of tag strings; `match` controls AND/OR semantics
    and whether untagged memories are included, exactly mirroring the existing
    `TagsMatch` enum.
    """

    model_config = ConfigDict(extra="forbid")

    tags: list[str] = Field(min_length=1)
    match: TagsMatch = "any"


class TagGroupAnd(BaseModel):
    """Logical AND over a list of nested groups."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    and_: list["TagGroup"] = Field(alias="and", min_length=1)


class TagGroupOr(BaseModel):
    """Logical OR over a list of nested groups."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    or_: list["TagGroup"] = Field(alias="or", min_length=1)


class TagGroupNot(BaseModel):
    """Logical NOT around a single nested group."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    not_: "TagGroup" = Field(alias="not")


# Discriminated by structural shape (left-to-right): leaf → and → or → not.
TagGroup = Annotated[
    Union[TagGroupLeaf, TagGroupAnd, TagGroupOr, TagGroupNot],
    Field(union_mode="left_to_right"),
]


TagGroupAnd.model_rebuild()
TagGroupOr.model_rebuild()
TagGroupNot.model_rebuild()


def _build_leaf_clause(
    leaf: TagGroupLeaf,
    param_offset: int,
    table_alias: str = "",
) -> tuple[str, list, int]:
    """Render a leaf predicate using the same SQL shape as `build_tags_where_clause`.

    Returns a parenthesized clause (without a leading `AND `) plus the bound
    params and the next available `$N` index. Compound builders combine these
    pieces with the appropriate boolean connective.
    """
    column = f"{table_alias}tags" if table_alias else "tags"
    operator, include_untagged = _parse_tags_match(leaf.match)

    if include_untagged:
        clause = (
            f"({column} IS NULL OR {column} = '{{}}' OR {column} {operator} ${param_offset})"
        )
    else:
        clause = (
            f"({column} IS NOT NULL AND {column} != '{{}}' AND {column} {operator} ${param_offset})"
        )
    return clause, [list(leaf.tags)], param_offset + 1


def _build_group_clause(
    group: "TagGroup",
    param_offset: int,
    table_alias: str = "",
) -> tuple[str, list, int]:
    """Recursively render any `TagGroup` into `(clause, params, next_offset)`.

    The returned clause is always parenthesized so callers can combine it with
    `AND`, `OR`, or `NOT` without ambiguity.
    """
    if isinstance(group, TagGroupLeaf):
        return _build_leaf_clause(group, param_offset, table_alias)

    if isinstance(group, TagGroupAnd):
        parts: list[str] = []
        params: list = []
        offset = param_offset
        for child in group.and_:
            clause, child_params, offset = _build_group_clause(child, offset, table_alias)
            parts.append(clause)
            params.extend(child_params)
        return "(" + " AND ".join(parts) + ")", params, offset

    if isinstance(group, TagGroupOr):
        parts = []
        params = []
        offset = param_offset
        for child in group.or_:
            clause, child_params, offset = _build_group_clause(child, offset, table_alias)
            parts.append(clause)
            params.extend(child_params)
        return "(" + " OR ".join(parts) + ")", params, offset

    if isinstance(group, TagGroupNot):
        inner, inner_params, next_offset = _build_group_clause(group.not_, param_offset, table_alias)
        return f"(NOT {inner})", inner_params, next_offset

    raise TypeError(f"Unknown TagGroup variant: {type(group).__name__}")


def build_tag_groups_where_clause(
    tag_groups: list["TagGroup"] | None,
    param_offset: int = 1,
    table_alias: str = "",
) -> tuple[str, list, int]:
    """Build a SQL WHERE fragment for compound `tag_groups` filtering.

    Top-level groups are AND-ed together (this matches the mental model of
    "all of these constraints must hold" and lets callers express OR/NOT
    inside individual groups). Returns a clause prefixed with `AND ` so it can
    be appended to existing query builders, exactly like
    `build_tags_where_clause`.

    Args:
        tag_groups: List of compound predicates. None or empty disables filtering.
        param_offset: Starting `$N` index for placeholders.
        table_alias: Optional table alias prefix (e.g. ``"mu."``).

    Returns:
        ``(clause, params, next_offset)``. ``clause`` is empty when there is
        nothing to filter on.
    """
    if not tag_groups:
        return "", [], param_offset

    parts: list[str] = []
    params: list = []
    offset = param_offset
    for group in tag_groups:
        clause, group_params, offset = _build_group_clause(group, offset, table_alias)
        parts.append(clause)
        params.extend(group_params)

    combined = " AND ".join(parts)
    return f"AND ({combined})", params, offset


def _match_leaf(result_tags: list[str] | None, leaf: TagGroupLeaf) -> bool:
    """Evaluate a single leaf predicate against a result's tag list."""
    _, include_untagged = _parse_tags_match(leaf.match)
    is_untagged = result_tags is None or len(result_tags) == 0
    if is_untagged:
        return include_untagged

    result_set = set(result_tags or [])
    leaf_set = set(leaf.tags)
    if leaf.match in ("any", "any_strict"):
        return bool(result_set & leaf_set)
    return leaf_set <= result_set


def _match_group(result_tags: list[str] | None, group: "TagGroup") -> bool:
    """Recursively evaluate a `TagGroup` against a result's tag list."""
    if isinstance(group, TagGroupLeaf):
        return _match_leaf(result_tags, group)
    if isinstance(group, TagGroupAnd):
        return all(_match_group(result_tags, child) for child in group.and_)
    if isinstance(group, TagGroupOr):
        return any(_match_group(result_tags, child) for child in group.or_)
    if isinstance(group, TagGroupNot):
        return not _match_group(result_tags, group.not_)
    raise TypeError(f"Unknown TagGroup variant: {type(group).__name__}")


def filter_results_by_tag_groups(
    results: list,
    tag_groups: list["TagGroup"] | None,
) -> list:
    """In-Python post-filter that mirrors `build_tag_groups_where_clause`.

    Used by retrieval paths (e.g. graph traversal expansion) where SQL-level
    filtering is impractical. Top-level groups are AND-ed; each result must
    satisfy every group to pass.
    """
    if not tag_groups:
        return results

    filtered = []
    for result in results:
        result_tags = getattr(result, "tags", None)
        if all(_match_group(result_tags, group) for group in tag_groups):
            filtered.append(result)
    return filtered


def build_combined_tag_filter(
    tags: list[str] | None,
    tags_match: TagsMatch,
    tag_groups: list["TagGroup"] | None,
    param_offset: int = 1,
    table_alias: str = "",
) -> tuple[str, list, int]:
    """Compose `tags` + `tag_groups` into a single ``AND ...`` SQL fragment.

    Either, both, or neither input may be provided. Empty inputs contribute no
    SQL. The return shape matches `build_tags_where_clause`:
    ``(clause, params, next_offset)``.

    Combined clauses are joined with `AND`, mirroring the recall API's mental
    model that every supplied filter must hold simultaneously. The HTTP layer
    enforces mutual exclusivity between `tags` and `tag_groups`, so in the
    common case only one branch contributes — but supporting both keeps
    internal call sites and tests simple.
    """
    parts: list[str] = []
    params: list = []
    offset = param_offset

    if tags:
        clause, p, offset = build_tags_where_clause(
            tags=tags,
            param_offset=offset,
            table_alias=table_alias,
            match=tags_match,
        )
        if clause:
            # `build_tags_where_clause` already returns "AND ...". Strip the
            # leading "AND " here so we can join multiple parts ourselves.
            stripped = clause[len("AND ") :] if clause.startswith("AND ") else clause
            parts.append(f"({stripped})")
            params.extend(p)

    if tag_groups:
        clause, p, offset = build_tag_groups_where_clause(
            tag_groups=tag_groups,
            param_offset=offset,
            table_alias=table_alias,
        )
        if clause:
            stripped = clause[len("AND ") :] if clause.startswith("AND ") else clause
            parts.append(stripped)
            params.extend(p)

    if not parts:
        return "", [], param_offset

    combined = " AND ".join(parts)
    return f"AND ({combined})", params, offset


def filter_results_by_tags_and_groups(
    results: list,
    tags: list[str] | None,
    tag_groups: list["TagGroup"] | None,
    tags_match: TagsMatch = "any",
) -> list:
    """Convenience post-filter combining `filter_results_by_tags` and `filter_results_by_tag_groups`."""
    out = filter_results_by_tags(results, tags, match=tags_match)
    out = filter_results_by_tag_groups(out, tag_groups)
    return out
