"""Core shared primitives."""

from .api_codes import ErrorCode, HttpStatus
from .coercion import parse_required_int, parse_strict_bool, parse_strict_int
from .collections import deduplicate_preserving_order, restore_input_order
from .datetime_utils import (
    APP_TIMEZONE,
    ensure_timezone,
    normalize_datetime_str,
    now_local,
    parse_datetime,
    serialize_datetime,
)
from .id_generator import (
    ClockMovedBackwardsError,
    SnowflakeConfig,
    SnowflakeGenerator,
    configure_snowflake_generator,
    generate_snowflake_id,
    generate_uuid7_hex,
)
from .model_normalization import (
    normalize_bool,
    normalize_non_negative_int,
    normalize_optional_bool,
    normalize_optional_datetime,
    normalize_optional_int,
    normalize_optional_positive_int,
    normalize_optional_str,
    normalize_positive_int,
    normalize_required_str,
    normalize_wire_payload,
)
from .naming import camel_to_snake, camel_to_snake_dict, snake_to_camel, snake_to_camel_dict

__all__ = [
    "APP_TIMEZONE",
    "ClockMovedBackwardsError",
    "ErrorCode",
    "HttpStatus",
    "SnowflakeConfig",
    "SnowflakeGenerator",
    "camel_to_snake",
    "camel_to_snake_dict",
    "configure_snowflake_generator",
    "deduplicate_preserving_order",
    "ensure_timezone",
    "generate_snowflake_id",
    "generate_uuid7_hex",
    "normalize_bool",
    "normalize_datetime_str",
    "normalize_non_negative_int",
    "normalize_optional_bool",
    "normalize_optional_datetime",
    "normalize_optional_int",
    "normalize_optional_positive_int",
    "normalize_optional_str",
    "normalize_positive_int",
    "normalize_required_str",
    "normalize_wire_payload",
    "now_local",
    "parse_datetime",
    "parse_required_int",
    "parse_strict_bool",
    "parse_strict_int",
    "restore_input_order",
    "serialize_datetime",
    "snake_to_camel",
    "snake_to_camel_dict",
]
