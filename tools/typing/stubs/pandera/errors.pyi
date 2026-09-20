"""Type the public Pandera failure category used by input-boundary regression tests."""

class SchemaError(Exception):
    """Identify a dataframe schema rejection."""

class SchemaErrors(Exception):
    """Identify multiple dataframe schema rejections."""
