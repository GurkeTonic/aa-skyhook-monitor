"""Tests for models"""

from datetime import timedelta
from unittest.mock import MagicMock

from allianceauth.tests.auth_utils import AuthUtils
from django.test import TestCase
from django.utils import timezone

from aa_skyhook_monitor.constants import BAY_VOLUME_M3
from aa_skyhook_monitor.models import Skyhook, SkyhookOwner, SkyhookReagent


def make_owner():
    corp = MagicMock()
    corp.corporation_name = "Test Corp"
    owner = MagicMock(spec=SkyhookOwner)
    owner.corporation = corp
    return owner


class TestSkyhookVulnProperties(TestCase):
    def _make_skyhook(self, start_offset_minutes, end_offset_minutes=None):
        now = timezone.now()
        skyhook = Skyhook.__new__(Skyhook)
        skyhook.theft_vulnerability_start = now + timedelta(
            minutes=start_offset_minutes
        )
        if end_offset_minutes is not None:
            skyhook.theft_vulnerability_end = now + timedelta(
                minutes=end_offset_minutes
            )
        else:
            skyhook.theft_vulnerability_end = None
        return skyhook

    def test_vuln_is_expired_no_start(self):
        s = Skyhook.__new__(Skyhook)
        s.theft_vulnerability_start = None
        s.theft_vulnerability_end = None
        self.assertFalse(s.vuln_is_expired)

    def test_vuln_is_expired_future(self):
        s = self._make_skyhook(start_offset_minutes=30, end_offset_minutes=60)
        self.assertFalse(s.vuln_is_expired)

    def test_vuln_is_expired_active(self):
        s = self._make_skyhook(start_offset_minutes=-10, end_offset_minutes=10)
        self.assertFalse(s.vuln_is_expired)

    def test_vuln_is_expired_past(self):
        s = self._make_skyhook(start_offset_minutes=-60, end_offset_minutes=-30)
        self.assertTrue(s.vuln_is_expired)

    def test_is_currently_vulnerable_active(self):
        s = self._make_skyhook(start_offset_minutes=-10, end_offset_minutes=10)
        self.assertTrue(s.is_currently_vulnerable)

    def test_is_currently_vulnerable_future(self):
        s = self._make_skyhook(start_offset_minutes=10, end_offset_minutes=70)
        self.assertFalse(s.is_currently_vulnerable)

    def test_is_currently_vulnerable_no_dates(self):
        s = Skyhook.__new__(Skyhook)
        s.theft_vulnerability_start = None
        s.theft_vulnerability_end = None
        self.assertFalse(s.is_currently_vulnerable)


class TestSkyhookReagentProperties(TestCase):
    def _make_reagent(self, volume, secured_stock, unsecured_stock):
        r = SkyhookReagent.__new__(SkyhookReagent)
        r.volume = volume
        r.secured_stock = secured_stock
        r.unsecured_stock = unsecured_stock
        return r

    def test_secured_m3(self):
        r = self._make_reagent(volume=2.0, secured_stock=1000, unsecured_stock=500)
        self.assertEqual(r.secured_m3, 2000)

    def test_unsecured_m3(self):
        r = self._make_reagent(volume=2.0, secured_stock=1000, unsecured_stock=500)
        self.assertEqual(r.unsecured_m3, 1000)

    def test_secured_pct_capped_at_100(self):
        r = self._make_reagent(
            volume=1.0, secured_stock=BAY_VOLUME_M3 * 2, unsecured_stock=0
        )
        self.assertEqual(r.secured_pct, 100)

    def test_unsecured_pct_partial(self):
        r = self._make_reagent(
            volume=1.0, secured_stock=0, unsecured_stock=BAY_VOLUME_M3 // 2
        )
        self.assertEqual(r.unsecured_pct, 50)
