from __future__ import annotations

import hashlib

try:
    from Crypto.Hash import keccak as crypto_keccak  # type: ignore
except Exception:  # pragma: no cover - optional dependency path
    crypto_keccak = None

KNOWN_SELECTORS = {
    "execute(address,uint256,bytes,bytes32,string)": "0x9bd11128",
    "deposit(uint256,uint32)": "0x2b2dfd2c",
    "sendRawAction(bytes)": "0x17938e13",
    "settleDailyNav(uint64,uint256,bytes32)": "0x8c9eab0d",
    "submitReport(address,address,string)": "0xe38a6a53",
    "x(uint64,bool)": "0xe3733521",
    "x(address,uint64,uint64)": "0xb0ec4ef9",
    "x(address,string)": "0xa82b5a89",
    "acceptToken()": "0x5510f804",
    "coreDepositWallet()": "0xf3be0518",
    "usdcTokenIndex()": "0x15dc074d",
    "spotDestinationDex()": "0x98ab67cb",
    "coreUsdcWeiPerAssetUnit()": "0xdcc410ef",
    "trackedCoreUsdc()": "0x25f25635",
    "accountedEvmUsdc()": "0x2424d721",
    "unaccountedAcceptTokenAssets()": "0x7dbb6d8b",
    "pendingCoreDeposits()": "0x0aa64d3d",
    "pendingCoreWithdrawals()": "0xf31f268a",
    "reservedRedeemAmount()": "0xef273a78",
    "lastSettledDay()": "0x80bc7175",
    "lastSettledTotalAssets()": "0xf490dd72",
    "lastSettledSharePrice()": "0x6bddd479",
    "initialSharePrice()": "0x5f3e364a",
    "totalSupply()": "0x18160ddd",
    "balanceOf(address)": "0x70a08231",
}



def keccak256(data: bytes) -> bytes:
    if crypto_keccak is not None:
        h = crypto_keccak.new(digest_bits=256)
        h.update(data)
        return h.digest()
    # Python stdlib exposes NIST SHA3, not Ethereum Keccak. This fallback is useful for tests
    # but production should install pycryptodome or use an external signer/encoder.
    return hashlib.sha3_256(data).digest()


def selector(signature: str) -> str:
    if crypto_keccak is None and signature in KNOWN_SELECTORS:
        return KNOWN_SELECTORS[signature]
    return "0x" + keccak256(signature.encode())[:4].hex()


def decode_uint(value: str) -> int:
    data = value[2:] if value.startswith("0x") else value
    if not data:
        return 0
    return int(data[-64:], 16)


def decode_address(value: str) -> str:
    data = value[2:] if value.startswith("0x") else value
    if len(data) < 64:
        raise ValueError("invalid ABI address response")
    return "0x" + data[-40:]


def encode_uint(value: int) -> str:
    if value < 0:
        raise ValueError("uint cannot be negative")
    return value.to_bytes(32, "big").hex()


def encode_bool(value: bool) -> str:
    return encode_uint(1 if value else 0)


def encode_address(value: str) -> str:
    if not value.startswith("0x") or len(value) != 42:
        raise ValueError(f"invalid address: {value}")
    return (b"\x00" * 12 + bytes.fromhex(value[2:])).hex()


def encode_bytes32(value: str) -> str:
    if value.startswith("0x"):
        raw = bytes.fromhex(value[2:])
    else:
        raw = value.encode()
    if len(raw) > 32:
        raise ValueError("bytes32 too long")
    return raw.ljust(32, b"\x00").hex()


def encode_string(value: str) -> str:
    data = value.encode()
    return encode_bytes_data(data)


def encode_bytes(value: str | bytes) -> str:
    if isinstance(value, bytes):
        data = value
    else:
        text = str(value)
        data = bytes.fromhex(text[2:] if text.startswith("0x") else text)
    return encode_bytes_data(data)


def encode_bytes_data(data: bytes) -> str:
    padded_len = ((len(data) + 31) // 32) * 32
    return encode_uint(len(data)) + data.ljust(padded_len, b"\x00").hex()


def calldata(signature: str, args: list[tuple[str, object]]) -> str:
    """Encode a small subset of ABI used by the executor CLI.

    Supported types: address, uint256, uint64, uint32, bool, bytes32, string, bytes.
    """
    static_parts: list[str] = []
    dynamic_parts: list[str] = []
    head_size = 32 * len(args)
    for typ, value in args:
        if typ == "address":
            static_parts.append(encode_address(str(value)))
        elif typ in {"uint256", "uint64", "uint32", "uint16"}:
            static_parts.append(encode_uint(int(value)))
        elif typ == "bool":
            static_parts.append(encode_bool(bool(value)))
        elif typ == "bytes32":
            static_parts.append(encode_bytes32(str(value)))
        elif typ == "string":
            offset = head_size + sum(len(part) // 2 for part in dynamic_parts)
            static_parts.append(encode_uint(offset))
            dynamic_parts.append(encode_string(str(value)))
        elif typ == "bytes":
            offset = head_size + sum(len(part) // 2 for part in dynamic_parts)
            static_parts.append(encode_uint(offset))
            dynamic_parts.append(encode_bytes(value if isinstance(value, bytes) else str(value)))
        else:
            raise ValueError(f"unsupported ABI type: {typ}")
    return selector(signature) + "".join(static_parts) + "".join(dynamic_parts)
