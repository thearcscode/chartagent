"""Assemble a backend-free input frame from a fragment (ADR-0019 D2/D6).

Code fills ``source_schema``, ``spec_version``, and empty ``annotations`` /
``interactions``. The model’s fragment carries chart type, encodings,
transform, and ``semantic_types``. This is also the data-free step-1
check: the façade, ``check_transform_shape``, and ``raw_sql``’s two locks.
Unknown columns are ``bind``’s — they need rows.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from chartagent.frame.input import InputFrame, SourceBucket
from chartagent.plan.schema import Fragment
from chartagent.profile.models import Profile
from chartagent.transform.drift import referenced_source_columns
from chartagent.transform.engine import open_connection
from chartagent.transform.menu import check_transform_shape
from chartagent.transform.raw_sql import sql_source_refs, validate_raw_sql

_SPEC_VERSION = "1.2"


def assemble(
    fragment: Fragment,
    profile: Profile,
    *,
    chart_properties: Mapping[str, Any] | None = None,
) -> InputFrame:
    """Build a backend-free ``InputFrame``. Raises on a step-1 schema failure."""
    check_transform_shape(fragment.transform)
    refs = _source_refs(fragment.transform)
    buckets = {column.name: column.bucket for column in profile.columns}
    source_schema: dict[str, SourceBucket] = {
        name: buckets[name] for name in sorted(refs) if name in buckets
    }
    return InputFrame.model_validate(
        {
            "semantic_types": fragment.semantic_types,
            "chart_spec": {
                "chartType": fragment.chart_type,
                "encodings": {
                    name: encoding.model_dump(exclude_none=True)
                    for name, encoding in fragment.encodings.items()
                },
                "chartProperties": dict(chart_properties or {}),
            },
            "x_chartagent": {
                "spec_version": _SPEC_VERSION,
                "transform": fragment.transform,
                "annotations": [],
                "interactions": {},
                "source_schema": source_schema,
            },
        }
    )


def _source_refs(transform: Mapping[str, object] | None) -> frozenset[str]:
    if transform is not None and "raw_sql" in transform:
        sql = transform["raw_sql"]
        if not isinstance(sql, str):
            return frozenset()
        connection = open_connection()
        try:
            validate_raw_sql(connection, sql)
            parsed = sql_source_refs(connection, sql)
        finally:
            connection.close()
        return frozenset() if parsed is None else parsed
    return referenced_source_columns(transform)
