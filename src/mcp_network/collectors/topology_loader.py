"""Shared topology file loader with ${ENV_VAR} interpolation."""

import os
import re
import yaml
import logging

logger = logging.getLogger(__name__)


def load_topology(topology_file: str) -> dict:
    """
    Load a YAML topology file, substituting ${VAR_NAME} placeholders
    with values from the environment.

    Raises:
        FileNotFoundError: topology_file does not exist.
        yaml.YAMLError: file is not valid YAML.
        EnvironmentError: a referenced ${VAR} is not set.
    """
    try:
        with open(topology_file, 'r') as f:
            topology = yaml.safe_load(f)
    except FileNotFoundError:
        logger.error(f"Topology file not found: {topology_file}")
        raise
    except yaml.YAMLError as e:
        logger.error(f"Invalid YAML in topology file: {e}")
        raise

    topology = _interpolate(topology)

    logger.info(
        f"Loaded topology from {topology_file}: "
        f"{len(topology.get('devices', []))} devices, "
        f"{len(topology.get('links', []))} links"
    )
    return topology


def _interpolate(obj):
    """Recursively substitute ${VAR} in all string values."""
    if isinstance(obj, str):
        return _substitute_vars(obj)
    elif isinstance(obj, dict):
        return {k: _interpolate(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_interpolate(item) for item in obj]
    return obj


def _substitute_vars(s: str) -> str:
    """Replace ${VAR_NAME} with os.environ[VAR_NAME]."""
    def _replace(match):
        var_name = match.group(1)
        value = os.environ.get(var_name)
        if value is None:
            raise EnvironmentError(
                f"Topology references ${{{var_name}}} "
                f"but {var_name} is not set in the environment."
            )
        return value

    return re.sub(r'\$\{(\w+)\}', _replace, s)
