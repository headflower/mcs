/*
 * MCS Launcher 原生插件 C ABI（版本 1）
 * ------------------------------------------------------------
 * 1. 编译为动态库（Windows: .dll，Linux/macOS: .so/.dylib）。
 * 2. 插件目录中放置 plugin.json：
 *      {
 *        "id": "com.example.native",
 *        "name": "示例原生插件",
 *        "version": "1.0.0",
 *        "api": 1,
 *        "kind": "native",
 *        "entry": "plugin.dll",
 *        "abi": 1
 *      }
 * 3. 导出 const MCSPluginV1* mcs_plugin_entry(void)。
 *
 * 字符串统一使用 UTF-8。函数表由启动器持有，生命周期覆盖整个插件生命周期。
 * 回调可能在任意线程被调用；宿主会负责获取 GIL，但插件自身仍需保证线程安全。
 */
#ifndef MCS_PLUGIN_H
#define MCS_PLUGIN_H

#include <stdint.h>

#ifdef _WIN32
#  define MCS_EXPORT __declspec(dllexport)
#else
#  define MCS_EXPORT __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

#define MCS_NATIVE_ABI 1

/* 日志级别：0=debug 1=info 2=warning 3=error */
typedef void (*MCSHookCallback)(void *userdata, const char *hook, const char *payload_json);

typedef struct MCSHostApi {
    uint32_t abi_version;
    void *host; /* 不透明指针，原样传回所有函数 */

    void (*log)(void *host, int level, const char *message);

    /* 注册钩子。返回 1 成功，0 失败。可用钩子见 sdk 文档。 */
    int (*register_hook)(void *host, const char *hook, MCSHookCallback callback, void *userdata);

    /* 读取启动器设置，返回 JSON 文本；键不存在时返回 "null"。 */
    const char *(*get_setting)(void *host, const char *key);

    /* 插件私有数据目录（可写）。 */
    const char *(*plugin_data_dir)(void *host);

    /* 当前游戏目录。 */
    const char *(*game_dir)(void *host);

    /* 读取任意文本文件（拥有完整读取权限）。相对路径按游戏目录解析。 */
    const char *(*read_text_file)(void *host, const char *path);

    /* 写入文本文件。仅允许游戏目录、启动器数据目录与插件数据目录。 */
    int (*write_text_file)(void *host, const char *path, const char *text);

    /* 同步 HTTP GET，返回响应文本。网络请求可能较慢，建议在插件线程中调用。 */
    const char *(*http_get)(void *host, const char *url);

    /* 触发一个启动器钩子，payload_json 必须是 JSON 对象文本。 */
    int (*emit_hook)(void *host, const char *hook, const char *payload_json);

    /* 最近一次失败调用的错误信息；成功时为空字符串。 */
    const char *(*last_error)(void *host);
} MCSHostApi;

typedef struct MCSPluginV1 {
    uint32_t abi_version;
    const char *id;      /* 必须与 plugin.json 的 id 完全一致 */
    const char *name;
    const char *version;
    int (*on_load)(const MCSHostApi *api, void **state);
    void (*on_unload)(void *state);
} MCSPluginV1;

/* 每个原生插件必须导出的唯一入口。 */
MCS_EXPORT const MCSPluginV1 *mcs_plugin_entry(void);

#ifdef __cplusplus
}
#endif

#endif /* MCS_PLUGIN_H */
