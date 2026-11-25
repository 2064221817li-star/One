# Smart Proxy Manager

个人自用的 Windows 智能代理节点管理工具，与 **Clash Verge Rev / Mihomo** 配合使用：

- 导入和管理多个代理订阅（含 V2RayAggregator 等公开来源）
- 解析、合并多种节点格式，自动去重与失效检测
- 用本机网络做延迟/连通性测试，按质量评分筛选节点
- 生成 Mihomo 兼容配置（仅节点 / Proxy Provider），校验通过才替换，失败保留旧配置

仅供个人使用，不公开发布，无商业功能。

## 当前状态

**阶段 1：核心业务模块已实现（离线验证通过）。** 已完成：

- 项目结构、Node 统一模型与字段校验、SQLite 存储（来源 / 节点 / 多来源关联，含旧库迁移）；
- 订阅获取：本地文件与 HTTP(S) 下载，带超时 / 大小 / 重定向上限与 SSRF 防护（默认拒绝私网地址，显式开关才放行）；
- 协议解析：Mihomo YAML（只取 proxies，危险顶层键不透传）、Base64 订阅、ss / vmess / vless / trojan URI 逐字段校验，不支持的协议跳过计数，逐条错误收集；
- 指纹去重（协议 + 主机 + 端口 + 传输 / TLS / SNI + 认证参数 SHA-256 摘要）与多来源合并；
- 配置生成（完整 profile 与仅 proxies 的 provider 两种受控输出，不写控制面键）与校验（临时文件 → 校验 → 原子替换，失败保旧并写错误报告）；
- CLI：`sources list/add`、`update`、`stats`、`generate`、`validate` 全部可用，中文提示与退出码规范（0/1/2）；
- 测试：125 个 pytest 用例全离线通过（固定样例 + Mock），含凭据脱敏专项测试。

**尚未实现 / 未验证：** 节点测速与评分（阶段 2，接口保留）；自动定时更新（阶段 3）；真实节点连通性与 Clash Verge Rev 实机导入**尚未验证**——离线测试通过不等于真实连接成功，需在 Windows 实机单独验证。技术可行性见 `docs/feasibility-report.md`。

## 环境要求

- Windows 10/11 x64
- Python 3.13（项目固定 `>=3.13,<3.14`，用 `py -3.13` 调用）
- 已安装 Clash Verge Rev（官方稳定版）

## 安装与运行（Windows PowerShell）

在项目目录（例如 `D:\Deep seek Harness\SmartProxyManager`）下：

```powershell
# 1. 创建虚拟环境
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. 安装（含开发依赖）
pip install -e .[dev]

# 3. 查看 CLI 帮助
spm --help
spm sources list

# 4. 运行测试
pytest
```

配置：把 `config.example.toml` 复制为 `config.toml` 后按需修改（`config.toml` 不会进 Git，不要把真实订阅 Token 发到聊天或日志里）。

## 目录结构

```
SmartProxyManager/
├── README.md / AGENTS.md     项目说明 / 给编程 AI 的开发约束
├── pyproject.toml            依赖与打包（PyYAML 6.0.3、httpx 0.28.1、pytest）
├── config.example.toml       示例配置（无真实凭据）
├── docs/                     可行性报告等文档
├── src/smart_proxy_manager/  核心源码（按模块拆分，CLI 与核心逻辑解耦）
├── tests/                    pytest 测试（固定样例，不访问网络）
├── data/                     本地数据库等数据（不进 Git）
├── output/                   生成的配置与报告（不进 Git）
└── scripts/                  Windows 开发/测试辅助脚本
```

## 常用命令

```powershell
spm sources add --name my-sub --kind file --location D:\subs\nodes.yaml
spm update my-sub          # 获取 → 解析 → 去重 → 入库，输出统计
spm update --all           # 更新全部已启用来源
spm stats                  # 按来源 / 协议统计节点
spm generate               # 生成完整 profile 到 output\smart-proxy.yaml
spm generate --provider-only   # 只生成 provider 数据文件（仅 proxies）
spm validate output\smart-proxy.yaml
```

## 开发顺序（后续阶段）

阶段 2：本地测速（复用 Mihomo 健康检查 / REST API）与智能评分筛选。阶段 3：自动更新与 Verge 对接深化。真实导入 Verge 的验证在 Windows 实机单独进行，离线测试通过不等于真实连接成功。
