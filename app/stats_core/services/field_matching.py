"""Source-neutral, conservative row matching owned by Fields.

Only explicitly saved relationships are planned. Keys must be unique on both
sides: repeating a total onto several records would change its meaning.
"""
from __future__ import annotations

import json
import math
from decimal import Decimal, InvalidOperation, localcontext

from stats_core.errors import ValidationError


def numeric_value(value):
    """Parse a numeric cell without conflating invalid content with blank zero."""
    if value is None or isinstance(value, str) and not value.strip():
        return 0.0
    if isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "").replace("$", "")
    if text.endswith("%"):
        text = text[:-1]
    try:
        number = float(text)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def match_key(value, field_type):
    """Blank keys never match. Text is exact after trimming, case-sensitive."""
    if value is None or isinstance(value, str) and not value.strip():
        return None
    if field_type == "number":
        if isinstance(value, bool):
            return None
        try:
            number = Decimal(str(value).strip().replace(",", "").replace("$", ""))
        except InvalidOperation:
            return None
        if not number.is_finite():
            return None
        # Identifiers may be larger than a JavaScript-safe integer. Never merge
        # distinct IDs merely because conversion to binary float rounds them.
        with localcontext() as context:
            context.prec = max(28, len(number.as_tuple().digits))
            canonical = str(number.normalize()) if number else "0"
        return ("number", canonical)
    return ("text", str(value).strip())


def public_row_key(field_id, key):
    return json.dumps([str(field_id), *key], ensure_ascii=False, separators=(",", ":")) if key else None


def unique_index(rows, key_of, label):
    result = {}
    for index, row in enumerate(rows):
        key = key_of(row)
        if key is None:
            continue
        if key in result:
            raise ValidationError(
                f"'{label}' repeats the same matching value. Choose a unique Field; "
                "matching these rows would repeat the numbers."
            )
        result[key] = index
    return result


def full_outer(left, right, left_key, right_key, left_label, right_label):
    """Return row pairs and diagnostics, keeping every unmatched source row."""
    left_index = unique_index(left, left_key, left_label)
    right_index = unique_index(right, right_key, right_label)
    pairs, used, matched = [], set(), 0
    for row in left:
        index = right_index.get(left_key(row))
        if index is None:
            pairs.append((row, None))
        else:
            pairs.append((row, right[index]))
            used.add(index)
            matched += 1
    pairs.extend((None, row) for index, row in enumerate(right) if index not in used)
    return pairs, {"matched_rows": matched, "left_only_rows": len(left) - matched,
                   "right_only_rows": len(right) - matched,
                   "left_blank_keys": len(left) - len(left_index),
                   "right_blank_keys": len(right) - len(right_index)}


def relationship_path(start, end, edges):
    """Find the single path through a saved, acyclic relationship graph."""
    pending, seen = [(start, [])], {start}
    for current, path in pending:
        if current == end:
            return path
        for edge in edges:
            nodes = (edge["left_report"], edge["right_report"])
            if current not in nodes:
                continue
            other = nodes[1] if nodes[0] == current else nodes[0]
            if other not in seen:
                seen.add(other)
                pending.append((other, path + [edge]))
    return None
