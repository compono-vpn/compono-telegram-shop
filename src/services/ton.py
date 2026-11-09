import base64
import struct
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, urlparse

MAX_COMMENT_BYTES = 123


def _crc32c(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0x82F63B78 if crc & 1 else 0)
    return crc ^ 0xFFFFFFFF


def comment_payload(text: str) -> str:
    """A TON text comment as a one-cell BOC in base64: op 0 (32 bits), then the UTF-8 text."""
    data = b"\x00\x00\x00\x00" + text.encode()
    if len(text.encode()) > MAX_COMMENT_BYTES:
        raise ValueError("comment does not fit one cell")
    cell = bytes([0, len(data) * 2]) + data
    header = b"\xb5\xee\x9c\x72" + bytes([0x41, 1, 1, 1, 0, len(cell), 0])
    boc = header + cell
    return base64.b64encode(boc + struct.pack("<I", _crc32c(boc))).decode()


@dataclass(frozen=True)
class TonTransfer:
    address: str
    nanotons: int
    text: str


def parse_transfer_url(url: str) -> Optional[TonTransfer]:
    """ton://transfer/<address>?amount=<nanotons>&text=<comment>, as billing returns for TON."""
    parsed = urlparse(url or "")
    if parsed.scheme != "ton" or parsed.netloc != "transfer":
        return None
    address = parsed.path.strip("/")
    query = parse_qs(parsed.query)
    amount = (query.get("amount") or [""])[0]
    text = (query.get("text") or [""])[0]
    if not address or not amount.isdigit() or int(amount) <= 0 or not text:
        return None
    return TonTransfer(address=address, nanotons=int(amount), text=text)


def transaction(transfer: TonTransfer, valid_until: int) -> dict:
    """TON Connect sendTransaction request for one transfer with its comment."""
    return {
        "valid_until": valid_until,
        "messages": [
            {
                "address": transfer.address,
                "amount": str(transfer.nanotons),
                "payload": comment_payload(transfer.text),
            }
        ],
    }


def format_ton(nanotons: int) -> str:
    whole, frac = divmod(nanotons, 10**9)
    frac_text = f"{frac:09d}".rstrip("0")[:4]
    return f"{whole}.{frac_text} TON" if frac_text else f"{whole} TON"
