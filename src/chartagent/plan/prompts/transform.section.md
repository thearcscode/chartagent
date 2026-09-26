## The transform

No transform exists yet: you author it, and the rows your `render` receives are its output. Write it as either the menu or `raw_sql` alone, never both. The menu is a JSON object using only these slots: $SLOTS. Expression nodes use only these kinds: $EXPR_KINDS. `raw_sql` is a single DuckDB SELECT over a table named `source`; it may read nothing else, and anything that is not a plain read of `source` is rejected.

Author `semantic_types` fresh for the transform's output columns; never copy them from the profile. Draw each value from this list: $SEMANTIC_TYPES. Do not author a source schema: the host computes it.
