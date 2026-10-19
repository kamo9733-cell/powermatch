"""ONVIF discovery via WS-Discovery: pure message builder + response parser (no sockets here).

Send the probe by UDP to 239.255.255.250:3702 and feed each reply datagram to parse_probe_match.
"""
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

MULTICAST = ("239.255.255.250", 3702)
NS_S = "http://www.w3.org/2003/05/soap-envelope"
NS_A = "http://schemas.xmlsoap.org/ws/2004/08/addressing"
NS_D = "http://schemas.xmlsoap.org/ws/2005/04/discovery"
NS_DN = "http://www.onvif.org/ver10/network/wsdl"
PROFILE_PREFIX = "onvif://www.onvif.org/"


def build_probe(message_id: str | None = None) -> bytes:
    mid = message_id or f"uuid:{uuid.uuid4()}"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<e:Envelope xmlns:e="{NS_S}" xmlns:w="{NS_A}" xmlns:d="{NS_D}" xmlns:dn="{NS_DN}">'
        f"<e:Header><w:MessageID>{mid}</w:MessageID>"
        "<w:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>"
        f"<w:Action>{NS_D}/Probe</w:Action></e:Header>"
        "<e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body>"
        "</e:Envelope>"
    ).encode()


@dataclass
class DiscoveredDevice:
    address: str  # endpoint reference (urn:uuid:...)
    xaddrs: list[str]
    scopes: list[str] = field(default_factory=list)

    @property
    def name(self) -> str | None:
        return self._scope("name/")

    @property
    def hardware(self) -> str | None:
        return self._scope("hardware/")

    def _scope(self, key: str) -> str | None:
        for s in self.scopes:
            if s.startswith(PROFILE_PREFIX + key):
                return s[len(PROFILE_PREFIX + key):]
        return None

    @property
    def hosts(self) -> list[str]:
        from urllib.parse import urlsplit
        return [h for x in self.xaddrs if (h := urlsplit(x).hostname)]


def parse_probe_match(xml: bytes | str) -> list[DiscoveredDevice]:
    """Returns [] for anything malformed. Untrusted LAN input: DTD/entities are refused outright."""
    raw = xml.encode() if isinstance(xml, str) else xml
    if len(raw) > 65_536 or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    out = []
    for m in root.iter(f"{{{NS_D}}}ProbeMatch"):
        addr = m.findtext(f"{{{NS_A}}}EndpointReference/{{{NS_A}}}Address", "").strip()
        xaddrs = (m.findtext(f"{{{NS_D}}}XAddrs") or "").split()
        scopes = (m.findtext(f"{{{NS_D}}}Scopes") or "").split()
        if addr and xaddrs:
            out.append(DiscoveredDevice(addr, xaddrs, scopes))
    return out
