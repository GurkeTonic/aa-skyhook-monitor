"""Tests for ESI sync + Discord notification tasks (ESI and SDE mocked)."""

import sys
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo
from django.test import TestCase
from django.utils import timezone
from esi.exceptions import HTTPNotModified

from aa_skyhook_monitor import tasks
from aa_skyhook_monitor.models import (
    Skyhook,
    SkyhookConfiguration,
    SkyhookOwner,
    SkyhookReagent,
)


def _make_owner(corp_id=2001, char_id=90000001):
    corp = EveCorporationInfo.objects.create(
        corporation_id=corp_id,
        corporation_name="Test Corp",
        corporation_ticker="TST",
        member_count=1,
    )
    character = EveCharacter.objects.create(
        character_id=char_id,
        character_name="Owner Char",
        corporation_id=corp_id,
        corporation_name="Test Corp",
        corporation_ticker="TST",
    )
    return SkyhookOwner.objects.create(corporation=corp, character=character)


class TestUpdateOwnerSkyhooks(TestCase):
    def setUp(self):
        self.owner = _make_owner()
        # Inject a fake eve_sde.models so the SDE planet filter is deterministic.
        fake_planet = mock.MagicMock()
        fake_planet.objects.filter.return_value.values_list.return_value = [40001]
        fake_models = mock.MagicMock(Planet=fake_planet, ItemType=mock.MagicMock())
        sys.modules["eve_sde"] = mock.MagicMock(models=fake_models)
        sys.modules["eve_sde.models"] = fake_models
        self.addCleanup(lambda: sys.modules.pop("eve_sde", None))
        self.addCleanup(lambda: sys.modules.pop("eve_sde.models", None))

    @mock.patch.object(tasks, "esi")
    @mock.patch.object(tasks.Token, "get_token")
    @mock.patch.object(tasks.update_skyhook_detail, "delay")
    def test_dispatches_only_relevant_skyhooks(self, mock_delay, mock_token, mock_esi):
        mock_token.return_value = mock.MagicMock()
        listing = mock_esi.client.Structures.GetCorporationsStructuresSkyhooksListing
        listing.return_value.result.return_value = SimpleNamespace(
            skyhooks=[
                SimpleNamespace(id=1001, planet_id=40001),  # relevant (Lava/Ice)
                SimpleNamespace(id=1002, planet_id=40099),  # irrelevant
            ]
        )

        tasks.update_owner_skyhooks(self.owner.pk)

        mock_delay.assert_called_once_with(self.owner.pk, 2001, 1001, 40001)
        self.owner.refresh_from_db()
        self.assertIsNotNone(self.owner.last_updated)

    @mock.patch.object(tasks, "esi")
    @mock.patch.object(tasks.Token, "get_token")
    @mock.patch.object(tasks.update_skyhook_detail, "delay")
    def test_prunes_only_own_stale_skyhooks(self, mock_delay, mock_token, mock_esi):
        mock_token.return_value = mock.MagicMock()
        # Pre-existing skyhook of this owner that is no longer reported -> pruned.
        Skyhook.objects.create(owner=self.owner, structure_id=9999, planet_id=40001)
        # Another owner's skyhook must survive.
        other = _make_owner(corp_id=2002, char_id=90000002)
        survivor = Skyhook.objects.create(
            owner=other, structure_id=8888, planet_id=40001
        )

        listing = mock_esi.client.Structures.GetCorporationsStructuresSkyhooksListing
        listing.return_value.result.return_value = SimpleNamespace(
            skyhooks=[SimpleNamespace(id=1001, planet_id=40001)]
        )

        tasks.update_owner_skyhooks(self.owner.pk)

        self.assertFalse(Skyhook.objects.filter(structure_id=9999).exists())
        self.assertTrue(Skyhook.objects.filter(pk=survivor.pk).exists())

    @mock.patch.object(tasks.update_owner_skyhooks, "delay")
    def test_update_all_records_single_sync_timestamp(self, mock_delay):
        from aa_skyhook_monitor.models import SkyhookConfiguration

        self.assertIsNone(SkyhookConfiguration.get_last_sync())
        tasks.update_all_skyhooks()
        mock_delay.assert_called_once_with(self.owner.pk)
        self.assertIsNotNone(SkyhookConfiguration.get_last_sync())

    @mock.patch.object(tasks, "esi")
    @mock.patch.object(tasks.Token, "get_token")
    def test_not_modified_skips_without_error(self, mock_token, mock_esi):
        mock_token.return_value = mock.MagicMock()
        listing = mock_esi.client.Structures.GetCorporationsStructuresSkyhooksListing
        listing.return_value.result.side_effect = HTTPNotModified(
            status_code=304, headers={}
        )

        tasks.update_owner_skyhooks(self.owner.pk)

        self.owner.refresh_from_db()
        self.assertIsNotNone(self.owner.last_updated)


class TestUpdateSkyhookDetail(TestCase):
    def setUp(self):
        self.owner = _make_owner()

    def _detail(self, start, end, reagent_type=81143):
        return SimpleNamespace(
            is_active=True,
            state="active",
            reagents=[
                SimpleNamespace(
                    type_id=reagent_type, secured_stock=100, unsecured_stock=50
                )
            ],
            theft_vulnerability=SimpleNamespace(start=start, end=end),
        )

    @mock.patch.object(tasks, "esi")
    @mock.patch.object(tasks.Token, "get_token")
    def test_creates_skyhook_and_reagent(self, mock_token, mock_esi):
        mock_token.return_value = mock.MagicMock()
        detail = mock_esi.client.Structures.GetCorporationsStructuresSkyhooksDetail
        detail.return_value.result.return_value = self._detail(
            "2026-06-12T10:00:00Z", "2026-06-12T12:00:00Z"
        )

        tasks.update_skyhook_detail(self.owner.pk, 2001, 1001, 40001)

        skyhook = Skyhook.objects.get(structure_id=1001)
        self.assertTrue(skyhook.is_active)
        self.assertIsNotNone(skyhook.theft_vulnerability_start)
        self.assertEqual(skyhook.reagents.count(), 1)
        self.assertEqual(skyhook.reagents.first().secured_stock, 100)

    @mock.patch.object(tasks, "esi")
    @mock.patch.object(tasks.Token, "get_token")
    def test_irrelevant_reagent_deletes_skyhook(self, mock_token, mock_esi):
        mock_token.return_value = mock.MagicMock()
        Skyhook.objects.create(owner=self.owner, structure_id=1001, planet_id=40001)
        detail = mock_esi.client.Structures.GetCorporationsStructuresSkyhooksDetail
        detail.return_value.result.return_value = self._detail(
            "2026-06-12T10:00:00Z", "2026-06-12T12:00:00Z", reagent_type=99999
        )

        tasks.update_skyhook_detail(self.owner.pk, 2001, 1001, 40001)

        self.assertFalse(Skyhook.objects.filter(structure_id=1001).exists())

    @mock.patch.object(tasks, "esi")
    @mock.patch.object(tasks.Token, "get_token")
    def test_expired_window_forces_refresh(self, mock_token, mock_esi):
        mock_token.return_value = mock.MagicMock()
        past = timezone.now() - timedelta(hours=1)
        Skyhook.objects.create(
            owner=self.owner,
            structure_id=1001,
            planet_id=40001,
            theft_vulnerability_start=past - timedelta(hours=1),
            theft_vulnerability_end=past,
        )
        detail = mock_esi.client.Structures.GetCorporationsStructuresSkyhooksDetail
        detail.return_value.result.return_value = self._detail(
            "2026-06-12T20:00:00Z", "2026-06-12T22:00:00Z"
        )

        tasks.update_skyhook_detail(self.owner.pk, 2001, 1001, 40001)

        detail.return_value.result.assert_called_once_with(force_refresh=True)


class TestNotifications(TestCase):
    def setUp(self):
        self.owner = _make_owner()
        SkyhookConfiguration.objects.create(
            discord_webhook_url="https://discord.test/webhook"
        )

    def _vulnerable_skyhook(self, start, end):
        sk = Skyhook.objects.create(
            owner=self.owner,
            structure_id=1001,
            planet_id=40001,
            planet_name="Planet I",
            theft_vulnerability_start=start,
            theft_vulnerability_end=end,
        )
        SkyhookReagent.objects.create(
            skyhook=sk,
            type_id=81143,
            type_name="Magmatic Gas",
            volume=0.15,
            secured_stock=100,
            unsecured_stock=50,
        )
        return sk

    @mock.patch.object(tasks, "_send_discord")
    def test_warning_ping_sent_once(self, mock_send):
        now = timezone.now()
        sk = self._vulnerable_skyhook(
            now + timedelta(minutes=30), now + timedelta(minutes=90)
        )

        tasks.check_skyhook_notifications()
        tasks.check_skyhook_notifications()  # second run must not re-send

        self.assertEqual(mock_send.call_count, 1)
        sk.refresh_from_db()
        self.assertEqual(sk.notified_warning_for, sk.theft_vulnerability_start)

    @mock.patch.object(tasks, "_send_discord")
    def test_start_ping_when_window_open(self, mock_send):
        now = timezone.now()
        self._vulnerable_skyhook(
            now - timedelta(minutes=5), now + timedelta(minutes=55)
        )

        tasks.check_skyhook_notifications()

        self.assertEqual(mock_send.call_count, 1)


class TestDiscordRetry(TestCase):
    def setUp(self):
        SkyhookConfiguration.objects.create(
            discord_webhook_url="https://discord.test/webhook"
        )

    @mock.patch("aa_skyhook_monitor.tasks.sleep", return_value=None)
    @mock.patch("aa_skyhook_monitor.tasks.requests.post")
    def test_retries_then_succeeds(self, mock_post, _mock_sleep):
        ok = mock.MagicMock(status_code=204)
        # first call raises, second succeeds
        mock_post.side_effect = [Exception("network"), ok]

        tasks._send_discord({"content": "test"})

        self.assertEqual(mock_post.call_count, 2)
