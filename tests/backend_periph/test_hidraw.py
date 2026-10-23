import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from alaz.backend.peripherals import hidraw as H


def make_node(root, name, vid, pid, desc):
    d = root / name / "device"
    d.mkdir(parents=True)
    (d / "uevent").write_text(f"DRIVER=hid\nHID_ID=0003:{vid:08X}:{pid:08X}\nHID_NAME=x\n")
    (d / "report_descriptor").write_bytes(desc)


def test_find_nodes(tmp_path):
    make_node(tmp_path, "hidraw3", 0x0B05, 0x1ACE, bytes.fromhex("0601ff0901a1018503c0"))
    make_node(tmp_path, "hidraw10", 0x0B05, 0x1ACE, bytes.fromhex("0601ff0901a1018504c0"))  # no 85 03
    make_node(tmp_path, "hidraw4", 0x0B05, 0x1B84, bytes.fromhex("0601ff0901a10185cc"))
    make_node(tmp_path, "hidraw5", 0x046D, 0x1ACE, bytes.fromhex("8503"))  # wrong vendor
    assert H.find_nodes(0x0B05, {0x1ACE}, 0x03, tmp_path, "/dev") == ["/dev/hidraw3"]
    assert H.find_nodes(0x0B05, {0x1B84, 0x1B82}, 0xCC, tmp_path, "/x") == ["/x/hidraw4"]
    assert H.find_nodes(0x0B05, {0x1ACE}, 0xCC, tmp_path) == []


def test_find_nodes_missing_root(tmp_path):
    assert H.find_nodes(1, {2}, 3, tmp_path / "nope") == []


class FakeIO:
    def __init__(self, on_write=None, stale=()):
        self.queue = list(stale)
        self.writes = []
        self.on_write = on_write or (lambda data: [])
        self.deny = False
        self.closed = []

    def open(self, path):
        if self.deny:
            raise PermissionError()
        return 7

    def close(self, fd):
        self.closed.append(fd)

    def read(self, fd):
        return self.queue.pop(0) if self.queue else None

    def write(self, fd, data):
        self.writes.append(data)
        self.queue.extend(self.on_write(data))

    def wait(self, fd, timeout):
        return bool(self.queue)


def pkt(rid, hexstr):
    return (bytes([rid]) + bytes.fromhex(hexstr)).ljust(64, b"\x00")


def make(io, rid=0x03):
    t = H.HidTransport("/dev/fake", rid, io=io)
    t.open()
    return t


def test_frame_is_64_bytes_zero_padded():
    io = FakeIO()
    t = make(io)
    t.send(b"\x50\x03")
    assert io.writes == [b"\x03\x50\x03" + bytes(61)]


def test_request_drains_stale_and_skips_async():
    stale = [pkt(3, "1207aa")]  # stale reply from an earlier request

    def on_write(data):
        return [pkt(3, "1201ffff"), pkt(3, "120700005a")]  # async button report, then real reply

    io = FakeIO(on_write, stale)
    r = make(io).request(b"\x12\x07", b"\x12\x07", 0.05)
    assert r[5] == 0x5A


def test_request_returns_error_reply():
    io = FakeIO(lambda d: [pkt(3, "ffaa")])
    r = make(io).request(b"\x12\x07", b"\x12\x07", 0.05)
    assert r[1:3] == b"\xff\xaa"


def test_request_times_out_with_retries():
    io = FakeIO()
    assert make(io).request(b"\x12\x07", b"\x12\x07", 0.01, retries=2) is None
    assert len(io.writes) == 3


def test_request_retries_then_succeeds():
    state = {"n": 0}

    def on_write(data):
        state["n"] += 1
        return [pkt(3, "12070000" + "11")] if state["n"] == 2 else []

    io = FakeIO(on_write)
    assert make(io).request(b"\x12\x07", b"\x12\x07", 0.01)[5] == 0x11
    assert len(io.writes) == 2


def test_ignores_other_report_ids():
    io = FakeIO(lambda d: [pkt(1, "1207"), pkt(3, "1207000001")])
    assert make(io).request(b"\x12\x07", b"\x12\x07", 0.05)[0] == 3


def test_permission_error():
    io = FakeIO()
    io.deny = True
    with pytest.raises(H.HidPermissionError):
        H.HidTransport("/dev/fake", 3, io=io).open()


def test_closed_transport_raises():
    t = H.HidTransport("/dev/fake", 3, io=FakeIO())
    with pytest.raises(H.HidError):
        t.request(b"\x12\x07", b"\x12\x07", 0.01)
    t = make(FakeIO())
    t.close()
    with pytest.raises(H.HidError):
        t.send(b"\x50\x03")


def test_write_acked_waits_for_echo_without_retry():
    # VERIFIED on hardware: a write is echoed back (03 51 28 …); a missing echo is not resent.
    echo = FakeIO(lambda d: [pkt(3, "1201ffff"), d])  # async report first, then the echo
    assert make(echo).write_acked(b"\x51\x28\x00\x00\x00\x64\x00\xff\x00", 0.05) is True
    silent = FakeIO()
    assert make(silent).write_acked(b"\x50\x03", 0.01) is False
    assert len(silent.writes) == 1
