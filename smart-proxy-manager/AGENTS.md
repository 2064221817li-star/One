# AGENTS.md — Smart Proxy Manager 开发约束

给在本仓库工作的编程 AI / 开发者。沟通与注释默认中文，代码标识符用英文。

## 项目边界（不要突破）

- 个人自用工具，与 Clash Verge Rev / Mihomo 配合；**不修改上游源码**，不自研代理协议、VPN 驱动或 TUN，**第一版不做 GUI**（只有 CLI）。
- 只调用 Mihomo / Verge 的公开机制（配置文件、Proxy Provider、REST API），不维护自己的内核。
- 预算上限 ¥300，默认零采购；引入任何付费服务前先停下来说明。

## 工作原则

1. **先验证再实现**：接口、配置格式、上游行为以真实源码和官方文档为准（见 `docs/feasibility-report.md`），不凭记忆或 README 推断。
2. **不编造结果**：禁止用虚构测速数据、模拟连接状态宣称功能正常。跑不了的验证标「未验证」，并写明原因。
3. **离线测试 ≠ 真实连接**：pytest 通过只证明逻辑正确；真实导入 Verge、真实节点连通性必须在 Windows 实机单独验证并如实区分。
4. **凭据安全**：订阅 Token、UUID、密码不得出现在日志、错误报告、测试样例和 Git 提交里；日志输出前做脱敏。真实配置只放 `config.toml`（已被 gitignore）。
5. **订阅内容是不可信输入**：下载要设超时、大小上限、重定向次数；YAML 只用 `yaml.safe_load`；不得执行订阅里携带的任何脚本或命令。
6. **失败保旧**：配置生成/校验失败时保留上一份有效配置，不覆盖；空订阅不得生成空配置覆盖旧配置。
7. **控制面归 Verge**：生成的配置不写 `external-controller`、`secret`、端口、`mode` 等键（会被 Verge 接管）；Mihomo REST API 若未配 secret 不得对外暴露。

## 架构约束

- 模块职责单一（见 `src/smart_proxy_manager/` 各文件 docstring），不要把功能堆进单个文件。
- 核心逻辑放在服务层（`services.py`）与各引擎模块里，`cli.py` 只做参数解析和结果输出，方便日后加 GUI 复用。
- 节点进出统一走 `models.Node` 模型及其校验，不在各模块里另造数据结构。
- 每个新功能配 pytest 测试（固定样例 + Mock，不依赖真实节点长期在线）。
