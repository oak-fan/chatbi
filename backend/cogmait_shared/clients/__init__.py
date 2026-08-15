"""Clients package.

该目录仅用于扩展模块复用内部服务 SDK，不作为平台内核默认依赖。
禁止从 `cogmait_shared.clients` 顶层做聚合导入，必须按具体子包路径导入
（例：`cogmait_shared.clients.contracts.main_api.dict_client`）。"""
