"""微软正版登录（OAuth 2.0 设备代码流）与账户存储。

流程：Microsoft OAuth → Xbox Live → XSTS → Minecraft Services → 玩家档案。
不保存微软账号密码，只保存可撤销的 refresh token（DPAPI 加密）。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

import requests
from PyQt6.QtCore import QObject, pyqtSignal

from .. import MINECRAFT_USER_AGENT
from ..api.types import Account
from .paths import data_root
from .secure import read_secure_json, write_secure_json

log = logging.getLogger("mcs.auth")

DEVICE_CODE_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
XBL_URL = "https://user.auth.xboxlive.com/user/authenticate"
XSTS_URL = "https://xsts.auth.xboxlive.com/xsts/authorize"
MC_LOGIN_URL = "https://api.minecraftservices.com/authentication/login_with_xbox"
MC_PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"
SCOPE = "XboxLive.signin offline_access"

XSTS_MESSAGES = {
    2148916227: "该账号已被 Xbox Live 封禁。",
    2148916233: "该微软账号还没有 Xbox 账户，请先在 xbox.com 创建。",
    2148916235: "当前国家/地区不支持 Xbox Live。",
    2148916236: "该账号需要进行成人验证（Xbox 家长控制）。",
    2148916237: "该账号需要进行成人验证（Xbox 家长控制）。",
    2148916238: "该账号是未成年人账号，需要由家庭组批准。",
}


class AuthError(RuntimeError):
    pass


# 公共 Azure 应用客户端 ID（device code 流程）。它来自开源项目 mcauth3，
# 仅作为开箱即用的默认值；正式分发时建议在设置中替换为自己的 Azure 应用 ID。
DEFAULT_CLIENT_ID = "4a07b708-b86d-4365-a55f-f4f23ecb85ab"


class MicrosoftAuth:
    def __init__(self, client_id: str) -> None:
        self.client_id = client_id or DEFAULT_CLIENT_ID
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": MINECRAFT_USER_AGENT, "Accept": "application/json"})

    # --------------------------------------------------------- device code
    def request_device_code(self, language: str = "zh-CN") -> dict[str, Any]:
        resp = self.session.post(
            DEVICE_CODE_URL,
            data={"client_id": self.client_id, "scope": SCOPE},
            params={"mkt": language},
            timeout=30,
        )
        if resp.status_code >= 400:
            raise AuthError(
                f"无法获取设备代码（HTTP {resp.status_code}）。请检查 Microsoft 客户端 ID 是否正确。\n{resp.text[:300]}"
            )
        return resp.json()

    def poll_device_code(
        self,
        device_code: str,
        interval: int,
        expires_in: int,
        *,
        cancelled: Callable[[], bool] | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        deadline = time.time() + max(60, int(expires_in))
        delay = max(2, int(interval))
        while time.time() < deadline:
            if cancelled and cancelled():
                raise AuthError("登录已取消。")
            time.sleep(delay)
            if cancelled and cancelled():
                raise AuthError("登录已取消。")
            resp = self.session.post(
                TOKEN_URL,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": self.client_id,
                    "device_code": device_code,
                },
                timeout=30,
            )
            try:
                payload = resp.json()
            except ValueError:
                payload = {}
            if resp.status_code < 400 and "access_token" in payload:
                return payload
            error = str(payload.get("error") or "")
            if error == "authorization_pending":
                if on_status:
                    on_status("等待你在浏览器中完成登录…")
                continue
            if error == "slow_down":
                delay += 5
                continue
            if error == "authorization_declined":
                raise AuthError("你拒绝了本次登录授权。")
            if error in ("expired_token", "code_expired"):
                raise AuthError("设备代码已过期，请重新登录。")
            if error:
                desc = payload.get("error_description") or ""
                raise AuthError(f"登录失败：{error}\n{desc[:300]}")
            raise AuthError(f"登录请求失败（HTTP {resp.status_code}）。")
        raise AuthError("等待登录超时，请重试。")

    # ---------------------------------------------------------- token chain
    def _xbox_token(self, ms_access_token: str) -> dict[str, Any]:
        resp = self.session.post(
            XBL_URL,
            json={
                "Properties": {
                    "AuthMethod": "RPS",
                    "SiteName": "user.auth.xboxlive.com",
                    "RpsTicket": f"d={ms_access_token}",
                },
                "RelyingParty": "http://auth.xboxlive.com",
                "TokenType": "JWT",
            },
            timeout=30,
        )
        if resp.status_code >= 400:
            raise AuthError(f"Xbox Live 认证失败（HTTP {resp.status_code}）：{resp.text[:200]}")
        return resp.json()

    def _xsts_token(self, xbl_token: str) -> dict[str, Any]:
        resp = self.session.post(
            XSTS_URL,
            json={
                "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl_token]},
                "RelyingParty": "rp://api.minecraftservices.com/",
                "TokenType": "JWT",
            },
            timeout=30,
        )
        if resp.status_code >= 400:
            try:
                xerr = int(resp.json().get("XErr", 0))
            except Exception:
                xerr = 0
            raise AuthError(XSTS_MESSAGES.get(xerr, f"XSTS 认证失败（XErr={xerr}）。"))
        return resp.json()

    def _minecraft_token(self, xsts_token: str, uhs: str) -> dict[str, Any]:
        resp = self.session.post(
            MC_LOGIN_URL,
            json={"identityToken": f"XBL3.0 x={uhs};{xsts_token}"},
            timeout=30,
        )
        if resp.status_code >= 400:
            raise AuthError(f"Minecraft 认证失败（HTTP {resp.status_code}）：{resp.text[:300]}")
        return resp.json()

    def _profile(self, access_token: str) -> dict[str, Any]:
        resp = self.session.get(
            MC_PROFILE_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
        )
        if resp.status_code == 404:
            raise AuthError("该账号没有 Minecraft: Java Edition 的所有权。")
        if resp.status_code >= 400:
            raise AuthError(f"无法获取玩家档案（HTTP {resp.status_code}）。")
        return resp.json()

    def _finish(self, ms_token: dict[str, Any], refresh_token: str = "") -> Account:
        xbl = self._xbox_token(ms_token["access_token"])
        xsts = self._xsts_token(xbl["Token"])
        uhs = xbl["DisplayClaims"]["xui"][0]["uhs"]
        mc = self._minecraft_token(xsts["Token"], uhs)
        profile = self._profile(mc["access_token"])
        skin = ""
        try:
            skins = profile.get("skins") or []
            if skins:
                skin = skins[0].get("url", "")
        except Exception:
            pass
        return Account(
            id=profile.get("id") or profile.get("name", ""),
            name=profile.get("name", ""),
            uuid=profile.get("id", ""),
            access_token=mc["access_token"],
            refresh_token=refresh_token or ms_token.get("refresh_token", ""),
            expires_at=time.time() + int(mc.get("expires_in") or 86400),
            kind="microsoft",
            skin_url=skin,
        )

    def login_with_device_code(
        self,
        *,
        on_device_code: Callable[[dict[str, Any]], None] | None = None,
        on_status: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> Account:
        code = self.request_device_code()
        if on_device_code:
            on_device_code(code)
        token = self.poll_device_code(
            code["device_code"],
            int(code.get("interval", 5)),
            int(code.get("expires_in", 900)),
            cancelled=cancelled,
            on_status=on_status,
        )
        return self._finish(token, token.get("refresh_token", ""))

    def refresh(self, account: Account) -> Account:
        if not account.refresh_token:
            raise AuthError("登录已过期，并且没有可用的刷新令牌，请重新登录。")
        resp = self.session.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "refresh_token": account.refresh_token,
                "grant_type": "refresh_token",
                "scope": SCOPE,
            },
            timeout=30,
        )
        if resp.status_code >= 400:
            raise AuthError("登录已过期，刷新失败，请重新登录。")
        token = resp.json()
        new_account = self._finish(token, token.get("refresh_token") or account.refresh_token)
        return new_account


class AccountStore(QObject):
    accounts_changed = pyqtSignal()
    current_changed = pyqtSignal(object)

    def __init__(self, path=None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._path = path or (data_root() / "accounts.dat")
        self._lock = threading.RLock()
        self._accounts: list[Account] = []
        self._current_id = ""
        self._load()

    # ------------------------------------------------------------------- io
    def _load(self) -> None:
        data = read_secure_json(self._path, {})
        try:
            for raw in data.get("accounts", []):
                self._accounts.append(Account(**{k: raw.get(k) for k in Account.__dataclass_fields__}))
            self._current_id = str(data.get("current_id") or "")
        except Exception:
            log.exception("账户数据损坏，已忽略")
            self._accounts = []
        if not self._current_id and self._accounts:
            self._current_id = self._accounts[0].id

    def _save(self) -> None:
        payload = {
            "version": 1,
            "current_id": self._current_id,
            "accounts": [
                {
                    "id": a.id, "name": a.name, "uuid": a.uuid,
                    "access_token": a.access_token, "refresh_token": a.refresh_token,
                    "expires_at": a.expires_at, "kind": a.kind, "skin_url": a.skin_url,
                }
                for a in self._accounts
            ],
        }
        try:
            write_secure_json(self._path, payload)
        except Exception:
            log.exception("保存账户失败")

    # --------------------------------------------------------------- access
    @property
    def accounts(self) -> list[Account]:
        with self._lock:
            return list(self._accounts)

    @property
    def current(self) -> Account | None:
        with self._lock:
            for account in self._accounts:
                if account.id == self._current_id:
                    return account
            return self._accounts[0] if self._accounts else None

    def set_current(self, account_id: str) -> None:
        with self._lock:
            if not any(a.id == account_id for a in self._accounts):
                return
            self._current_id = account_id
            self._save()
        self.current_changed.emit(self.current)
        self.accounts_changed.emit()

    def add(self, account: Account, make_current: bool = True) -> None:
        with self._lock:
            for index, existing in enumerate(self._accounts):
                if existing.id == account.id:
                    self._accounts[index] = account
                    break
            else:
                self._accounts.append(account)
            if make_current or not self._current_id:
                self._current_id = account.id
            self._save()
        self.current_changed.emit(self.current)
        self.accounts_changed.emit()

    def update(self, account: Account) -> None:
        with self._lock:
            for index, existing in enumerate(self._accounts):
                if existing.id == account.id:
                    self._accounts[index] = account
                    break
            else:
                self._accounts.append(account)
            self._save()
        self.current_changed.emit(self.current)

    def remove(self, account_id: str) -> None:
        with self._lock:
            self._accounts = [a for a in self._accounts if a.id != account_id]
            if self._current_id == account_id:
                self._current_id = self._accounts[0].id if self._accounts else ""
            self._save()
        self.current_changed.emit(self.current)
        self.accounts_changed.emit()

    def sign_out(self) -> None:
        account = self.current
        if account:
            self.remove(account.id)

    def refresh_current(self, client_id: str) -> Account:
        account = self.current
        if account is None:
            raise AuthError("尚未登录。")
        refreshed = MicrosoftAuth(client_id).refresh(account)
        self.update(refreshed)
        return refreshed
