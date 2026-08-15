"""cogmait_shared package root.

共享组件已按职责拆分为：
- ``cogmait_shared.core``：基础类型转换、时间、ID、命名等通用能力
- ``cogmait_shared.api``：响应封装、异常处理、HTTP 错误与中间件
- ``cogmait_shared.observability``：日志与 request_id 上下文能力
- ``cogmait_shared.security``：跨服务安全契约、会话模型与入口安全上下文
- ``cogmait_shared.clients.core``：跨服务调用的通用底座
- ``cogmait_shared.clients.contracts``：面向具体服务的稳定客户端契约
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__: list[str] = []
