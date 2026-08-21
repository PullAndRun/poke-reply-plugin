"""戳一戳自动回复插件

接收 NapCat 适配器的 QQ 戳一戳事件，转发给 LLM 独立思考并自动回复。
通过 Hook 机制拦截戳一戳通知消息，将原始事件信息改写为自然语言后送入 LLM 主链路，
让 LLM 自行判断如何回复。同时自动回戳。
"""

from typing import Any, Dict

from maibot_sdk import Field, HookHandler, MaiBotPlugin, PluginConfigBase
from maibot_sdk.types import HookMode


class PluginSectionConfig(PluginConfigBase):
    """插件基础配置。"""

    __ui_label__ = "插件"
    __ui_icon__ = "package"
    __ui_order__ = 0

    enabled: bool = Field(default=True, description="是否启用插件")
    config_version: str = Field(default="1.0.0", description="配置版本")


class PokeReplyConfig(PluginConfigBase):
    """戳一戳回复插件配置。"""

    __ui_label__ = "戳一戳回复"

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    group_blacklist: list[str] = Field(
        default_factory=list,
        description="不响应戳一戳的群 QQ 号列表",
    )
    enable_poke_back: bool = Field(default=True, description="是否同时回戳对方")
    bot_nickname: str = Field(default="", description="Bot 在 QQ 上的昵称，用于注入戳一戳文本中")


class PokeReplyPlugin(MaiBotPlugin):
    """戳一戳自动回复插件"""

    config_model = PokeReplyConfig

    async def on_load(self) -> None:
        pass

    async def on_unload(self) -> None:
        pass

    @HookHandler(
        hook="chat.receive.after_process",
        mode=HookMode.BLOCKING,
        name="poke_reply_handler",
        description="检测戳一戳事件并修改消息使其进入 LLM 回复链路",
    )
    async def handle_poke_notice(
        self, message: Dict[str, Any] | None = None, **kwargs: Any
    ) -> Dict[str, Any] | None:
        """拦截戳一戳通知，将原始事件改写为自然语言送入 LLM。

        仅处理目标为 bot 自身的戳一戳事件。

        Args:
            message: 当前入站消息的序列化字典。
            **kwargs: 额外参数。

        Returns:
            若处理了戳一戳则返回包含 modified_kwargs 的字典。
        """
        del kwargs

        if not self.config.plugin.enabled:
            return None

        if not isinstance(message, dict):
            return None

        if not message.get("is_notify"):
            return None

        msg_info = message.get("message_info") or {}
        if not isinstance(msg_info, dict):
            return None

        additional = msg_info.get("additional_config") or {}
        if not isinstance(additional, dict):
            return None

        notice_type = str(additional.get("napcat_notice_type") or "")
        notice_sub_type = str(additional.get("napcat_notice_sub_type") or "")
        if notice_type != "notify" or notice_sub_type != "poke":
            return None

        raw_payload = additional.get("napcat_notice_payload") or {}
        if not isinstance(raw_payload, dict):
            return None

        user_info = msg_info.get("user_info") or {}
        if not isinstance(user_info, dict):
            user_info = {}

        group_info = msg_info.get("group_info") or {}
        if not isinstance(group_info, dict):
            group_info = {}

        poker_name = str(user_info.get("user_nickname") or user_info.get("user_id") or "未知用户")
        poker_id = str(user_info.get("user_id") or "")
        target_id = str(raw_payload.get("target_id") or "")
        self_id = str(additional.get("self_id") or raw_payload.get("self_id") or "")
        group_id = str(group_info.get("group_id") or raw_payload.get("group_id") or "")
        group_name = str(group_info.get("group_name") or "")

        if group_id and _is_group_blacklisted(group_id, self.config.group_blacklist):
            self.ctx.logger.info("Skipping poke event in blacklisted group %s", group_id)
            return None

        if not self_id:
            self.ctx.logger.warning("无法获取 bot 自身 QQ 号 (self_id)，跳过")
            return None

        if poker_id == self_id:
            return None

        if target_id != self_id:
            return None

        if group_id and group_name:
            location = f"群聊「{group_name}」中"
        elif group_id:
            location = "群聊中"
        else:
            location = "私聊中"

        labeled_name = f"{poker_name}（QQ:{poker_id}）"

        action_val, suffix_val = _extract_poke_action(raw_payload)
        if action_val:
            bot_tag = ""
            if self.config.bot_nickname:
                bot_tag = f" {self.config.bot_nickname}"
            raw_poke_text = f"{labeled_name}{action_val}{bot_tag}{suffix_val}"
        else:
            raw_poke_text = str(message.get("processed_plain_text") or "")
            if poker_name and poker_name in raw_poke_text:
                raw_poke_text = raw_poke_text.replace(poker_name, labeled_name, 1)
            else:
                raw_poke_text = f"{labeled_name}发起了戳一戳"

        natural_text = f"{raw_poke_text}（{location}）"

        self.ctx.logger.info(
            "检测到戳一戳: poker=%s(%s) group=%s bot_nickname=%r",
            poker_name,
            poker_id,
            group_id or "(私聊)",
            self.config.bot_nickname,
        )

        message["is_notify"] = False
        message["processed_plain_text"] = natural_text
        if message.get("display_message") is not None:
            message["display_message"] = natural_text
        message["raw_message"] = [{"type": "text", "data": natural_text}]

        if self.config.enable_poke_back and poker_id:
            try:
                api_params: Dict[str, Any] = {"user_id": poker_id}
                if group_id:
                    api_params["group_id"] = group_id
                await self.ctx.api.call("adapter.napcat.message.send_poke", **api_params)
                self.ctx.logger.info("已回戳用户 %s", poker_id)
            except Exception:
                self.ctx.logger.warning(
                    "回戳用户 %s 失败", poker_id, exc_info=True
                )

        return {"action": "continue", "modified_kwargs": {"message": message}}

    async def on_config_update(self, scope: str, config_data: Dict[str, object], version: str) -> None:
        del scope
        del config_data
        del version


def create_plugin() -> PokeReplyPlugin:
    return PokeReplyPlugin()


def _extract_poke_action(raw_payload: Dict[str, Any]) -> tuple[str, str]:
    """从 raw_info 中提取 QQ 自定义戳一戳动作文本。"""
    raw_info = raw_payload.get("raw_info")
    if isinstance(raw_info, list):
        nor_parts = [
            str(col.get("txt", ""))
            for col in raw_info
            if isinstance(col, dict) and col.get("type") == "nor"
        ]
        if nor_parts:
            return nor_parts[0], "".join(nor_parts[1:])
    return "", ""


def _is_group_blacklisted(group_id: str, blacklist: object) -> bool:
    """Return whether a group id is present in the configured blacklist."""
    normalized_group_id = str(group_id).strip()
    if not normalized_group_id or not isinstance(blacklist, (list, tuple, set)):
        return False
    return normalized_group_id in {
        str(item).strip() for item in blacklist if str(item).strip()
    }
