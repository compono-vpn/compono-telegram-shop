from pydantic import SecretStr

from .base import TrackableDto


class AmneziaWGConfigDto(TrackableDto):
    private_key: SecretStr
    address: str
    dns: str
    mtu: int
    server_public_key: str
    endpoint: str
    allowed_ips: str
    persistent_keepalive: int
    jc: int
    jmin: int
    jmax: int
    s1: int
    s2: int
    h1: int
    h2: int
    h3: int
    h4: int


class Hysteria2ConfigDto(TrackableDto):
    uri: SecretStr
    server: str
    auth: SecretStr
    sni: str
    insecure: bool


class CallsBundleDto(TrackableDto):
    amneziawg: AmneziaWGConfigDto
    hysteria2: Hysteria2ConfigDto
