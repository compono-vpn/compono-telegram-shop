"""Tests for AmneziaWG .conf rendering and QR generation for the Calls (beta) feature."""

from __future__ import annotations

from aiogram.types import BufferedInputFile

from src.core.utils.calls import generate_calls_qr, render_amneziawg_conf
from src.models.dto.calls import AmneziaWGConfigDto


def _make_config() -> AmneziaWGConfigDto:
    return AmneziaWGConfigDto(
        private_key="aGVsbG8td29ybGQ=",
        address="10.8.0.2/32",
        dns="1.1.1.1",
        mtu=1280,
        server_public_key="cHVibGljLWtleQ==",
        endpoint="calls.componovpn.com:51820",
        allowed_ips="0.0.0.0/0, ::/0",
        persistent_keepalive=25,
        jc=4,
        jmin=40,
        jmax=70,
        s1=30,
        s2=25,
        h1=1234567891,
        h2=1234567892,
        h3=1234567893,
        h4=1234567894,
    )


class TestRenderAmneziaWGConf:

    def test_renders_exact_template(self):
        conf = render_amneziawg_conf(_make_config())

        assert conf == (
            "[Interface]\n"
            "PrivateKey = aGVsbG8td29ybGQ=\n"
            "Address = 10.8.0.2/32\n"
            "DNS = 1.1.1.1\n"
            "MTU = 1280\n"
            "Jc = 4\n"
            "Jmin = 40\n"
            "Jmax = 70\n"
            "S1 = 30\n"
            "S2 = 25\n"
            "H1 = 1234567891\n"
            "H2 = 1234567892\n"
            "H3 = 1234567893\n"
            "H4 = 1234567894\n"
            "\n"
            "[Peer]\n"
            "PublicKey = cHVibGljLWtleQ==\n"
            "Endpoint = calls.componovpn.com:51820\n"
            "AllowedIPs = 0.0.0.0/0, ::/0\n"
            "PersistentKeepalive = 25\n"
        )

    def test_private_key_never_appears_unmasked_in_repr(self):
        config = _make_config()

        assert "aGVsbG8td29ybGQ=" not in repr(config)
        assert "aGVsbG8td29ybGQ=" not in str(config)


class TestGenerateCallsQr:

    def test_returns_buffered_input_file(self):
        qr = generate_calls_qr("hysteria2://auth@calls.componovpn.com:8443/", "test.png")

        assert isinstance(qr, BufferedInputFile)
        assert qr.filename == "test.png"
        assert len(qr.data) > 0
