"""AES-256-GCM 凭证加解密工具（阶段 2）。

设计原则：
  1. 单文件、零业务依赖：仅依赖 `cryptography` 库与 `config.get_settings()`。
  2. 主密钥外部托管：开发环境用环境变量 `ENCRYPTION_KEY_B64`；生产建议接入
     KMS（AWS / 阿里 / Vault），通过 sidecar 写入同名环境变量即可。
  3. 存储格式：`version(1) || key_id(1) || nonce(12) || ciphertext || tag(16)`，
     共 30 字节 overhead，全部以 bytes 形式写入 LONGBLOB。
  4. 密钥轮换预留：`key_id` 字段标记本条密文使用哪份密钥；新增密钥时旧密钥
     仍可解密历史数据，写入时使用主密钥。

⚠ 安全要点：
  - 主密钥必须 32 字节（AES-256），通过 base64 编码后写入环境变量。
  - 同一 nonce 在同一密钥下**绝对不能重复使用**：本实现每次随机 12 字节。
  - 解密失败抛 CryptoError，不暴露密文细节；上层应捕获记录但不要回显。

详见 docs/saas-transformation.md §7.5、§13。
"""
from __future__ import annotations

import base64
import os
import secrets
from functools import lru_cache
from typing import Optional

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "缺少 cryptography 库，请执行 `pip install cryptography>=42.0`"
    ) from exc

from loguru import logger


# ── 常量 ──────────────────────────────────────────────────────────
_VERSION: int = 1
_NONCE_LEN: int = 12   # AES-GCM 推荐 96 bit
_TAG_LEN: int = 16     # AES-GCM 标准 128 bit
_KEY_LEN: int = 32     # AES-256


class CryptoError(Exception):
    """加解密失败基类，不携带敏感上下文。"""


class KeyNotConfiguredError(CryptoError):
    """未配置主密钥；不应在生产启动后还出现。"""


# ── 密钥加载 ──────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_keyring() -> dict[int, bytes]:
    """加载所有可用密钥。

    支持两种来源（优先级从高到低）：
      1. `ENCRYPTION_KEY_B64` 环境变量 / settings（单密钥，key_id=1）
      2. `ENCRYPTION_KEYS_JSON` 环境变量（密钥轮换，格式见下）

    `ENCRYPTION_KEYS_JSON` 示例（base64 后再 JSON）：
        {"1": "AAAA...32B base64", "2": "BBBB...32B base64"}
      主密钥默认为最大数字 ID。
    """
    keyring: dict[int, bytes] = {}

    # 主密钥（单密钥模式，最常见）
    from config import get_settings
    try:
        b64 = getattr(get_settings(), "encryption_key_b64", "") or os.getenv("ENCRYPTION_KEY_B64", "")
    except Exception:
        b64 = os.getenv("ENCRYPTION_KEY_B64", "")
    if b64:
        raw = _decode_key(b64, source="ENCRYPTION_KEY_B64")
        keyring[1] = raw

    # 轮换模式（多密钥）
    import json as _json
    keys_json = os.getenv("ENCRYPTION_KEYS_JSON", "")
    if keys_json:
        try:
            kj = _json.loads(keys_json)
            for k, v in kj.items():
                kid = int(k)
                keyring[kid] = _decode_key(v, source=f"ENCRYPTION_KEYS_JSON[{k}]")
        except Exception as e:
            logger.error(f"ENCRYPTION_KEYS_JSON 解析失败：{e}")

    return keyring


def _decode_key(b64: str, source: str) -> bytes:
    """把 base64 字符串解码为 32 字节密钥；长度不对则报错。"""
    try:
        raw = base64.b64decode(b64.strip())
    except Exception as e:
        raise KeyNotConfiguredError(f"{source} base64 解码失败") from e
    if len(raw) != _KEY_LEN:
        raise KeyNotConfiguredError(
            f"{source} 长度错误：期望 {_KEY_LEN} 字节，实际 {len(raw)}"
        )
    return raw


def _primary_key_id() -> int:
    keyring = _load_keyring()
    if not keyring:
        raise KeyNotConfiguredError(
            "未配置加密主密钥；请设置环境变量 ENCRYPTION_KEY_B64"
            "（32 字节随机数 base64 编码）"
        )
    return max(keyring.keys())


def _key_for(key_id: int) -> bytes:
    keyring = _load_keyring()
    if key_id not in keyring:
        raise CryptoError(f"未知 key_id={key_id}（可能是旧密钥被移除）")
    return keyring[key_id]


# ── 公共 API ──────────────────────────────────────────────────────

def encrypt(plain: str | bytes, *, aad: Optional[bytes] = None) -> bytes:
    """加密字符串/字节，返回 self-describing 的二进制 blob。

    参数:
      plain: 明文（str 将以 UTF-8 编码）。
      aad: 可选的附加认证数据（不加密但参与完整性校验，例如绑定 tenant_id 防换密文）。

    返回:
      `version(1) || key_id(1) || nonce(12) || ciphertext || tag(16)`
    """
    if isinstance(plain, str):
        plain_b = plain.encode("utf-8")
    else:
        plain_b = bytes(plain)

    key_id = _primary_key_id()
    key = _key_for(key_id)
    nonce = secrets.token_bytes(_NONCE_LEN)
    aesgcm = AESGCM(key)
    ct_with_tag = aesgcm.encrypt(nonce, plain_b, aad)  # 末尾 16 字节即 tag
    if key_id > 255 or key_id < 0:
        raise CryptoError("key_id 越界（仅支持 0~255）")
    header = bytes([_VERSION, key_id])
    return header + nonce + ct_with_tag


def decrypt(blob: bytes | bytearray | memoryview, *, aad: Optional[bytes] = None) -> str:
    """解密 `encrypt()` 产物，返回 UTF-8 字符串。"""
    data = bytes(blob)
    if len(data) < 2 + _NONCE_LEN + _TAG_LEN:
        raise CryptoError("密文长度不足")
    version = data[0]
    key_id = data[1]
    if version != _VERSION:
        raise CryptoError(f"不支持的密文版本：{version}")
    nonce = data[2 : 2 + _NONCE_LEN]
    ct_with_tag = data[2 + _NONCE_LEN :]
    key = _key_for(key_id)
    aesgcm = AESGCM(key)
    try:
        plain = aesgcm.decrypt(nonce, ct_with_tag, aad)
    except Exception as e:
        raise CryptoError("解密失败（密钥不匹配或密文被篡改）") from e
    return plain.decode("utf-8")


def is_configured() -> bool:
    """快速判断是否配置了密钥；无需抛错的探测路径使用。"""
    try:
        return bool(_load_keyring())
    except Exception:
        return False


def generate_key_b64() -> str:
    """生成一个新的随机主密钥（32 字节 base64）。运维侧使用：

        python -c "from core.crypto import generate_key_b64; print(generate_key_b64())"
    """
    return base64.b64encode(secrets.token_bytes(_KEY_LEN)).decode("ascii")


# ── 自检 ──────────────────────────────────────────────────────────

def selftest() -> bool:
    """启动时可调用，验证加解密链路正常；失败返回 False（由调用方决定是否致命）。"""
    if not is_configured():
        logger.warning("crypto.selftest: 未配置 ENCRYPTION_KEY_B64，跳过自检")
        return False
    try:
        sample = "adpilot-selftest-\u4e2d\u6587"
        blob = encrypt(sample, aad=b"selftest")
        back = decrypt(blob, aad=b"selftest")
        assert back == sample, "round-trip mismatch"
        return True
    except Exception as e:
        logger.error(f"crypto.selftest 失败：{e}")
        return False
