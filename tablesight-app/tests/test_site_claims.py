"""Marketing claims must match the product: plan limits on the site == billing.PLANS; no unmeasured numbers."""
import re
from html.parser import HTMLParser
from pathlib import Path

from tablesight.platform.billing import PLANS

SITE = Path(__file__).parents[1] / "site" / "index.html"


class Cards(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cards = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "data-plan" in a:
            self.cards.append(a)


def test_site_plans_match_billing_plans():
    p = Cards()
    p.feed(SITE.read_text(encoding="utf-8"))
    names = {c["data-plan"]: c for c in p.cards}
    assert {"starter", "pro"} <= set(names)
    for n in ("starter", "pro"):
        assert int(names[n]["data-cameras"]) == PLANS[n].max_cameras
        assert int(names[n]["data-locations"]) == PLANS[n].max_locations


def test_site_has_early_access_banner_and_no_invented_confidence_numbers():
    html = SITE.read_text(encoding="utf-8")
    assert "Early access" in html and "simulated data only" in html
    assert not re.search(r"confidence\s*\d{2}\s*%", html)
    assert "tuned for low light" not in html


def test_roi_calculator_does_not_default_to_a_favourable_answer():
    html = SITE.read_text(encoding="utf-8")
    assert re.search(r'id="upl"[^>]*value="0"', html)
