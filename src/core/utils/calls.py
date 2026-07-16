from io import BytesIO
from typing import Any, cast

from aiogram.types import BufferedInputFile
from PIL import Image
from qrcode import ERROR_CORRECT_H, QRCode  # type: ignore[attr-defined]

from src.core.constants import ASSETS_DIR
from src.models.dto.calls import AmneziaWGConfigDto


def render_amneziawg_conf(config: AmneziaWGConfigDto) -> str:
    return (
        "[Interface]\n"
        f"PrivateKey = {config.private_key.get_secret_value()}\n"
        f"Address = {config.address}\n"
        f"DNS = {config.dns}\n"
        f"MTU = {config.mtu}\n"
        f"Jc = {config.jc}\n"
        f"Jmin = {config.jmin}\n"
        f"Jmax = {config.jmax}\n"
        f"S1 = {config.s1}\n"
        f"S2 = {config.s2}\n"
        f"H1 = {config.h1}\n"
        f"H2 = {config.h2}\n"
        f"H3 = {config.h3}\n"
        f"H4 = {config.h4}\n"
        "\n"
        "[Peer]\n"
        f"PublicKey = {config.server_public_key}\n"
        f"Endpoint = {config.endpoint}\n"
        f"AllowedIPs = {config.allowed_ips}\n"
        f"PersistentKeepalive = {config.persistent_keepalive}\n"
    )


def generate_calls_qr(data: str, filename: str) -> BufferedInputFile:
    qr: Any = QRCode(
        version=1,
        error_correction=ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)

    qr_img_raw = qr.make_image(fill_color="black", back_color="white")
    qr_img: Image.Image
    if hasattr(qr_img_raw, "get_image"):
        qr_img = cast(Image.Image, qr_img_raw.get_image())
    else:
        qr_img = cast(Image.Image, qr_img_raw)
    qr_img = qr_img.convert("RGB")

    logo_path = ASSETS_DIR / "logo.png"
    if logo_path.exists():
        logo = Image.open(logo_path).convert("RGBA")
        qr_width, qr_height = qr_img.size
        logo_size = int(qr_width * 0.2)
        logo = logo.resize((logo_size, logo_size), resample=Image.Resampling.LANCZOS)
        pos = ((qr_width - logo_size) // 2, (qr_height - logo_size) // 2)
        qr_img.paste(logo, pos, mask=logo)

    buffer = BytesIO()
    qr_img.save(buffer, format="PNG")
    buffer.seek(0)
    return BufferedInputFile(file=buffer.getvalue(), filename=filename)
