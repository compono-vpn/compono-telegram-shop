import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.constants import IMPORTED_TAG, REMNASHOP_PREFIX
from src.core.enums import SubscriptionStatus
from src.services.importer import ImporterService


@pytest.fixture
def service():
    svc = ImporterService(
        config=MagicMock(),
        redis_client=MagicMock(),
        redis_repository=MagicMock(),
    )
    return svc


@pytest.fixture
def xui_db(tmp_path):
    """Create a real SQLite DB mimicking 3X-UI schema."""
    db_path = tmp_path / "x-ui.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE inbounds (id INTEGER PRIMARY KEY, settings TEXT)")
    conn.close()
    return db_path


def _insert_inbound(db_path: Path, inbound_id: int, clients: list[dict]) -> None:
    settings = json.dumps({"clients": clients})
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO inbounds (id, settings) VALUES (?, ?)", (inbound_id, settings))
    conn.commit()
    conn.close()


def _make_xui_user(
    email: str = "user123",
    enable: bool = True,
    expiry_ms: int = 1893456000000,  # 2030-01-01
    total_gb: int = 10737418240,
    limit_ip: int = 2,
) -> dict:
    return {
        "email": email,
        "enable": enable,
        "expiryTime": expiry_ms,
        "totalGB": total_gb,
        "limitIp": limit_ip,
    }


# ── transform_xui_user ─────────────────────────────────────────────


class TestTransformXuiUser:
    def test_happy_path(self, service):
        user = _make_xui_user(email="prefix_42_suffix", expiry_ms=1893456000000)
        result = service.transform_xui_user(user)

        assert result is not None
        assert result["username"] == f"{REMNASHOP_PREFIX}42"
        assert result["telegram_id"] == "42"
        assert result["status"] == SubscriptionStatus.ACTIVE
        assert result["expire_at"] == datetime.fromtimestamp(1893456000, tz=timezone.utc)
        assert result["traffic_limit_bytes"] == 10737418240
        assert result["hwid_device_limit"] == 2
        assert result["tag"] == IMPORTED_TAG

    def test_disabled_user_returns_none(self, service):
        user = _make_xui_user(enable=False)
        assert service.transform_xui_user(user) is None

    def test_no_digits_in_email_returns_none(self, service):
        user = _make_xui_user(email="no_digits_here")
        assert service.transform_xui_user(user) is None

    def test_empty_email_returns_none(self, service):
        user = _make_xui_user(email="")
        assert service.transform_xui_user(user) is None

    def test_missing_email_returns_none(self, service):
        user = {"enable": True}
        assert service.transform_xui_user(user) is None

    def test_zero_expiry_gives_far_future(self, service):
        user = _make_xui_user(expiry_ms=0)
        result = service.transform_xui_user(user)
        assert result is not None
        assert result["expire_at"] == datetime(2099, 1, 1, tzinfo=timezone.utc)

    def test_missing_expiry_gives_far_future(self, service):
        user = {"enable": True, "email": "user999"}
        result = service.transform_xui_user(user)
        assert result is not None
        assert result["expire_at"] == datetime(2099, 1, 1, tzinfo=timezone.utc)

    def test_defaults_for_missing_optional_fields(self, service):
        user = {"enable": True, "email": "user55", "expiryTime": 1893456000000}
        result = service.transform_xui_user(user)
        assert result is not None
        assert result["traffic_limit_bytes"] == 0
        assert result["hwid_device_limit"] == 1

    def test_extracts_first_number_from_email(self, service):
        user = _make_xui_user(email="abc99xyz77")
        result = service.transform_xui_user(user)
        assert result is not None
        assert result["telegram_id"] == "99"


# ── transform_xui_users ────────────────────────────────────────────


class TestTransformXuiUsers:
    def test_filters_out_none_results(self, service):
        users = [
            _make_xui_user(email="user1"),
            _make_xui_user(enable=False),  # disabled -> None
            _make_xui_user(email="nodigits"),  # no digits -> None
        ]
        result = service.transform_xui_users(users)
        assert len(result) == 1
        assert result[0]["telegram_id"] == "1"

    def test_empty_input(self, service):
        assert service.transform_xui_users([]) == []

    def test_all_invalid(self, service):
        users = [_make_xui_user(enable=False), _make_xui_user(email="abc")]
        assert service.transform_xui_users(users) == []


# ── split_active_and_expired ────────────────────────────────────────


class TestSplitActiveAndExpired:
    def test_splits_correctly(self, service):
        now = datetime.now(tz=timezone.utc)
        users = [
            {"name": "active", "expire_at": datetime(2099, 1, 1, tzinfo=timezone.utc)},
            {"name": "expired", "expire_at": datetime(2020, 1, 1, tzinfo=timezone.utc)},
        ]
        active, expired = service.split_active_and_expired(users)
        assert len(active) == 1
        assert active[0]["name"] == "active"
        assert len(expired) == 1
        assert expired[0]["name"] == "expired"

    def test_missing_expire_at_goes_to_expired(self, service):
        users = [{"name": "no_expiry"}]
        active, expired = service.split_active_and_expired(users)
        assert len(active) == 0
        assert len(expired) == 1

    def test_non_datetime_expire_at_goes_to_expired(self, service):
        users = [{"name": "string_date", "expire_at": "2099-01-01"}]
        active, expired = service.split_active_and_expired(users)
        assert len(active) == 0
        assert len(expired) == 1

    def test_empty_input(self, service):
        active, expired = service.split_active_and_expired([])
        assert active == []
        assert expired == []

    def test_all_active(self, service):
        users = [
            {"expire_at": datetime(2099, 1, 1, tzinfo=timezone.utc)},
            {"expire_at": datetime(2098, 1, 1, tzinfo=timezone.utc)},
        ]
        active, expired = service.split_active_and_expired(users)
        assert len(active) == 2
        assert len(expired) == 0

    def test_all_expired(self, service):
        users = [
            {"expire_at": datetime(2020, 1, 1, tzinfo=timezone.utc)},
            {"expire_at": datetime(2019, 1, 1, tzinfo=timezone.utc)},
        ]
        active, expired = service.split_active_and_expired(users)
        assert len(active) == 0
        assert len(expired) == 2


# ── _xui_validate_db ───────────────────────────────────────────────


class TestXuiValidateDb:
    def test_valid_db_with_inbounds(self, service, xui_db):
        _insert_inbound(xui_db, 1, [_make_xui_user()])
        assert service._xui_validate_db(xui_db) is True

    def test_empty_inbounds_table(self, service, xui_db):
        assert service._xui_validate_db(xui_db) is False

    def test_nonexistent_file(self, service, tmp_path):
        assert service._xui_validate_db(tmp_path / "nonexistent.db") is False

    def test_corrupt_file(self, service, tmp_path):
        bad_db = tmp_path / "corrupt.db"
        bad_db.write_text("not a database")
        assert service._xui_validate_db(bad_db) is False


# ── _xui_get_inbound_with_most_clients ──────────────────────────────


class TestXuiGetInboundWithMostClients:
    def test_selects_inbound_with_most_clients(self, service, xui_db):
        _insert_inbound(xui_db, 1, [_make_xui_user()])
        _insert_inbound(xui_db, 2, [_make_xui_user(), _make_xui_user()])
        _insert_inbound(xui_db, 3, [_make_xui_user()])

        assert service._xui_get_inbound_with_most_clients(xui_db) == 2

    def test_single_inbound(self, service, xui_db):
        _insert_inbound(xui_db, 5, [_make_xui_user()])
        assert service._xui_get_inbound_with_most_clients(xui_db) == 5

    def test_skips_invalid_json(self, service, xui_db):
        conn = sqlite3.connect(xui_db)
        conn.execute("INSERT INTO inbounds (id, settings) VALUES (?, ?)", (1, "not json"))
        conn.commit()
        conn.close()
        _insert_inbound(xui_db, 2, [_make_xui_user()])

        assert service._xui_get_inbound_with_most_clients(xui_db) == 2

    def test_skips_inbound_without_clients_list(self, service, xui_db):
        conn = sqlite3.connect(xui_db)
        conn.execute(
            "INSERT INTO inbounds (id, settings) VALUES (?, ?)",
            (1, json.dumps({"clients": "not a list"})),
        )
        conn.commit()
        conn.close()
        _insert_inbound(xui_db, 2, [_make_xui_user()])

        assert service._xui_get_inbound_with_most_clients(xui_db) == 2

    def test_no_valid_inbounds_raises(self, service, xui_db):
        conn = sqlite3.connect(xui_db)
        conn.execute("INSERT INTO inbounds (id, settings) VALUES (?, ?)", (1, "bad json"))
        conn.commit()
        conn.close()

        with pytest.raises(ValueError, match="No valid inbounds"):
            service._xui_get_inbound_with_most_clients(xui_db)

    def test_empty_table_raises(self, service, xui_db):
        with pytest.raises(ValueError, match="No valid inbounds"):
            service._xui_get_inbound_with_most_clients(xui_db)


# ── _xui_get_users_from_inbound ────────────────────────────────────


class TestXuiGetUsersFromInbound:
    def test_returns_clients_list(self, service, xui_db):
        clients = [_make_xui_user(email="a1"), _make_xui_user(email="b2")]
        _insert_inbound(xui_db, 1, clients)

        result = service._xui_get_users_from_inbound(xui_db, 1)
        assert len(result) == 2
        assert result[0]["email"] == "a1"

    def test_missing_inbound_raises(self, service, xui_db):
        with pytest.raises(ValueError, match="not found"):
            service._xui_get_users_from_inbound(xui_db, 999)

    def test_invalid_json_raises(self, service, xui_db):
        conn = sqlite3.connect(xui_db)
        conn.execute("INSERT INTO inbounds (id, settings) VALUES (?, ?)", (1, "bad"))
        conn.commit()
        conn.close()

        with pytest.raises(ValueError, match="Invalid JSON"):
            service._xui_get_users_from_inbound(xui_db, 1)

    def test_non_list_clients_raises(self, service, xui_db):
        conn = sqlite3.connect(xui_db)
        conn.execute(
            "INSERT INTO inbounds (id, settings) VALUES (?, ?)",
            (1, json.dumps({"clients": "string_not_list"})),
        )
        conn.commit()
        conn.close()

        with pytest.raises(TypeError, match="Invalid clients format"):
            service._xui_get_users_from_inbound(xui_db, 1)

    def test_missing_clients_key_raises(self, service, xui_db):
        conn = sqlite3.connect(xui_db)
        conn.execute(
            "INSERT INTO inbounds (id, settings) VALUES (?, ?)",
            (1, json.dumps({"no_clients": []})),
        )
        conn.commit()
        conn.close()

        with pytest.raises(TypeError, match="Invalid clients format"):
            service._xui_get_users_from_inbound(xui_db, 1)


# ── get_users_from_xui (integration of internal methods) ───────────


class TestGetUsersFromXui:
    def test_happy_path_end_to_end(self, service, xui_db):
        clients = [
            _make_xui_user(email="tg_100", expiry_ms=1893456000000),
            _make_xui_user(email="tg_200", expiry_ms=1893456000000),
            _make_xui_user(enable=False, email="tg_300"),  # disabled, filtered
        ]
        _insert_inbound(xui_db, 1, clients)

        result = service.get_users_from_xui(xui_db)
        assert len(result) == 2
        telegram_ids = {u["telegram_id"] for u in result}
        assert telegram_ids == {"100", "200"}

    def test_invalid_db_raises(self, service, tmp_path):
        bad_path = tmp_path / "missing.db"
        with pytest.raises(ValueError, match="Invalid or inaccessible"):
            service.get_users_from_xui(bad_path)

    def test_picks_inbound_with_most_clients(self, service, xui_db):
        _insert_inbound(xui_db, 1, [_make_xui_user(email="u1")])
        _insert_inbound(xui_db, 2, [
            _make_xui_user(email="u10"),
            _make_xui_user(email="u20"),
            _make_xui_user(email="u30"),
        ])

        result = service.get_users_from_xui(xui_db)
        assert len(result) == 3
