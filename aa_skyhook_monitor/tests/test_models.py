"""Tests for models"""

from datetime import timedelta
from unittest.mock import MagicMock

from django.test import TestCase
from django.utils import timezone

from aa_skyhook_monitor.models import Skyhook, SkyhookOwner, SkyhookReagent
from aa_skyhook_monitor.planet_resources import PLANET_REAGENT_DATA


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
    # Use a real planet from the SDE dict for capacity tests.
    # UQ9-3C III (planet_id=40272997): amount_per_cycle=717, capacity=1_046_820 units
    _TEST_PLANET_ID = 40272997
    _TEST_CAPACITY = PLANET_REAGENT_DATA[_TEST_PLANET_ID][1]  # 1_046_820

    def _make_reagent(self, volume, secured_stock, unsecured_stock, planet_id=None):
        from django.db.models.base import ModelState

        skyhook = MagicMock()
        skyhook.planet_id = planet_id or self._TEST_PLANET_ID
        r = SkyhookReagent.__new__(SkyhookReagent)
        r._state = ModelState()
        r._state.fields_cache["skyhook"] = skyhook
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
            volume=1.0, secured_stock=self._TEST_CAPACITY * 2, unsecured_stock=0
        )
        self.assertEqual(r.secured_pct, 100)

    def test_unsecured_pct_partial(self):
        r = self._make_reagent(
            volume=1.0, secured_stock=0, unsecured_stock=self._TEST_CAPACITY // 2
        )
        self.assertEqual(r.unsecured_pct, 50)

    def test_bay_capacity_units_known_planet(self):
        r = self._make_reagent(volume=0.01, secured_stock=0, unsecured_stock=0)
        self.assertEqual(r.bay_capacity_units, self._TEST_CAPACITY)

    def test_bay_capacity_units_unknown_planet(self):
        r = self._make_reagent(volume=0.01, secured_stock=0, unsecured_stock=0, planet_id=99999999)
        self.assertEqual(r.bay_capacity_units, 0)

    def test_secured_pct_unknown_planet_returns_zero(self):
        r = self._make_reagent(volume=0.01, secured_stock=1000, unsecured_stock=0, planet_id=99999999)
        self.assertEqual(r.secured_pct, 0)
