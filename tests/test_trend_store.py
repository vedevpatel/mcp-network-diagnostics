"""Unit tests for MetricStore and MetricSeries."""
from mcp_network.trends.store import MetricStore, MetricSeries
from mcp_network.models.network import Device, Interface


class TestMetricSeries:
    def test_add_and_count(self):
        s = MetricSeries(max_samples=5)
        for i in range(3):
            s.add(float(i), timestamp=float(i))
        assert s.count == 3

    def test_ring_buffer_eviction(self):
        s = MetricSeries(max_samples=3)
        for i in range(5):
            s.add(float(i), timestamp=float(i))
        assert s.count == 3
        assert s.samples[0].value == 2.0

    def test_latest(self):
        s = MetricSeries(max_samples=5)
        s.add(10.0, timestamp=1.0)
        s.add(20.0, timestamp=2.0)
        assert s.latest.value == 20.0

    def test_empty_latest_is_none(self):
        s = MetricSeries(max_samples=5)
        assert s.latest is None

    def test_empty_count_is_zero(self):
        s = MetricSeries(max_samples=5)
        assert s.count == 0

    def test_samples_returns_list_copy(self):
        s = MetricSeries(max_samples=5)
        s.add(1.0, timestamp=0.0)
        samples = s.samples
        assert isinstance(samples, list)
        assert len(samples) == 1


def _make_device(device_id, cpu, mem, iface_util, iface_errors):
    return Device(
        device_id=device_id,
        device_type="router",
        cpu_usage=cpu,
        memory_usage=mem,
        interfaces=[
            Interface(name="Gi0/0", utilization=iface_util,
                      errors=iface_errors, status="up")
        ],
    )


class TestMetricStore:
    def test_record_device_creates_series(self):
        store = MetricStore(max_samples=20)
        dev = _make_device("R1", 50.0, 60.0, 30.0, 5)
        store.record_device(dev, timestamp=1.0)
        assert store.get_series("R1", "cpu") is not None
        assert store.get_series("R1", "memory") is not None
        assert store.get_series("R1", "interface:Gi0/0:util") is not None
        assert store.get_series("R1", "interface:Gi0/0:errors") is not None

    def test_record_device_values(self):
        store = MetricStore()
        dev = _make_device("R1", 50.0, 60.0, 30.0, 5)
        store.record_device(dev, timestamp=1.0)
        assert store.get_series("R1", "cpu").latest.value == 50.0
        assert store.get_series("R1", "memory").latest.value == 60.0
        assert store.get_series("R1", "interface:Gi0/0:util").latest.value == 30.0
        assert store.get_series("R1", "interface:Gi0/0:errors").latest.value == 5.0

    def test_record_all_records_every_device(self):
        store = MetricStore()
        d1 = _make_device("R1", 50.0, 60.0, 30.0, 5)
        d2 = _make_device("R2", 55.0, 65.0, 35.0, 10)
        store.record_all({"R1": d1, "R2": d2}, timestamp=1.0)
        assert store.get_series("R1", "cpu").count == 1
        assert store.get_series("R2", "cpu").count == 1

    def test_multiple_records_accumulate(self):
        store = MetricStore()
        dev = _make_device("R1", 50.0, 60.0, 30.0, 5)
        store.record_device(dev, timestamp=1.0)
        dev2 = _make_device("R1", 55.0, 62.0, 32.0, 7)
        store.record_device(dev2, timestamp=2.0)
        assert store.get_series("R1", "cpu").count == 2

    def test_get_device_metrics(self):
        store = MetricStore()
        dev = _make_device("R1", 50.0, 60.0, 30.0, 5)
        store.record_device(dev, timestamp=1.0)
        metrics = store.get_device_metrics("R1")
        assert "cpu" in metrics
        assert "memory" in metrics
        assert "interface:Gi0/0:util" in metrics

    def test_get_device_metrics_empty(self):
        store = MetricStore()
        assert store.get_device_metrics("R99") == {}

    def test_missing_series_returns_none(self):
        store = MetricStore()
        assert store.get_series("R99", "cpu") is None

    def test_clear(self):
        store = MetricStore()
        dev = _make_device("R1", 50.0, 60.0, 30.0, 5)
        store.record_device(dev, timestamp=1.0)
        store.clear()
        assert store.get_series("R1", "cpu") is None

    def test_max_samples_respected(self):
        store = MetricStore(max_samples=3)
        dev = _make_device("R1", 50.0, 60.0, 30.0, 5)
        for i in range(5):
            store.record_device(dev, timestamp=float(i))
        assert store.get_series("R1", "cpu").count == 3

    def test_multiple_interfaces(self):
        dev = Device(
            device_id="R1",
            device_type="router",
            cpu_usage=50.0,
            memory_usage=60.0,
            interfaces=[
                Interface(name="Gi0/0", utilization=10.0, errors=0, status="up"),
                Interface(name="Gi0/1", utilization=20.0, errors=1, status="up"),
            ],
        )
        store = MetricStore()
        store.record_device(dev, timestamp=1.0)
        assert store.get_series("R1", "interface:Gi0/0:util").latest.value == 10.0
        assert store.get_series("R1", "interface:Gi0/1:util").latest.value == 20.0
