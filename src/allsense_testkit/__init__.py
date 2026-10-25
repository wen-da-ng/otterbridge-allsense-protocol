"""Test kit for the AllSense protocol (spec/PROTOCOL.md): fake phones, reference codecs and the
conformance runner, so any client can be tested without a phone.

    from allsense_testkit import FakePhone
    phone = FakePhone()          # a stand-in phone on a free local port
    print(phone.url)             # the link a client connects with
    phone.stop()
"""

from .fake_phone import DEVICE, TOKEN, FakePhone

__version__ = "0.1.0"
PROTOCOL_VERSION = 0

__all__ = ["FakePhone", "TOKEN", "DEVICE", "PROTOCOL_VERSION", "__version__"]
