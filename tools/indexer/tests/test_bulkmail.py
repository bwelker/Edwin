"""Unit tests for the bulk-mail classifier (lib/bulkmail.py).

Run:  /opt/homebrew/bin/python3.12 -m unittest tools/indexer/tests/test_bulkmail.py
  or: cd tools/indexer && /opt/homebrew/bin/python3.12 -m unittest discover tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.bulkmail import is_bulk_mail  # noqa: E402


class TestBulkMail(unittest.TestCase):

    # -- bulk: must be detected ----------------------------------------------

    def test_newsletter_sender_with_footer(self):
        fm = {"from": "Big Box Store <newsletter@shopmail.example.com>",
              "subject": "[TRENDING] Every Great Joint Starts Here"}
        body = "Meet the Complete Festool DOMINO Lineup\nSHOP NOW\n"
        self.assertTrue(is_bulk_mail(fm, body))

    def test_noreply_sender(self):
        fm = {"from": "TaxApp <noreply@example.com>",
              "subject": "Your maximum refund is waiting"}
        self.assertTrue(is_bulk_mail(fm, "File today and save."))

    def test_do_not_reply_variants(self):
        fm = {"from": "Hotel Rewards <do-not-reply@example.com>",
              "subject": "Your points update"}
        self.assertTrue(is_bulk_mail(fm, "Points summary attached."))

    def test_promo_subdomain_plus_unsubscribe(self):
        fm = {"from": "Outdoor Co-op <gearmail@email.example.com>",
              "subject": "New arrivals for summer"}
        body = ("Big savings inside.\n\n"
                "Unsubscribe | View in browser | Privacy policy")
        self.assertTrue(is_bulk_mail(fm, body))

    def test_marketing_subject_plus_unsubscribe(self):
        fm = {"from": "Deals Team <hello@dealsmail.example.com>",
              "subject": "Flash sale: 40% off everything, last chance"}
        body = "Shop the sale now.\nIf you no longer wish to receive these emails, opt out."
        self.assertTrue(is_bulk_mail(fm, body))

    # -- not bulk: personal / work senders must never be classified ----------

    def test_personal_sender_plain(self):
        fm = {"from": "Jane Doe <jane.doe@example.com>",
              "subject": "Dinner Saturday?"}
        self.assertFalse(is_bulk_mail(fm, "Sam and their partner are free Saturday."))

    def test_personal_sender_forwarding_a_deal(self):
        # A friend forwarding a promo: subject marker alone must not classify.
        fm = {"from": "Sam Rivers <srivers82@example.com>",
              "subject": "Fwd: 50% off Festool this weekend"}
        self.assertFalse(is_bulk_mail(fm, "Saw this and thought of you."))

    def test_work_domain_allowlisted(self):
        # Internal automated mail stays contextualized even with bulk markers
        # when its domain is on the configured allowlist.
        import lib.bulkmail as bulkmail
        fm = {"from": "Alerts <noreply@example.com>",
              "subject": "Sensor node offline"}
        body = "Node edge-14 stopped reporting.\nUnsubscribe from these alerts."
        old = bulkmail.ALLOW_DOMAIN_SUFFIXES
        bulkmail.ALLOW_DOMAIN_SUFFIXES = ("example.com",)
        try:
            self.assertFalse(is_bulk_mail(fm, body))
        finally:
            bulkmail.ALLOW_DOMAIN_SUFFIXES = old

    def test_colleague_with_unsubscribe_quote(self):
        # One weak signal (quoted unsubscribe footer) is not enough.
        fm = {"from": "Taylor Quinn <tquinn@example.net>",
              "subject": "Re: vendor contract"}
        body = "See the forwarded thread below.\n> Unsubscribe here"
        self.assertFalse(is_bulk_mail(fm, body))

    def test_empty_sender_never_bulk(self):
        fm = {"from": " <>", "subject": None}
        self.assertFalse(is_bulk_mail(fm, ""))


if __name__ == "__main__":
    unittest.main()
