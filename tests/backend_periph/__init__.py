"""Shared fakes for the peripheral tests (never touch real /dev or /sys)."""
from alaz.backend.peripherals.hidraw import HidPermissionError


def rep(report_id, hexstr):
    return bytes([report_id]) + bytes.fromhex(hexstr.replace(" ", ""))


class FakeTransport:
    """Stands in for HidTransport. ``replies`` maps cmd bytes -> reply (bytes) / None (timeout)."""

    def __init__(self, replies=None, deny=False):
        self.replies = dict(replies or {})
        self.deny = deny
        self.log = []  # ("req"|"send", cmd)
        self.opened = False

    def open(self):
        if self.deny:
            raise HidPermissionError(13, "denied")
        self.opened = True

    def close(self):
        self.opened = False

    def request(self, cmd, match, timeout, retries=2):
        self.log.append(("req", bytes(cmd)))
        return self.replies.get(bytes(cmd))

    def send(self, cmd):
        self.log.append(("send", bytes(cmd)))

    def write_acked(self, cmd, timeout):
        self.log.append(("send", bytes(cmd)))
        return True

    def sent(self):
        return [c for k, c in self.log if k == "send"]

    def requested(self):
        return [c for k, c in self.log if k == "req"]


def settle(client, qapp=None):
    from PyQt6.QtCore import QCoreApplication
    client._pool.waitForDone(5000)
    QCoreApplication.processEvents()
