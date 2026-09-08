# SPDX-License-Identifier: Apache-2.0
"""Worker environment parsing without importing a web-service dependency."""
import os


class ConfigurationError(RuntimeError):
    """Invalid worker configuration."""


def env_str(name, default=None, *, required=False):
    value = os.getenv(name, "").strip()
    if value:
        return value
    if required:
        raise ConfigurationError(f"Missing required environment variable {name}")
    return default


def env_bool(name, default=False):
    def parse(value, fallback):
        value = str(value).strip().lower()
        if value in ("true", "1", "yes", "on"):
            return True
        if value in ("false", "0", "no", "off"):
            return False
        return fallback
    fallback = default if isinstance(default, bool) else parse(default, False)
    return parse(env_str(name), fallback)


def _number(name, default, convert):
    value = env_str(name)
    if value is None:
        return default
    try:
        return convert(value)
    except ValueError as error:
        raise ConfigurationError(f"Invalid numeric environment variable {name}") from error


def env_int(name, default):
    return _number(name, default, int)


def env_float(name, default):
    return _number(name, default, float)
