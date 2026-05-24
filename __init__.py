"""
朱雀抽奖插件
功能：
1. 自动抽取朱雀站点喇叭球
2. 显示朱雀灵石余额
3. 抽奖前后余额对比
4. 消息推送（微信/Telegram）
"""

import re
import traceback
from datetime import datetime
from typing import Any, Dict, List, Tuple, Optional

import pytz
from app import schemas
from app.core.config import settings
from app.core.event import eventmanager, Event
from app.helper.sites import SitesHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.utils.http import RequestUtils
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger


class ZhuqueLottery(_PluginBase):
    """
    朱雀抽奖插件
    """

    # 插件元数据
    plugin_name = "朱雀抽奖"
    plugin_desc = "自动抽取朱雀站点喇叭球，显示灵石余额。"
    plugin_icon = "lottery.png"
    plugin_version = "1.0.0"
    plugin_author = "QClaw"
    author_url = "https://github.com/QClaw"
    plugin_config_prefix = "zhuquelottery_"
    plugin_order = 0
    auth_level = 2

    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None

    # 配置属性
    _enabled: bool = False
    _cron: str = ""
    _onlyonce: bool = False
    _notify: bool = True
    _cookie: str = ""  # 朱雀 Cookie
    _csrf_token: str = ""  # CSRF Token
    _mp_url: str = "http://192.168.10.18:3001"
    _api_key: str = "4BV87UxlTBXPe4JF3ugV2w"
    _site_id: int = 34  # 朱雀站点 ID
    _threshold: float = 1000.0  # 灵石阈值提醒

    # 历史记录
    _history: List[Dict] = []

    def init_plugin(self, config: dict = None):
        """
        初始化插件
        """
        # 停止现有任务
        self.stop_service()

        # 加载配置
        if config:
            self._enabled = config.get("enabled", False)
            self._cron = config.get("cron", "")
            self._onlyonce = config.get("onlyonce", False)
            self._notify = config.get("notify", True)
            self._cookie = config.get("cookie", "")
            self._csrf_token = config.get("csrf_token", "")  # 新增
            self._mp_url = config.get("mp_url", "http://192.168.10.18:3001")
            self._api_key = config.get("api_key", "4BV87UxlTBXPe4JF3ugV2w")
            self._site_id = config.get("site_id", 34)
            self._threshold = float(config.get("threshold", 1000.0))

            # 保存配置
            self.__update_config()

        # 启动定时任务
        if self._enabled or self._onlyonce:
            self.__start_service()

    def __start_service(self):
        """
        启动定时任务
        """
        if self._onlyonce:
            # 立即执行一次
            self.lottery()

            # 关闭 onlyonce
            self._onlyonce = False
            self.__update_config()

        if self._enabled and self._cron:
            # 创建定时器
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)

            # 添加定时任务
            try:
                self._scheduler.add_job(
                    func=self.lottery,
                    trigger=CronTrigger.from_crontab(self._cron),
                    name="朱雀抽奖"
                )
                logger.info(f"朱雀抽奖定时任务已添加: {self._cron}")
            except Exception as e:
                logger.error(f"添加定时任务失败: {e}")

            # 启动定时器
            if self._scheduler.get_jobs():
                self._scheduler.start()
                logger.info("朱雀抽奖定时任务已启动")
            else:
                self._scheduler = None

    def __update_config(self):
        """
        更新配置到数据库
        """
        config = {
            "enabled": self._enabled,
            "cron": self._cron,
            "onlyonce": self._onlyonce,
            "notify": self._notify,
            "cookie": self._cookie,
            "csrf_token": self._csrf_token,  # 新增
            "mp_url": self._mp_url,
            "api_key": self._api_key,
            "site_id": self._site_id,
            "threshold": self._threshold
        }
        # 保存配置（通过父类方法）
        super().update_config(config)

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        返回插件配置表单
        """
        # 表单定义
        form = [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VTabs",
                        "content": [
                            {
                                "component": "VTab",
                                "text": "基本设置"
                            },
                            {
                                "component": "VTab",
                                "text": "高级设置"
                            }
                        ],
                        "panels": [
                            {
                                "component": "VWindowItem",
                                "content": [
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {
                                                "component": "VCol",
                                                "props": {
                                                    "cols": 12,
                                                    "md": 6
                                                },
                                                "content": [
                                                    {
                                                        "component": "VSwitch",
                                                        "props": {
                                                            "label": "启用插件",
                                                            "model": "enabled"
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {
                                                    "cols": 12,
                                                    "md": 6
                                                },
                                                "content": [
                                                    {
                                                        "component": "VSwitch",
                                                        "props": {
                                                            "label": "立即运行一次",
                                                            "model": "onlyonce"
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {
                                                "component": "VCol",
                                                "props": {
                                                    "cols": 12,
                                                    "md": 6
                                                },
                                                "content": [
                                                    {
                                                        "component": "VTextField",
                                                        "props": {
                                                            "label": "定时任务",
                                                            "model": "cron",
                                                            "placeholder": "0 8 * * *（每天早上8点）",
                                                            "hint": "Cron 表达式"
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {
                                                    "cols": 12,
                                                    "md": 6
                                                },
                                                "content": [
                                                    {
                                                        "component": "VSwitch",
                                                        "props": {
                                                            "label": "开启通知",
                                                            "model": "notify"
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {
                                                "component": "VCol",
                                                "props": {
                                                    "cols": 12,
                                                    "md": 6
                                                },
                                                "content": [
                                                    {
                                                        "component": "VTextField",
                                                        "props": {
                                                            "label": "朱雀 Cookie",
                                                            "model": "cookie",
                                                            "placeholder": "输入朱雀站点 Cookie",
                                                            "hint": "用于抽奖请求",
                                                            "clearable": True
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {
                                                    "cols": 12,
                                                    "md": 6
                                                },
                                                "content": [
                                                    {
                                                        "component": "VTextField",
                                                        "props": {
                                                            "label": "CSRF Token",
                                                            "model": "csrf_token",
                                                            "placeholder": "输入 CSRF Token",
                                                            "hint": "从朱雀页面获取",
                                                            "clearable": True
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {
                                                    "cols": 12,
                                                    "md": 6
                                                },
                                                "content": [
                                                    {
                                                        "component": "VTextField",
                                                        "props": {
                                                            "label": "灵石阈值",
                                                            "model": "threshold",
                                                            "placeholder": "1000.0",
                                                            "hint": "低于此值时提醒"
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "component": "VWindowItem",
                                "content": [
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {
                                                "component": "VCol",
                                                "props": {
                                                    "cols": 12,
                                                    "md": 6
                                                },
                                                "content": [
                                                    {
                                                        "component": "VTextField",
                                                        "props": {
                                                            "label": "MoviePilot 地址",
                                                            "model": "mp_url",
                                                            "placeholder": "http://192.168.10.18:3001"
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {
                                                    "cols": 12,
                                                    "md": 6
                                                },
                                                "content": [
                                                    {
                                                        "component": "VTextField",
                                                        "props": {
                                                            "label": "API Key",
                                                            "model": "api_key",
                                                            "placeholder": "4BV87UxlTBXPe4JF3ugV2w"
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {
                                                "component": "VCol",
                                                "props": {
                                                    "cols": 12,
                                                    "md": 6
                                                },
                                                "content": [
                                                    {
                                                        "component": "VTextField",
                                                        "props": {
                                                            "label": "朱雀站点 ID",
                                                            "model": "site_id",
                                                            "placeholder": "34"
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

        # 模型
        model = {
            "enabled": self._enabled,
            "cron": self._cron,
            "onlyonce": self._onlyonce,
            "notify": self._notify,
            "cookie": self._cookie,
            "csrf_token": self._csrf_token,  # 新增
            "mp_url": self._mp_url,
            "api_key": self._api_key,
            "site_id": self._site_id,
            "threshold": self._threshold
        }

        return form, model

    def get_page(self) -> List[dict]:
        """
        返回插件历史记录页面
        """
        # 获取当前灵石余额
        bonus = self.get_bonus()

        # 页面内容
        page = [
            {
                "component": "VCard",
                "content": [
                    {
                        "component": "VCardTitle",
                        "text": "💰 朱雀灵石余额"
                    },
                    {
                        "component": "VCardText",
                        "content": [
                            {
                                "component": "VRow",
                                "content": [
                                    {
                                        "component": "VCol",
                                        "props": {"cols": 12, "md": 6},
                                        "content": [
                                            {
                                                "component": "VTextField",
                                                "props": {
                                                    "label": "当前灵石余额",
                                                    "model": "current_bonus",
                                                    "value": f"{bonus:.2f}" if bonus else "获取失败",
                                                    "readonly": True,
                                                    "hint": "自动获取"
                                                }
                                            }
                                        ]
                                    },
                                    {
                                        "component": "VCol",
                                        "props": {"cols": 12, "md": 6},
                                        "content": [
                                            {
                                                "component": "VBtn",
                                                "props": {
                                                    "color": "primary",
                                                    "text": "立即抽奖",
                                                    "click": "lottery"
                                                }
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            },
            {
                "component": "VCard",
                "content": [
                    {
                        "component": "VCardTitle",
                        "text": "📊 抽奖历史记录"
                    },
                    {
                        "component": "VCardText",
                        "content": [
                            {
                                "component": "VTable",
                                "props": {
                                    "headers": [
                                        {"text": "时间", "value": "time"},
                                        {"text": "抽奖前余额", "value": "bonus_before"},
                                        {"text": "抽奖后余额", "value": "bonus_after"},
                                        {"text": "花费灵石", "value": "cost"},
                                        {"text": "结果", "value": "result"}
                                    ],
                                    "items": self._history[-20:] if self._history else [],
                                    "item-key": "time"
                                }
                            }
                        ]
                    }
                ]
            }
        ]

        return page

    def stop_service(self):
        """
        停止定时任务
        """
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("朱雀抽奖定时任务已停止")

    def get_bonus(self) -> Optional[float]:
        """
        获取朱雀灵石余额
        """
        try:
            url = f"{self._mp_url}/api/v1/site/userdata/{self._site_id}"
            headers = {"X-API-KEY": self._api_key}
            resp = RequestUtils(headers=headers).get_res(url)

            if resp and resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) > 0:
                    bonus = data[0].get("bonus", 0.0)
                    logger.info(f"获取朱雀灵石余额成功: {bonus}")
                    return float(bonus)
            else:
                logger.error(f"获取朱雀灵石余额失败: HTTP {resp.status_code if resp else 'None'}")

        except Exception as e:
            logger.error(f"获取朱雀灵石余额异常: {e}\n{traceback.format_exc()}")

        return None

    def lottery(self):
        """
        执行抽奖
        """
        logger.info("开始朱雀抽奖...")

        # 1. 获取抽奖前余额
        bonus_before = self.get_bonus()
        if bonus_before is None:
            logger.error("获取抽奖前余额失败，中止抽奖")
            return

        logger.info(f"抽奖前余额: {bonus_before:.2f}")

        # 2. 执行抽奖请求
        result = self.do_lottery()

        # 3. 获取抽奖后余额
        bonus_after = self.get_bonus()
        if bonus_after is None:
            logger.error("获取抽奖后余额失败")
            bonus_after = bonus_before  # 使用前值

        # 4. 计算花费
        cost = bonus_before - bonus_after
        logger.info(f"抽奖后余额: {bonus_after:.2f}, 花费: {cost:.2f}")

        # 5. 记录历史
        record = {
            "time": datetime.now(pytz.timezone(settings.TZ)).strftime("%Y-%m-%d %H:%M:%S"),
            "bonus_before": f"{bonus_before:.2f}",
            "bonus_after": f"{bonus_after:.2f}",
            "cost": f"{cost:.2f}",
            "result": result
        }
        self._history.append(record)

        # 只保留最近 100 条记录
        if len(self._history) > 100:
            self._history = self._history[-100:]

        # 6. 发送通知
        if self._notify:
            self.send_notification(record)

        logger.info("朱雀抽奖完成")

    def do_lottery(self) -> str:
        """
        执行抽奖请求
        """
        logger.info("开始执行抽奖请求...")

        try:
            # 朱雀抽奖 API
            url = "https://zhuque.in/api/gaming/spinThePrizeWheel"
            
            # 请求头
            headers = {
                "Cookie": self._cookie,
                "x-csrf-token": self._csrf_token,
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            
            # 发送 POST 请求（无请求体）
            resp = RequestUtils(headers=headers).post_res(url, data="")
            
            if resp and resp.status_code == 200:
                result = resp.json()
                logger.info(f"抽奖成功: {result}")
                
                # 解析响应（根据实际返回格式调整）
                message = result.get("message", "抽奖成功")
                prize = result.get("prize", "")
                cost = result.get("cost", 4)  # 默认花费 4 灵石
                
                return f"成功 | 花费 {cost} 灵石 | {message} {prize}".strip()
            else:
                error_msg = f"抽奖失败: HTTP {resp.status_code if resp else 'None'}"
                if resp:
                    error_msg += f" | {resp.text[:200]}"
                logger.error(error_msg)
                return error_msg
                
        except Exception as e:
            error_msg = f"抽奖请求异常: {e}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            return error_msg

    def send_notification(self, record: Dict):
        """
        发送通知
        """
        try:
            title = "🎲 朱雀抽奖完成"
            text = f"""## 朱雀抽奖结果

- ⏰ 时间：{record["time"]}
- 💰 抽奖前余额：{record["bonus_before"]}
- 💰 抽奖后余额：{record["bonus_after"]}
- 💸 花费灵石：{record["cost"]}
- 🎯 结果：{record["result"]}

---
> 由 MoviePilot 朱雀抽奖插件自动发送
"""

            # 发送通知（通过 MoviePilot 的通知系统）
            self.send_message(title, text, NotificationType.Plugin)

            logger.info("抽奖通知已发送")

        except Exception as e:
            logger.error(f"发送通知失败: {e}\n{traceback.format_exc()}")

    def __del__(self):
        """
        析构函数，停止定时任务
        """
        self.stop_service()
