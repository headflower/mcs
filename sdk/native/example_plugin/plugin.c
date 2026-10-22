/*
 * 示例原生插件：注册 app.ready 与 launch.log 钩子，并在插件数据目录写入
 * 一份启动记录。编译方式见同目录 build_msvc.bat / build_gcc.sh。
 */
#include "mcs_plugin.h"

#include <stdio.h>
#include <string.h>

static const MCSPluginV1 PLUGIN = {
    MCS_NATIVE_ABI,
    "com.example.native",
    "示例原生插件",
    "1.0.0",
    NULL,
    NULL,
};

static const MCSHostApi *g_api = NULL;
static int g_ready_count = 0;

static void write_log(const char *line) {
    if (!g_api) return;
    const char *dir = g_api->plugin_data_dir(g_api->host);
    if (!dir || !dir[0]) return;

    char path[1024];
    snprintf(path, sizeof(path), "%s/events.log", dir);
    const char *previous = g_api->read_text_file(g_api->host, path);
    char buffer[8192];
    buffer[0] = '\0';
    if (previous) {
        snprintf(buffer, sizeof(buffer), "%s%s\n", previous, line);
    } else {
        snprintf(buffer, sizeof(buffer), "%s\n", line);
    }
    if (g_api->write_text_file(g_api->host, path, buffer) != 0) {
        g_api->log(g_api->host, 2, g_api->last_error(g_api->host));
    }
}

static void on_app_ready(void *userdata, const char *hook, const char *payload_json) {
    (void)userdata;
    (void)payload_json;
    g_ready_count += 1;
    if (g_api) {
        char message[256];
        snprintf(message, sizeof(message), "原生插件收到 %s（第 %d 次）", hook, g_ready_count);
        g_api->log(g_api->host, 1, message);
    }
    write_log("app.ready");
}

static void on_launch_log(void *userdata, const char *hook, const char *payload_json) {
    (void)userdata;
    if (!g_api) return;
    char line[512];
    snprintf(line, sizeof(line), "%s %s", hook, payload_json ? payload_json : "{}");
    if (strlen(line) > 400) line[400] = '\0';
    /* 游戏日志可能非常频繁，示例只记录到内存日志。 */
    g_api->log(g_api->host, 0, line);
}

static int native_on_load(const MCSHostApi *api, void **state) {
    if (!api || api->abi_version != MCS_NATIVE_ABI) return 1;
    g_api = api;
    (void)state;

    g_api->log(g_api->host, 1, "示例原生插件正在加载");
    if (!g_api->register_hook(g_api->host, "app.ready", on_app_ready, NULL)) return 2;
    if (!g_api->register_hook(g_api->host, "launch.log", on_launch_log, NULL)) return 3;

    const char *game_dir = g_api->game_dir(g_api->host);
    g_api->log(g_api->host, 1, game_dir ? game_dir : "(未知游戏目录)");
    write_log("loaded");
    return 0;
}

static void native_on_unload(void *state) {
    (void)state;
    if (g_api) {
        write_log("unloaded");
        g_api->log(g_api->host, 1, "示例原生插件已卸载");
    }
    g_api = NULL;
}

MCS_EXPORT const MCSPluginV1 *mcs_plugin_entry(void) {
    static MCSPluginV1 plugin = PLUGIN;
    plugin.on_load = native_on_load;
    plugin.on_unload = native_on_unload;
    return &plugin;
}
