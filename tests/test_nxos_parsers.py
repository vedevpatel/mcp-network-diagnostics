"""
Unit tests for NX-OS parsers (nxos.py).

Covers system-resources (CPU + memory in one command), interface brief
(NX-OS column layout), and interface detail (30-second rates, singular
error keyword).
"""

from mcp_network.parsers.nxos import (
    parse_system_resources,
    parse_interface_brief,
    parse_interface_detail,
)


# ===========================================================================
# parse_system_resources
# ===========================================================================


class TestNxosSystemResources:
    STANDARD = """\
CPU states  :   2.5% user,   1.3% kernel,   96.2% idle
Memory usage:   16402560K total,   2664308K used,   13738252K free
"""

    def test_cpu_from_idle(self):
        r = parse_system_resources(self.STANDARD)
        # 100 - 96.2 = 3.8
        assert r["cpu_percent"] == 3.8

    def test_memory_total_kb(self):
        r = parse_system_resources(self.STANDARD)
        assert r["total_kb"] == 16402560

    def test_memory_used_kb(self):
        r = parse_system_resources(self.STANDARD)
        assert r["used_kb"] == 2664308

    def test_memory_free_kb(self):
        r = parse_system_resources(self.STANDARD)
        assert r["free_kb"] == 13738252

    def test_memory_percent(self):
        r = parse_system_resources(self.STANDARD)
        expected = round((2664308 / 16402560) * 100, 1)
        assert r["memory_percent"] == expected

    def test_high_cpu(self):
        output = "CPU states  :  30.0% user,  20.0% kernel,   50.0% idle\nMemory usage:   1000K total,   500K used,   500K free\n"
        r = parse_system_resources(output)
        assert r["cpu_percent"] == 50.0

    def test_idle_100_means_zero_cpu(self):
        output = "CPU states  :   0.0% user,   0.0% kernel,  100.0% idle\nMemory usage:   1000K total,   100K used,   900K free\n"
        r = parse_system_resources(output)
        assert r["cpu_percent"] == 0.0

    def test_garbage_returns_zeros(self):
        r = parse_system_resources("nothing useful")
        assert r["cpu_percent"] == 0.0
        assert r["total_kb"] == 0
        assert r["memory_percent"] == 0.0

    def test_empty_string_returns_zeros(self):
        r = parse_system_resources("")
        assert r == {"cpu_percent": 0.0, "total_kb": 0, "used_kb": 0, "free_kb": 0, "memory_percent": 0.0}


# ===========================================================================
# parse_interface_brief
# ===========================================================================


class TestNxosInterfaceBrief:
    HEADER = (
        "Interface            VLAN    Type    Mode   Status  Reason  Speed    Port-ch\n"
        "-------------------------------------------------------------------------------\n"
    )

    def test_single_up_interface(self):
        output = self.HEADER + "Eth1/1               --      --      --     up      --      10G(D)   --\n"
        result = parse_interface_brief(output)
        assert len(result) == 1
        assert result[0]["name"] == "Eth1/1"
        assert result[0]["status"] == "up"
        assert result[0]["speed"] == "10G(D)"

    def test_down_interface_with_reason(self):
        output = self.HEADER + "Eth1/2               --      --      --     down    link down 1G(D)   --\n"
        result = parse_interface_brief(output)
        assert len(result) == 1
        assert result[0]["status"] == "down"
        assert result[0]["reason"] == "link down"

    def test_multiple_interfaces(self):
        output = (
            self.HEADER
            + "Eth1/1               --      --      --     up      --      10G(D)   --\n"
            + "Eth1/2               --      --      --     up      --      10G(D)   --\n"
            + "Eth1/3               --      --      --     down    --      auto(D)  --\n"
        )
        result = parse_interface_brief(output)
        assert len(result) == 3
        assert result[2]["name"] == "Eth1/3"
        assert result[2]["status"] == "down"

    def test_header_only_returns_empty(self):
        assert parse_interface_brief(self.HEADER) == []

    def test_non_eth_lines_skipped(self):
        output = self.HEADER + "mgmt0                --      --      --     up      --      1000    --\n"
        # mgmt0 doesn't start with 'Eth' → skipped
        assert parse_interface_brief(output) == []

    def test_short_lines_skipped(self):
        output = self.HEADER + "Eth1/1\n"
        assert parse_interface_brief(output) == []


# ===========================================================================
# parse_interface_detail
# ===========================================================================


class TestNxosInterfaceDetail:
    DETAIL = """\
Ethernet1/1 is up
  admin state is up, line protocol state is up
  Hardware is 10/25/40GbE, address is aabb.cc00.0001
  MTU 1500 bytes, BW 10000000 Kbit
  30 seconds input rate 5000000 bits/sec, 600 packets/sec
  30 seconds output rate 3000000 bits/sec, 400 packets/sec
     1000000 packets input, 1500000000 bytes
     800000 packets output, 1200000000 bytes
     42 input error, 0 CRC, 0 frame, 0 overrun, 0 ignored
     7 output error, 0 underruns
"""

    def test_name_parsed(self):
        r = parse_interface_detail(self.DETAIL)
        assert r["name"] == "Ethernet1/1"

    def test_admin_status(self):
        r = parse_interface_detail(self.DETAIL)
        assert r["admin_status"] == "up"

    def test_bandwidth(self):
        r = parse_interface_detail(self.DETAIL)
        assert r["bandwidth_kbit"] == 10000000

    def test_input_rate(self):
        r = parse_interface_detail(self.DETAIL)
        assert r["input_rate_bps"] == 5000000

    def test_output_rate(self):
        r = parse_interface_detail(self.DETAIL)
        assert r["output_rate_bps"] == 3000000

    def test_input_errors_singular_keyword(self):
        """NX-OS says 'input error' not 'input errors'."""
        r = parse_interface_detail(self.DETAIL)
        assert r["input_errors"] == 42

    def test_output_errors_singular_keyword(self):
        r = parse_interface_detail(self.DETAIL)
        assert r["output_errors"] == 7

    def test_utilization_math(self):
        # (5000000 + 3000000) / (10000000 * 1000) * 100 = 0.08 %
        r = parse_interface_detail(self.DETAIL)
        assert abs(r["utilization_percent"] - 0.08) < 0.001

    def test_down_interface_zeros(self):
        output = """\
Ethernet1/2 is down
  admin state is down
  BW 10000000 Kbit
  30 seconds input rate 0 bits/sec, 0 packets/sec
  30 seconds output rate 0 bits/sec, 0 packets/sec
     0 input error
     0 output error
"""
        r = parse_interface_detail(output)
        assert r["name"] == "Ethernet1/2"
        assert r["admin_status"] == "down"
        assert r["utilization_percent"] == 0.0
        assert r["input_errors"] == 0

    def test_zero_bandwidth_no_divide_by_zero(self):
        output = "Ethernet1/3 is up\n  30 seconds input rate 100 bits/sec\n"
        r = parse_interface_detail(output)
        assert r["utilization_percent"] == 0.0
