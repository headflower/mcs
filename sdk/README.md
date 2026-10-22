# MCS Launcher 插件 SDK

启动器本身只保留三件事：**启动游戏、基础设置、正版登录**。其余能力全部是插件。
官方插件（游戏下载、模组下载、Java 运行时、原生接口）就是最好的参考实现。

## 快速开始

1. 新建目录，例如 `%APPDATA%\MCSLauncher\plugins\com.example.hello\`。
2. 放入 `plugin.json`：

   ```json
   {
     "id": "com.example.hello",
     "name": "Hello 插件",
     "version": "0.1.0",
     "api": 1,
     "kind": "python",
     "entry": "plugin.py",
     "description": "我的第一个 MCS 插件"
   }
   ```

3. 放入 `plugin.py`，提供 `setup(context)`，返回一个可选的实例；
   宿主会随后调用 `on_load(context)`（不要自己调用两次）：

   ```python
   def setup(ctx):
       return HelloPlugin()

   class HelloPlugin:
       def on_load(self, ctx):
           ctx.add_page("hello", "Hello", lambda _ctx=None: page(ctx), icon="★")
   ```

4. 在“设置 → 插件”中重新加载，或重启启动器。

完整的可运行示例见 [`sdk/python/example_plugin`](../sdk/python/example_plugin)。

## 目录约定

| 位置 | 说明 |
| --- | --- |
| `mcs.official` 包内 | 随启动器分发的官方插件 |
| `%APPDATA%\MCSLauncher\plugins\` | 用户安装的插件（每个插件一个目录） |
| `%APPDATA%\MCSLauncher\plugin-data\<id>\` | 插件私有可写目录 |

`plugin.json` 字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `id` | 是 | 唯一 id，建议反向域名；原生插件二进制中的 id 必须一致 |
| `name` / `version` | 否 | 展示名与版本 |
| `api` | 否 | 所需插件 API 版本，当前为 `1` |
| `kind` | 否 | `python`（默认）或 `native` |
| `entry` | 否 | Python 入口 `.py`，或原生动态库文件名 |
| `dependencies` | 否 | 需要先加载的插件 id 列表 |
| `priority` | 否 | 数字越小越早加载/排序 |
| `abi` | 否 | 原生插件的 ABI 版本，当前为 `1` |

## 插件上下文 `ctx`

- `ctx.plugin_id`、`ctx.plugin_dir`、`ctx.data_dir`（可写）
- `ctx.settings`：`get(key)` / `set(key, value)` / `all()`
- `ctx.accounts`：当前账户、账户列表
- `ctx.launcher`：`versions()`、`launch(version_id, options)`、`refresh_versions()`
- `ctx.fs`：全盘读取；写入仅限游戏目录与启动器数据目录
- `ctx.http`：`get_json` / `get_text` / `download`（自动重试、BMCLAPI 镜像）
- `ctx.java`：Java 探测与 `find(major)`
- `ctx.tasks.run(fn, ...)`：后台线程执行，回调自动切回 UI 线程
- `ctx.ui`：`add_page`、`remove_page`、`notify`、`show_error`、`confirm`、`open_path`、`set_status`、`call_on_ui`
- `ctx.services`：插件间服务注册/查找，例如官方 Java 插件注册了 `"java"`
- `ctx.register_hook(hook, callback, priority=100)`

## 钩子

| 名称 | 参数 |
| --- | --- |
| `app.ready` | `host`, `window` |
| `app.closing` | `host` |
| `account.changed` | `account`（可能为 `None`） |
| `launch.pre` | `context`（可修改 `command` / `env`） |
| `launch.started` | `context`, `pid` |
| `launch.log` | `line` |
| `launch.finished` | `exit_code` |
| `settings.changed` | `key`, `value` |
| `game.version_installed` | `version_id` |
| `mod.installed` | `path`, `project` |

## 线程规则

- 只有 UI 线程可以操作 Qt 控件。
- 耗时操作放进 `ctx.tasks.run`；它的 `on_done` / `on_error` / `on_progress`
  已经通过 `UiService.call_on_ui` 切回 UI 线程。
- `ctx.http` 的调用是阻塞的，不要在 UI 线程直接调用大文件下载。

## 原生插件

C / C++ 插件使用稳定 C ABI，由官方“原生插件接口”插件加载。
入口导出 `mcs_plugin_entry()`，函数表定义见
[`sdk/native/mcs_plugin.h`](../sdk/native/mcs_plugin.h)，示例见
[`sdk/native/example_plugin`](../sdk/native/example_plugin)。

```c
MCS_EXPORT const MCSPluginV1 *mcs_plugin_entry(void) {
    static MCSPluginV1 plugin = { MCS_NATIVE_ABI, "com.example.native", "示例", "1.0.0",
                                  my_on_load, my_on_unload };
    return &plugin;
}
```

原生插件可获得：日志、钩子注册、读取设置、游戏目录、插件数据目录、
全盘文本读取、受限写入、同步 HTTP GET、触发自定义钩子。
原生插件不需要 Python，但必须与启动器使用相同的进程位数（当前为 64 位）。

## 安全边界

- 读取：不限制路径。
- 写入/删除：只有游戏目录、启动器数据目录、插件数据目录。
- 原生插件通过钩子只会收到账户公开字段（id / name / uuid），不会收到访问令牌；Python 插件与启动器同进程运行，应只安装可信插件。令牌本身由启动器通过 DPAPI 加密保存。
- 原生插件与 Python 插件拥有同等的进程内权限。只安装可信插件。
