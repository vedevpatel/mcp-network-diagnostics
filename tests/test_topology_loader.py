"""
Unit tests for topology_loader: YAML loading, ${ENV_VAR} interpolation,
and error paths.
"""

import pytest
import yaml

from mcp_network.collectors.topology_loader import load_topology, _interpolate, _substitute_vars


# ---------------------------------------------------------------------------
# _substitute_vars — unit-level
# ---------------------------------------------------------------------------


class TestSubstituteVars:
    def test_no_vars_passthrough(self):
        assert _substitute_vars("plain string") == "plain string"

    def test_single_var(self, monkeypatch):
        monkeypatch.setenv("TEST_HOST", "10.0.0.1")
        assert _substitute_vars("${TEST_HOST}") == "10.0.0.1"

    def test_var_embedded_in_text(self, monkeypatch):
        monkeypatch.setenv("TEST_PORT", "2222")
        assert _substitute_vars("ssh://host:${TEST_PORT}/path") == "ssh://host:2222/path"

    def test_multiple_vars_in_one_string(self, monkeypatch):
        monkeypatch.setenv("U", "admin")
        monkeypatch.setenv("P", "secret")
        assert _substitute_vars("${U}:${P}") == "admin:secret"

    def test_missing_var_raises(self, monkeypatch):
        monkeypatch.delenv("DEFINITELY_NOT_SET_XYZ", raising=False)
        with pytest.raises(EnvironmentError, match="DEFINITELY_NOT_SET_XYZ"):
            _substitute_vars("${DEFINITELY_NOT_SET_XYZ}")


# ---------------------------------------------------------------------------
# _interpolate — recursive walk
# ---------------------------------------------------------------------------


class TestInterpolate:
    def test_dict_values_interpolated(self, monkeypatch):
        monkeypatch.setenv("MY_VAL", "hello")
        result = _interpolate({"key": "${MY_VAL}", "num": 42})
        assert result == {"key": "hello", "num": 42}

    def test_list_items_interpolated(self, monkeypatch):
        monkeypatch.setenv("ITEM", "world")
        result = _interpolate(["plain", "${ITEM}"])
        assert result == ["plain", "world"]

    def test_nested_dict_in_list(self, monkeypatch):
        monkeypatch.setenv("DEEP", "found")
        data = [{"a": {"b": "${DEEP}"}}]
        assert _interpolate(data) == [{"a": {"b": "found"}}]

    def test_non_string_leaves_untouched(self):
        assert _interpolate(123) == 123
        assert _interpolate(None) is None
        assert _interpolate(3.14) == 3.14


# ---------------------------------------------------------------------------
# load_topology — full round-trip through file I/O
# ---------------------------------------------------------------------------


class TestLoadTopology:
    def _write_topo(self, tmp_path, data):
        p = tmp_path / "topo.yaml"
        p.write_text(yaml.dump(data))
        return str(p)

    def test_happy_path_no_vars(self, tmp_path):
        topo = self._write_topo(tmp_path, {
            "devices": [{"id": "R1", "type": "router", "host": "10.0.0.1"}],
            "links": [],
        })
        result = load_topology(topo)
        assert len(result["devices"]) == 1
        assert result["devices"][0]["id"] == "R1"

    def test_env_var_substituted_in_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TOPO_USER", "neteng")
        topo = self._write_topo(tmp_path, {
            "devices": [{"id": "R1", "type": "router", "username": "${TOPO_USER}"}],
            "links": [],
        })
        result = load_topology(topo)
        assert result["devices"][0]["username"] == "neteng"

    def test_missing_env_var_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MISSING_CRED_VAR", raising=False)
        topo = self._write_topo(tmp_path, {
            "devices": [{"id": "R1", "password": "${MISSING_CRED_VAR}"}],
            "links": [],
        })
        with pytest.raises(EnvironmentError, match="MISSING_CRED_VAR"):
            load_topology(topo)

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_topology("/no/such/file/topo.yaml")

    def test_invalid_yaml_raises(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text("devices: [[[not: valid: yaml{{{{")
        with pytest.raises(Exception):
            load_topology(str(p))

    def test_thresholds_and_local_device_preserved(self, tmp_path):
        topo = self._write_topo(tmp_path, {
            "local_device": "R1",
            "thresholds": {"cpu": 70, "utilization": 60, "errors": 50},
            "devices": [],
            "links": [],
        })
        result = load_topology(topo)
        assert result["local_device"] == "R1"
        assert result["thresholds"]["cpu"] == 70
