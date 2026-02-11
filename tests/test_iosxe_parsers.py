"""
Unit tests for IOS-XE parsers (iosxe.py).

Covers both supported output formats for each parser, edge cases
(garbage / empty input), and utilization arithmetic.
"""

from mcp_network.parsers.iosxe import (
    parse_memory_summary,
    parse_cpu_usage,
    parse_interface_brief,
    parse_interface_detail,
)


# ===========================================================================
# parse_memory_summary
# ===========================================================================


class TestIosxeMemory:
    # -- Processor Pool format (show processes memory sorted) --

    POOL_OUTPUT = (
        "System memory status\n"
        "Processor Pool Total:  412852636 Used:  103498492 Free:  309354144\n"
    )

    def test_pool_total_mb(self):
        r = parse_memory_summary(self.POOL_OUTPUT)
        assert round(r["total_mb"], 1) == round(412852636 / (1024 * 1024), 1)

    def test_pool_used_mb(self):
        r = parse_memory_summary(self.POOL_OUTPUT)
        assert round(r["used_mb"], 1) == round(103498492 / (1024 * 1024), 1)

    def test_pool_free_mb(self):
        r = parse_memory_summary(self.POOL_OUTPUT)
        assert round(r["free_mb"], 1) == round(309354144 / (1024 * 1024), 1)

    def test_pool_usage_percent(self):
        r = parse_memory_summary(self.POOL_OUTPUT)
        expected = (103498492 / 412852636) * 100
        assert abs(r["usage_percent"] - expected) < 0.01

    # -- show memory statistics format --

    STATS_OUTPUT = (
        "Pool Name  Address    Total      Used       Free\n"
        "Processor  3E6413E0   500000000  200000000  300000000\n"
    )

    def test_stats_format_parsed(self):
        r = parse_memory_summary(self.STATS_OUTPUT)
        assert r["total_mb"] == 500000000 / (1024 * 1024)
        assert r["used_mb"] == 200000000 / (1024 * 1024)

    def test_stats_usage_percent(self):
        r = parse_memory_summary(self.STATS_OUTPUT)
        assert abs(r["usage_percent"] - 40.0) < 0.01

    # -- garbage / missing --

    def test_garbage_returns_zeros(self):
        r = parse_memory_summary("nothing useful here")
        assert r["total_mb"] == 0.0
        assert r["used_mb"] == 0.0
        assert r["usage_percent"] == 0.0

    def test_empty_string_returns_zeros(self):
        r = parse_memory_summary("")
        assert r == {"total_mb": 0.0, "used_mb": 0.0, "free_mb": 0.0, "usage_percent": 0.0}


# ===========================================================================
# parse_cpu_usage
# ===========================================================================


class TestIosxeCpu:
    def test_standard_format(self):
        output = "CPU utilization for five seconds: 12%/3%; one minute: 8%; five minutes: 5%\n"
        assert parse_cpu_usage(output) == 5.0

    def test_higher_value(self):
        output = "CPU utilization for five seconds: 90%/45%; one minute: 87%; five minutes: 82%\n"
        assert parse_cpu_usage(output) == 82.0

    def test_alt_format_five_minutes_only(self):
        # Some IOS-XE variants omit the prefix
        output = "  one minute: 10%; five minutes: 7%\n"
        assert parse_cpu_usage(output) == 7.0

    def test_missing_cpu_line_returns_zero(self):
        assert parse_cpu_usage("show version output here") == 0.0

    def test_empty_string_returns_zero(self):
        assert parse_cpu_usage("") == 0.0


# ===========================================================================
# parse_interface_brief
# ===========================================================================


class TestIosxeInterfaceBrief:
    HEADER = "Interface              IP-Address      OK? Method Status                Protocol\n"

    def test_up_interface(self):
        output = self.HEADER + "GigabitEthernet0/0     10.1.1.1        YES NVRAM  up                    up\n"
        result = parse_interface_brief(output)
        assert len(result) == 1
        assert result[0]["name"] == "GigabitEthernet0/0"
        assert result[0]["ip_address"] == "10.1.1.1"
        assert result[0]["status"] == "up"
        assert result[0]["protocol"] == "up"

    def test_admin_down_interface(self):
        output = self.HEADER + "GigabitEthernet0/1     unassigned      YES NVRAM  administratively down down\n"
        result = parse_interface_brief(output)
        assert len(result) == 1
        assert result[0]["status"] == "admin_down"
        assert result[0]["protocol"] == "down"

    def test_multiple_interfaces(self):
        output = (
            self.HEADER
            + "GigabitEthernet0/0     10.1.1.1        YES NVRAM  up                    up\n"
            + "GigabitEthernet0/1     10.1.1.2        YES NVRAM  up                    up\n"
            + "Loopback0              1.1.1.1         YES NVRAM  up                    up\n"
        )
        result = parse_interface_brief(output)
        assert len(result) == 3
        names = [r["name"] for r in result]
        assert "GigabitEthernet0/0" in names
        assert "Loopback0" in names

    def test_header_only_returns_empty(self):
        result = parse_interface_brief(self.HEADER)
        assert result == []

    def test_empty_string_returns_empty(self):
        assert parse_interface_brief("") == []


# ===========================================================================
# parse_interface_detail
# ===========================================================================


class TestIosxeInterfaceDetail:
    DETAIL_TRAFFIC = """\
GigabitEthernet0/0 is up, line protocol is up
  Hardware is GigabitEthernet, address is aabb.cc00.0001
  MTU 1500 bytes, BW 1000000 Kbit
  5 minute input rate 100000 bits/sec, 50 packets/sec
  5 minute output rate 100000 bits/sec, 50 packets/sec
     500000 packets input, 750000000 bytes
     500000 packets output, 750000000 bytes
     3 input errors, 0 CRC, 0 frame, 0 overrun, 0 ignored
     7 output errors, 0 underruns
"""

    def test_bandwidth_parsed(self):
        r = parse_interface_detail(self.DETAIL_TRAFFIC)
        assert r["bandwidth_kbps"] == 1000000

    def test_input_rate_parsed(self):
        r = parse_interface_detail(self.DETAIL_TRAFFIC)
        assert r["input_rate_bps"] == 100000

    def test_output_rate_parsed(self):
        r = parse_interface_detail(self.DETAIL_TRAFFIC)
        assert r["output_rate_bps"] == 100000

    def test_input_errors_parsed(self):
        r = parse_interface_detail(self.DETAIL_TRAFFIC)
        assert r["input_errors"] == 3

    def test_output_errors_parsed(self):
        r = parse_interface_detail(self.DETAIL_TRAFFIC)
        assert r["output_errors"] == 7

    def test_utilization_math(self):
        # (100000 + 100000) / (1000000 * 1000) * 100 = 0.02 %
        r = parse_interface_detail(self.DETAIL_TRAFFIC)
        assert abs(r["utilization_percent"] - 0.02) < 0.001

    def test_zero_bandwidth_no_divide_by_zero(self):
        output = "GigabitEthernet0/0 is up\n  5 minute input rate 100 bits/sec\n"
        r = parse_interface_detail(output)
        assert r["utilization_percent"] == 0.0

    def test_all_zeros_on_shutdown(self):
        output = """\
GigabitEthernet0/1 is administratively down, line protocol is down
  Hardware is GigabitEthernet, address is aabb.cc00.0002
  MTU 1500 bytes, BW 1000000 Kbit
  5 minute input rate 0 bits/sec, 0 packets/sec
  5 minute output rate 0 bits/sec, 0 packets/sec
     0 input errors, 0 CRC, 0 frame, 0 overrun, 0 ignored
     0 output errors, 0 underruns
"""
        r = parse_interface_detail(output)
        assert r["input_rate_bps"] == 0
        assert r["output_rate_bps"] == 0
        assert r["input_errors"] == 0
        assert r["output_errors"] == 0
        assert r["utilization_percent"] == 0.0

    def test_high_utilization(self):
        # 500 Mbps each direction on a 1 Gbps link → 100 %
        output = """\
GigabitEthernet0/0 is up
  BW 1000000 Kbit
  5 minute input rate 500000000 bits/sec, 60000 packets/sec
  5 minute output rate 500000000 bits/sec, 60000 packets/sec
     0 input errors
     0 output errors
"""
        r = parse_interface_detail(output)
        assert abs(r["utilization_percent"] - 100.0) < 0.01
