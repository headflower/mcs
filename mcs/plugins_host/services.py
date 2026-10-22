"""插件间共享服务注册表。

核心不依赖任何具体服务；插件通过 `ctx.services.register(...)` 暴露能力，
其它插件用 `ctx.services.get("java")` 取用。卸载时按名字注销，后加载的
插件无法访问已卸载插件的服务。
"""

from __future__ import annotations

from typing import Any, Iterator


class ServiceRegistry:
    def __init__(self) -> None:
        self._services: dict[str, Any] = {}
        self._owners: dict[str, str] = {}

    def register(self, name: str, service: Any, owner: str = "") -> Any:
        if not name:
            raise ValueError("服务名不能为空")
        if name in self._services and self._services[name] is not service:
            raise KeyError(f"服务 {name!r} 已被其它插件注册")
        self._services[name] = service
        self._owners[name] = owner
        return service

    def unregister(self, name: str, service: Any = None) -> None:
        current = self._services.get(name)
        if current is None:
            return
        if service is not None and current is not service:
            return
        self._services.pop(name, None)
        self._owners.pop(name, None)

    def unregister_owner(self, owner: str) -> None:
        if not owner:
            return
        for name in [n for n, value in self._owners.items() if value == owner]:
            self.unregister(name)

    def owner_of(self, name: str) -> str:
        return self._owners.get(name, "")

    def get(self, name: str, default: Any = None) -> Any:
        return self._services.get(name, default)

    def require(self, name: str) -> Any:
        service = self._services.get(name)
        if service is None:
            raise LookupError(f"所需服务 {name!r} 尚未就绪，请确认对应插件已启用")
        return service

    def __contains__(self, name: object) -> bool:
        return name in self._services

    def __iter__(self) -> Iterator[str]:
        return iter(self._services)

    def names(self) -> list[str]:
        return sorted(self._services)


class PluginServiceView:
    """绑定插件 id 的视图，自动记录服务归属。"""

    def __init__(self, registry: ServiceRegistry, plugin_id: str) -> None:
        self._registry = registry
        self._plugin_id = plugin_id

    def register(self, name: str, service: Any) -> Any:
        return self._registry.register(name, service, owner=self._plugin_id)

    def unregister(self, name: str, service: Any = None) -> None:
        self._registry.unregister(name, service)

    def get(self, name: str, default: Any = None) -> Any:
        return self._registry.get(name, default)

    def require(self, name: str) -> Any:
        return self._registry.require(name)

    def names(self) -> list[str]:
        return self._registry.names()

    def __contains__(self, name: object) -> bool:
        return name in self._registry

    def __iter__(self) -> Iterator[str]:
        return iter(self._registry)
