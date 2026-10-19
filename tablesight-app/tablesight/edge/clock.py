"""Clock drift vs server time and event timestamp correction."""
import email.utils
from collections.abc import Callable
from dataclasses import dataclass


def parse_http_date(value: str) -> float:
    """Server time from an HTTP `Date` header (1 s resolution; fine for a drift alarm)."""
    return email.utils.parsedate_to_datetime(value).timestamp()


@dataclass
class ClockSync:
    offset: float = 0.0  # add to local time to get server time
    rtt: float = 0.0
    synced: bool = False
    max_rtt: float = 5.0  # discard measurements taken on a bad link

    def measure(self, fetch_server_time: Callable[[], float], local: Callable[[], float]) -> bool:
        t0 = local()
        server = fetch_server_time()
        t1 = local()
        rtt = t1 - t0
        if rtt < 0 or rtt > self.max_rtt:
            return False
        # assume the server stamped at the midpoint of the round trip
        self.offset, self.rtt, self.synced = server - (t0 + rtt / 2), rtt, True
        return True

    def correct(self, local_t: float) -> float:
        return local_t + self.offset

    def drifting(self, tolerance_s: float = 2.0) -> bool:
        return self.synced and abs(self.offset) > tolerance_s
