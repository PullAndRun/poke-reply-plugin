# 戳一戳回复插件

接收 NapCat 适配器的 QQ 戳一戳事件，转发给 LLM 独立思考并自动回复，同时自动回戳。

## 功能

- **戳一戳检测**：拦截 NapCat 适配器的戳一戳通知，仅处理目标是 bot 自身的戳一戳
- **LLM 思考回复**：将原始戳一戳文本（含 QQ 自定义动作如"捏了捏"、"比心"等）改写后送入 LLM 主链路，由 LLM 自主决定回复内容
- **自动回戳**：默认同时回戳对方（可在配置中关闭）
- **昵称注入**：支持将 bot 的 QQ 昵称注入戳一戳文本中，使 LLM 看到的上下文更完整(其实是bug打个补丁)
- **群黑名单**：可配置不响应此插件的群 QQ 号，黑名单群不会进入 LLM 回复链路，也不会触发自动回戳

## 配置

编辑 `config.toml`：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `plugin.enabled` | bool | `true` | 是否启用插件 |
| `plugin.config_version` | str | `"1.0.0"` | 配置版本号 |
| `enable_poke_back` | bool | `true` | 是否自动回戳对方 |
| `bot_nickname` | str | `""` | bot 在 QQ 上的昵称，填入后会注入到戳一戳文本的动作与后缀之间 |
| `group_blacklist` | array[string] | `[]` | 不响应戳一戳的群 QQ 号列表；留空表示不屏蔽任何群 |

`group_blacklist` 示例：

```toml
group_blacklist = ["123456789", "987654321"]
```

黑名单仅对群聊生效，私聊不受影响。群号即使写成数字也会按字符串统一匹配。

### 示例

bot 昵称为 "東雪莲"，收到用户 "张三" 发来的 "捏了捏" 动作时，LLM 收到的消息为：

```
张三（QQ:12345）捏了捏 東雪莲 的脸，找打（群聊「吹水群」中）
```

bot_nickname 留空时：

```
张三（QQ:12345）捏了捏的脸，找打（群聊「吹水群」中）
```

## 依赖

- MaiBot 主程序 ≥ 1.0.0
- maibot-plugin-sdk ≥ 2.0.0
- NapCat 适配器插件（提供 `adapter.napcat.message.send_poke` API）

## 工作流程

1. NapCat 适配器收到 QQ 戳一戳事件，转为通知消息（`is_notify=True`）
2. 插件 Hook `chat.receive.after_process` 拦截该消息
3. 校验：戳一戳目标是 bot 自身、发起者不是 bot 自身
4. 从 `raw_info` 提取 QQ 自定义动作文本（如有）
5. 改写消息为自然语言，设置 `is_notify=False`，送入 LLM 主链路
6. （可选）调用 NapCat API 回戳
7. LLM 收到改写后的消息，自主生成回复
