from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class CryptoAsset:
    id: str
    label: str
    chain: str
    token: str


CRYPTO_ASSETS: Final[tuple[CryptoAsset, ...]] = (
    CryptoAsset(id="usdt-tron", label="₮ USDT · TRON", chain="tron", token="USDT"),
    CryptoAsset(id="usdt-ton", label="₮ USDT · TON", chain="ton", token="USDT"),
    CryptoAsset(id="ton", label="💎 TON", chain="ton", token="TON"),
    CryptoAsset(id="usdt-eth", label="₮ USDT · Ethereum", chain="ethereum", token="USDT"),
    CryptoAsset(id="usdc-eth", label="$ USDC · Ethereum", chain="ethereum", token="USDC"),
    CryptoAsset(id="eth", label="Ξ ETH", chain="ethereum", token="ETH"),
    CryptoAsset(id="sol", label="◎ SOL", chain="solana", token="SOL"),
    CryptoAsset(id="usdc-sol", label="$ USDC · Solana", chain="solana", token="USDC"),
    CryptoAsset(id="usdt-bsc", label="₮ USDT · BSC", chain="bsc", token="USDT"),
    CryptoAsset(id="bnb", label="🟡 BNB", chain="bsc", token="BNB"),
    CryptoAsset(id="pol", label="🟣 POL · Polygon", chain="polygon", token="POL"),
    CryptoAsset(id="usdc-base", label="$ USDC · Base", chain="base", token="USDC"),
    CryptoAsset(id="usdc-arb", label="$ USDC · Arbitrum", chain="arbitrum", token="USDC"),
    CryptoAsset(id="usdc-op", label="$ USDC · Optimism", chain="optimism", token="USDC"),
    CryptoAsset(id="avax", label="🔺 AVAX", chain="avalanche", token="AVAX"),
)

CRYPTO_ASSETS_BY_ID: Final[dict[str, CryptoAsset]] = {asset.id: asset for asset in CRYPTO_ASSETS}


def get_crypto_asset(asset_id: str) -> CryptoAsset:
    return CRYPTO_ASSETS_BY_ID[asset_id]
