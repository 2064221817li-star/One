# Smart Proxy Manager — 阶段 0 可行性报告

- 日期：2026-11-10
- 阶段：阶段 0（源码调研与可行性验证）之源码研究部分
- 结论一句话：**技术路线可行，无阻断性问题。** 推荐路线 = Python 工具生成「仅含节点/Provider 的受控 Mihomo YAML」→ 通过 Clash Verge Rev 的本地导入或 Mihomo 的 file 型 Proxy Provider 交付 → 测速与健康检查优先复用 Mihomo 内置能力（健康检查 + REST API），Python 只做订阅管理、解析、去重、评分与配置生成。

---

## 0. 调研方法与环境限制（先说明，避免误读下文证据等级）

1. 本次调研在 Linux VM 中完成，**不是用户的 Windows 电脑**。Windows 环境基线检查未执行（见第 5 节，给出了用户自查命令清单）。
2. 本机 `git clone` 通道异常：对三个仓库执行 `git clone --depth 1` 与 `git ls-remote` 均长时间无数据直至超时（curl 访问 github.com 正常）。按预案改用 **GitHub API 按明确分支名读取源码文件**，在 `research/` 下保存了关键文件的局部镜像（非完整克隆）。涉及结论均以这些实际读到的文件为准。
3. **数据异常与处置（重要）**：调研初期，GitHub API 以默认分支查询 `MetaCubeX/mihomo` 时返回了一个同名 Python 仓库（Honkai: Star Rail 数据模型库）的内容，包括错误的许可证（MIT）与提交哈希。本报告已弃用该批数据。改用 mihomo 的发布分支 `Meta` 显式查询后，返回内容与官方文档、pkg.go.dev 等多方来源一致（GPL-3.0、Go 源码结构），方才采信。下文所有 mihomo 结论均基于 `Meta` 分支源码与官方文档 wiki.metacubex.one。
4. 未执行任何上游仓库中的脚本或二进制；未编写业务代码。

---

## 1. 上游版本与许可证台账

| 项目 | 仓库 | 本次核查基准 | 最新 Release（API 查询） | 许可证（以仓库 LICENSE 文件为准） | 备注 |
|---|---|---|---|---|---|
| Clash Verge Rev | github.com/clash-verge-rev/clash-verge-rev | `dev` 分支 HEAD `304a65fc36dfba7dec25124c0294865897df8c00`（2026-11-10） | v2.5.10（2026-11-03） | **GPL-3.0**（LICENSE 文件已核） | 默认分支为 `dev`；用户实际安装的版本需在 Windows 自查时确认 |
| Mihomo | github.com/MetaCubeX/mihomo | `Meta` 分支 HEAD `3f27ef39f8c96bbfbc8b0b9bb10f5c9ef60149d8`（2026-10-21） | v1.19.33（2026-10-21） | **GPL-3.0**（LICENSE 文件已核；README 另注明：非 MetaCubeX 的下游项目名称不得包含 "mihomo" 一词） | 发布/开发基准分支为 `Meta`；Verge 内置的内核版本通常滞后于上游最新版，需在实机确认 |
| V2RayAggregator | github.com/mahdibland/V2RayAggregator | `master` 分支 HEAD `3b63ba662719e4cfce09d860b264a2c447ba4c89`（2026-11-10） | 1.0.0（2022-10-18，之后无新 Release，靠 Actions 定时提交更新内容） | **GPL-3.0**（LICENSE 文件已核） | 仓库仍在靠 GitHub Actions 高频更新（当日有提交） |

许可证影响：三者均为 GPL-3.0。本项目只做**调用与配置生成**（不复制其代码进本项目、不链接其二进制源码），个人自用场景下无额外义务；若日后复制 V2RayAggregator 的 Python 代码片段进行修改/分发，须遵守 GPL-3.0 并保留来源说明。第一版决定：**不复制上游代码**，仅借鉴思路自行实现（见第 4 节）。

---

## 2. 十个核心问题逐项结论

### Q1 能否直接生成 Clash Verge Rev 可导入的 Mihomo YAML？
**结论：已验证（源码级）——可以。**
- Verge 的订阅导入校验在 `clash-verge-rev/src-tauri/src/config/prfitem.rs`（`from_url`）：下载内容先按 YAML 解析，随后强制校验「必须包含 `proxies` 或 `proxy-providers` 之一」，否则报错 `profile does not contain 'proxies' or 'proxy-providers'`。
- 本地导入走同一文件的 `from_local`：接收文件内容生成 profile。
- 导入后配置经 `src-tauri/src/enhance/mod.rs` 的 `enhance()` 加工为运行时配置，交给 Verge 内置 Mihomo 内核运行。
- 备注：即我们生成的 YAML 只要是合法 Mihomo 配置且至少含 `proxies` 或 `proxy-providers`，即可被 Verge 导入。真实导入仍需在用户 Windows 实机上做一次冒烟测试（未验证，见第 9 节）。

### Q2 能否只输出 Proxy Provider 而不覆盖现有路由规则？
**结论：已验证（源码级）——机制成立；但要区分两种交付方式。**
- Mihomo 侧：`proxy-providers` 是一等机制，类型有 `http` / `file` / `inline` 三种（`mihomo/adapter/provider/parser.go` 的 `ParseProxyProvider`）；代理组通过 `use:` 引用 provider，规则（rules）与 provider 完全解耦。
- Verge 侧：只含 `proxy-providers` 的文件能通过 Q1 的导入校验；`enhance/mod.rs` 的 `cleanup_proxy_groups` 会读取 `proxy-providers` 的名称集合来校验各代理组 `use` 引用的有效性，说明 provider 会被正常纳入运行时配置。
- **注意事项（已验证）**：`enhance/mod.rs` 中有 `CONTROL_PLANE_KEYS` 清单——`external-controller`、`secret`、各端口、`mode`、`allow-lan`、`log-level` 等键由 Verge 接管，profile 里写了也会被丢弃/强制覆盖。**我们生成的文件不要试图设置这些键。**
- **设计取舍（方案建议，非已验证事实）**：在 Verge 里一份 profile 就是一份完整配置基底。若把「只有 provider 的文件」作为独立 profile 启用，它没有 rules，需要自带至少一个代理组和兜底规则，会改变用户的分流现状。更稳妥的交付是二选一：
  - A. 生成**完整 profile**（proxies + groups + 极简 rules），定位为用户主动切换使用的「智能节点配置」；
  - B. 生成 **provider 数据文件**（仅 `proxies:` 列表），由用户现有主力 profile 通过一个 `file` 型 provider 引用它——不触碰现有规则，这与任务书「优先只输出 Provider」的目标最契合，但 provider 的 `path` 必须落在 Mihomo HomeDir 安全路径内（见 Q3）。
  MVP 建议先做 A（简单、可独立验证），阶段 3 再补 B。

### Q3 本地文件导入后，更新原文件能否同步到客户端？
**结论：已验证（源码级）——本地导入是「复制内容」，改原文件不会同步；但有两条可靠的更新通道。**
- `clash-verge-rev/src-tauri/src/config/profiles.rs`：导入时把文件内容（`file_data`）用 `fs::write` 写入 Verge 配置目录下以 uid 命名的 `{uid}.yaml`；`prfitem.rs` 的 `from_local` 只保存名称/描述/选项，不保留原始外部文件路径。`profiles.rs` 中未发现对原始文件的监听/同步逻辑（代码检索结论）。
- 可靠更新通道：
  1. **remote 型 profile + 定时更新**（见 Q4）：我们的工具若在本机起一个仅监听 127.0.0.1 的小 HTTP 服务提供配置文件，Verge 可按间隔自动拉取新版；
  2. **Mihomo file 型 proxy-provider**：provider 通过 `resource.Fetcher` 按 `interval` 重新读取文件（`mihomo/adapter/provider/provider.go` 中 `NewProxySetProvider` 以 interval 构造 Fetcher，`Update()` 调用 `Fetcher.Update()`），也可经 REST API 手动触发（Q6）。注意其 `path` 有安全路径限制：`ParseProxyProvider` 对 file/http 的 path 调用 `C.Path.IsSafePath` 校验，只允许 Mihomo HomeDir（可用环境变量 `SAFE_PATHS` 追加）——官方文档《代理集合配置》页亦有同样说明。

### Q4 是否有稳定的本地订阅更新机制？
**结论：已验证（源码级）——有，两层都具备。**
- Verge 层：`src-tauri/src/core/timer.rs` 实现了按 profile 的定时更新调度：读取每个 remote profile 的 `update_interval`（分钟，>0 才启用），到期（`now - updated >= interval*60`）触发重新下载。导入时 Verge 还能从订阅响应头读取流量信息（`subscription-userinfo`）与建议更新间隔（`profile-update-interval`，小时→分钟换算，见 `prfitem.rs`）。`from_url` 支持的选项包括 `with_proxy` / `self_proxy`（走系统代理或本机代理下载）、超时（默认 20 秒）、`danger_accept_invalid_certs` 等。
- Mihomo 层：http 型 provider 自带 `interval` 定时拉取（秒）与本地缓存文件（path 不填时按 URL 的 MD5 命名，见官方文档）。
- 结论：自动更新不需要我们自建机制——工具负责「生成新文件」，Verge/Mihomo 负责「按时取新文件」。工具自身的定时刷新（阶段 3）只需在文件层面做原子替换与失败保旧。

### Q5 Mihomo 如何做真实延迟检测？
**结论：已验证（源码级）。**
- 实现位置：`mihomo/adapter/provider/healthcheck.go` 的 `HealthCheck`：`process()` 按 `interval` 定时执行（`lazy` 为真且 provider 未被使用时跳过）；`execute()` 对每个代理并发调用 `p.URLTest(ctx, url, expectedStatus)`，单次超时由 `timeout` 控制（构造时默认 5000 ms）。
- 代理组侧：`adapter/outboundgroup/urltest.go` 的 `URLTest` 组基于同一套检测结果选最快节点（带 `tolerance` 防抖）；`fallback`、`load-balance` 组共用 `groupbase.go` 的健康检查基础设施。
- 检测语义：通过代理向测试 URL（常用 `https://www.gstatic.com/generate_204`）发真实 HTTP 请求并计时——是**真实网络延迟**，不是 TCP 握手伪测速。官方文档《代理集合配置》《代理组配置》页对 health-check 字段（enable/url/interval/timeout/lazy/expected-status）有完整说明。

### Q6 独立节点管理器能否复用 Mihomo 的健康检查？
**结论：已验证（源码级）——可以，经 REST API；有明确的安全前提。**
- API 路由在 `mihomo/hub/route/server.go` 挂载：`/proxies`、`/providers/proxies` 等。关键端点：
  - `GET /proxies/{name}/delay?url=...&timeout=...`（`hub/route/proxies.go` 的 `getProxyDelay`）：对单个代理执行 `URLTest` 并返回 `{"delay": ms}`；超时返回 504，失败返回 503；
  - `GET /group/{name}/delay`：对整个代理组批量测速并返回各节点延迟（官方 API 文档）；
  - `PUT /providers/proxies/{name}`：触发 provider 更新（`hub/route/provider.go` 的 `updateProvider`）；
  - `GET /providers/proxies/{name}/healthcheck`：触发 provider 全量健康检查（同文件 `healthCheckProvider`）；provider 内单节点测速为 `GET /providers/proxies/{provider}/{name}/healthcheck`。
- 鉴权（`hub/route/server.go` 的 `authentication`）：**仅当配置了 `secret` 时才启用** Bearer 鉴权（也支持 `?token=` 查询参数）；`secret` 为空则 API 无鉴权。
- 默认监听安全性：**Mihomo 不会替我们兜底**——`external-controller` 监听什么地址取决于最终配置。在 Verge 管理下，控制面由 Verge 接管（其 `src-tauri/src/config/clash.rs` 的 `guard` 逻辑强制写入 external-controller 等值，Windows 下还使用命名管道 `external-controller-pipe` 做 IPC）。因此阶段 2 的正确做法是：从本机 Verge 的配置中读取其控制器地址与 secret 再调用，**绝不能要求用户把未鉴权 API 暴露到局域网**；实机上的确切地址/secret 获取方式需在 Windows 上验证（未验证，见第 9 节）。
- 备用方案：若 API 不可用，工具可生成带 health-check 的 provider 配置，让 Mihomo 在后台持续检测，工具再从 API 的 `/proxies` 读取 `history`/`alive` 结果——仍依赖 API 只读访问。

### Q7 公开节点与私人订阅如何安全隔离？
**结论：机制已验证，隔离方案属设计建议（未在实机验证）。**
- 可依托的已验证机制：provider 天然按「集合」隔离（每个 provider 独立命名、独立文件、独立健康检查）；代理组用 `use` 精确挑选要引入的 provider，并支持 `filter` / `exclude-filter` / `exclude-type` 再筛选（`adapter/provider/parser.go` 的 schema 字段与官方文档一致）；provider 的 `override.additional-prefix` 可给节点名加来源前缀，避免重名与误选。
- 本项目的隔离设计（建议）：
  1. 数据层：SQLite 中每个来源带 `visibility`（private/public）与 `trust` 标记，私人订阅的原始 URL/凭据只存本地库，不进日志、不进生成的公开文件；
  2. 生成层：私人节点与公开节点**永远生成到不同的 provider 文件**，默认的代理组只 `use` 私人 provider；公开 provider 需用户显式开启才会被某个「公开池」分组引用——满足任务书「默认不把公开节点混入私人订阅」；
  3. 失效保护：公开池为空或全灭时，不生成空配置覆盖（与 Q2 的失败保旧策略一致）；
  4. 凭据：日志脱敏函数统一处理 Token/UUID/密码字段；`.gitignore` 排除 `data/`、`output/` 与真实配置。

### Q8 第一版可稳定解析的协议
**结论：已验证（以 Mihomo 当前源码为准）。**
- Mihomo 解析入口 `mihomo/adapter/parser.go` 的 `ParseProxy` 支持的 `type` 全集（Meta 分支当前源码）：`ss`、`ssr`、`socks5`、`http`、`vmess`、`vless`、`snell`、`trojan`、`hysteria`、`hysteria2`、`wireguard`、`tuic`、`shadowquic`、`gost-relay`、`direct`、`dns`、`reject`、`rematch`、`ssh`、`mieru`、`anytls`、`sudoku`、`masque`、`trusttunnel`、`openvpn`、`tailscale`、`zerotier`、`easytier`。
- 与任务书分批计划一致：第一批 **Shadowsocks / VMess / VLESS / Trojan** 均为内核一等支持，且各自有官方文档页（含必填字段表，可直接用作我们解析器字段校验的依据：`wiki.metacubex.one/config/proxies/ss|vmess|vless|trojan`）；第二批 **Hysteria2 / TUIC** 同样受支持，URI 格式更复杂（端口跳跃、QUIC 参数），后置合理。
- 注意：内核支持 `ssr` 的 YAML 形式，但 SSR 已被主流生态淘汰、且 V2RayAggregator 的存量 SSR 节点质量差——本项目**不解析 `ssr://` URI**（见第 4 节）。

### Q9 哪些功能只靠 Mihomo 即可完成？
**结论：已验证。** 以下不需要我们写代码，配置即可：
- 节点连通性/延迟的周期健康检查（provider health-check）；
- 按延迟自动选最快（url-test 组）、故障转移（fallback 组）、负载均衡（load-balance 组）；
- http/file provider 的定时更新与本地缓存；
- 按名称/类型过滤节点（filter / exclude-filter / exclude-type）、节点名覆写（override 前后缀与改名）；
- REST API 查询节点状态与延迟历史、触发测速与 provider 更新；
- 订阅流量/到期信息的透传展示（provider 的 subscription-info 由内核缓存，Verge 读取响应头呈现）；
- 实际代理连接、规则分流、DNS、TUN、系统代理——全部由 Verge+Mihomo 负责（任务书本来就要求不碰）。

### Q10 哪些功能需要自写 Python 代码？
**结论：已验证（即 MVP 的工作量边界）。**
- 多来源订阅的下载与容错（超时/大小/重定向限制、失败保旧）；
- 格式解析：Base64 订阅解码、URI 解析（ss/vmess/vless/trojan…，含字段级校验，不能只看前缀）、Clash YAML 中 `proxies` 的提取与清洗（剥离不可信的顶层键如 external-controller、script、危险规则）；
- 节点归一化模型与**稳定指纹去重**（协议+主机+端口+传输/TLS/SNI+认证摘要哈希）；
- SQLite 存储（节点、来源、检测历史、收藏/禁用）与凭据脱敏；
- 智能评分（成功率 45% / 延迟 30% / 稳定性 25% 的可配置权重）与筛选策略——Mihomo 只给原始延迟，跨时间的成功率与稳定性统计必须我们基于 API 采样落库后计算；
- Mihomo 配置的生成、校验（调用本机 Mihomo `-t` 或 Verge 的校验路径属阶段 1 实机验证项）、原子替换与回滚；
- CLI、定时刷新调度（文件层）、与 Verge 的对接流程（导入指引/本地 HTTP 服务方案）。

---

## 3. （并入第 2 节编号说明）
任务书的 10 个核心问题已全部在第 2 节逐项回答；其中 Q7 的隔离落地与 Q2 的交付方式二选一属设计建议，已在文中标注，其余均为源码/文档级已验证。

---

## 4. V2RayAggregator 分析

仓库结构（`master` 分支，2026-11-10 仍在更新）：来源清单 `sub/sub_list.json`（79 条来源，字段：id / remarks / site / url / update_method / enabled）；逐源抓取结果存 `sub/list/*.txt`（27 个文件）；合并产物为 `sub/sub_merge.txt`、`sub/sub_merge_base64.txt`、`sub/sub_merge_yaml.yml`，以及根目录的成品 `Eternity.yml`（完整 Clash 配置，约 213 个节点）、`Eternity.txt`（URI 列表）、`Eternity` / `EternityBase` 等。

### 4.1 流水线（GitHub Actions 驱动）
- `.github/workflows/merge.yml`（每 12 小时）：下载 **subconverter v0.7.2** 二进制在本机启动（监听 25500），再跑 `utils/list_merge.py` 完成抓取+转换+合并；
- `.github/workflows/speedtest.yml`（每 8 小时）：跑 `utils/speedtest/speedtest2.sh`——下载 **LiteSpeedTest** 二进制对合并订阅测速，结果写 `LogInfo.txt`，再跑 `utils/eternity_convert.py` 生成 Eternity 成品；
- `.github/workflows/Collector.yml` / `clash_yaml.yml`：机场（付费订阅试用）采集支线，本项目不涉及。

### 4.2 各文件职责与可借鉴点
| 文件 | 做什么 | 对本项目的价值 |
|---|---|---|
| `utils/get_subs.py` | 按 sub_list 逐源下载、解码、清洗（内含 get_subs / v2 / v3 三代实现并存） | 借鉴：来源清单的数据结构（id/remarks/url/update_method/enabled）可直接作为我们 Source Manager 的字段参考；`change_date` 型 URL（按日期拼 URL）是真实存在的来源形态，解析层要容忍 |
| `utils/sub_convert.py` | 格式转换核心：`format`（识别 Base64/URI/YAML）、`yaml_encode`（URI→Clash 字典）、`base64_decode/encode`、`yaml_decode`、`makeup`（去重+改名） | 借鉴：URI 粘连拆分、Base64 识别等脏数据处理经验；**去重逻辑可参考其比较维度**（server+port 相同再比 net/tls/id/password/cipher），但其实现为 O(n²) 两两比对且字段覆盖不全（无 SNI/flow 等），我们按任务书用指纹哈希重做 |
| `utils/list_merge.py` | 编排：遍历来源→转换→合并→写出 sub_merge* | 仅借鉴编排顺序；其 `add_valid` 只认 ssr/ss/trojan/vmess 前缀，正是任务书禁止的「只看前缀」做法，不采用 |
| `utils/eternity_convert.py` | 把测速日志（avg_speed）拼进节点名、按地区分 provider 文件、截断保留前 **200** 个节点生成 Eternity.yml | 借鉴：「评分结果体现在节点名/排序上」的呈现思路；截断 200 是其硬编码策略，我们改为可配置的筛选阈值 |
| `utils/subs_function.py` | `is_line_valid`（协议前缀白名单，vless 默认不开）、国家 emoji 改名、重名处理 | 改名/去重命名思路可借鉴；前缀白名单不采用 |

### 4.3 应舍弃的旧代码/旧协议
- **SSR**：`sub_convert.py` 与来源池含大量 `ssr://` 处理；Mihomo 生态已淘汰 SSR 订阅形态，本项目不解析；
- **对 subconverter 的运行时依赖**：其转换主路径（`convert_remote`）依赖本机 25500 端口的 subconverter 服务——这是外部二进制服务，不符合本项目「Python 标准库+少量依赖、本地可控」原则，我们的解析器自行实现四种优先协议；
- **三代并存的抓取函数与大段注释掉的旧代码**：只说明其技术债，不作为实现参考；
- **Eternity.yml 的整表照搬**：它是含 port/dns/external-controller 的**完整配置**，直接导入会与 Verge 的控制面接管冲突（Q2），我们只取其 `proxies` 数据，不取其配置壳；且它是公开免费节点池，质量与安全性不可控——按任务书仅作公开来源的输入样本，默认不与私人订阅混合。

### 4.4 安全风险（实证）
1. **工作流中硬编码凭据**：`speedtest.yml` 与 `clash_yaml.yml` 的推送步骤里写有明文 `github_token` 字段（本报告不复述其值）——典型的凭据入库反面案例，本项目须以 `.gitignore`+示例配置杜绝；
2. **CI 中下载并以 sudo 执行第三方二进制**（subconverter、LiteSpeedTest 均从 Release 直接下载运行）——供应链风险，本项目禁止；
3. **来源即攻击面**：79 条来源多为个人仓库/免费节点站，内容不可信（可能含失效、劫持或恶意配置）；其流水线用 `yaml.safe_load` 是对的，但对下载无统一的超时/大小/重定向约束（代码检索结论），本项目按任务书第 9.2 节补齐；
4. **测速结果不可迁移**：其测速在 GitHub Actions 的海外 runner 上执行，延迟数据对用户本地网络无参考价值——与任务书「不得把 Actions 测速作为本地质量依据」一致，本项目测速一律本机执行（Q5/Q6）。

---

## 5. Windows 环境检查：自查清单 + 实测结果

**执行说明**：调研运行在 Linux VM 上，无法直接检查用户 Windows 电脑，故由用户在 Windows 上运行下方命令自查。**2026-11-10 晚用户已回传 PowerShell 输出截图，结果如下：**

| 检查项 | 结果 | 结论 |
|---|---|---|
| 系统版本与架构 | 10.0.26100.0（Windows 11 24H2），AMD64 | ✅ 符合 Win10/11 x64 要求 |
| Python | 初查时 `python` 默认指向 3.8.10，`py` 启动器另有 3.10-64；**2026-11-10 当晚已按建议安装 Python 3.13**，`py -0p` 显示 3.13 为默认（*），3.10 保留共存 | ✅ 已达标：项目固定使用 Python 3.13（经 `py -3.13` 调用，避免误用旧版本） |
| Git | 初查时未安装；**2026-11-10 当晚已安装 Git 2.56.0.windows.4** 并验证 `git --version` 输出正常 | ✅ 已达标 |
| Clash Verge Rev | LOCALAPPDATA 路径不存在（False），但进程显示 clash-verge 运行于 `C:\Program Files\Clash Verge\clash-verge.exe`，clash-verge-service 与 verge-mihomo 进程均在运行 | ✅ 已安装（系统级安装）且正在运行，内置 Mihomo 内核工作中 |
| Verge 配置目录 | `%APPDATA%\io.github.clash-verge-rev.clash-verge-rev` 存在且完整：profiles/、profiles.yaml、config.yaml、verge.yaml、clash-verge.yaml、dns_config.yaml、geoip.dat、geosite.dat、Country.mmdb、ASN.mmdb 等 | ✅ 配置目录健康；阶段 2 对接所需的控制器/secret 存放位置后续在此目录内确认 |
| 目录可写性 | 在 C:\Users\20642 下成功创建测试目录 | ✅ 可写 |
| 项目目录 | 用户当前工作目录为 `D:\Deep seek Harness\SmartProxyManager` | 备注：项目计划放在 D 盘该目录 |
| Verge 应用版本 / 内核版本 | 2026-11-10 当晚用户回传首页截图：Verge **v2.5.10**、内核 **Mihomo v1.19.33**、混合端口 7897、服务模式运行 | ✅ 已补齐，且恰与本次调研查到的最新 Release 一致（v2.5.10 / v1.19.33），版本台账与实机对齐 |

环境基线结论：初查的两个缺口（Python、Git）已于 2026-11-10 当晚补齐，其余条件满足阶段 1 要求，环境基线检查完成。

在 PowerShell 中逐条运行：

```powershell
# 1. 系统版本与架构
[System.Environment]::OSVersion.Version; $env:PROCESSOR_ARCHITECTURE
# 2. Python（要求 3.11+，建议当前稳定版）
python --version; py -0p
# 3. Git
git --version
# 4. Clash Verge Rev 是否安装（开始菜单有图标也可；下面查常见路径与进程）
Test-Path "$env:LOCALAPPDATA\Programs\Clash Verge Rev"; Get-Process | Where-Object { $_.ProcessName -like "*verge*" -or $_.ProcessName -like "*mihomo*" } | Select-Object ProcessName, Path
# 5. Verge 配置目录与内置内核（确认控制器地址/secret 的存放位置，供阶段 2 对接）
Get-ChildItem "$env:APPDATA\io.github.clash-verge-rev.clash-verge-rev" -ErrorAction SilentlyContinue | Select-Object Name
# 6. 开发目录可写性（在计划放项目的目录里执行）
mkdir $HOME\SmartProxyManager-test -ErrorAction SilentlyContinue; "ok" | Out-File $HOME\SmartProxyManager-test\w.txt; Remove-Item -Recurse $HOME\SmartProxyManager-test
```

另需人工确认：打开 Clash Verge Rev → 设置页记录其**应用版本**与**内核版本**（关于/设置页可见），以及当前在用的订阅是否正常工作。

---

## 6. 最终技术选型

| 模块 | 选型 | 理由/证据 |
|---|---|---|
| 语言 | Python 3（Windows，3.11+；具体小版本待用户环境自查后固定） | 任务书指定；V2RayAggregator 亦为 Python，其数据结构可参考 |
| 代理内核/客户端 | Clash Verge Rev（官方稳定版）+ 内置 Mihomo | 不自维护内核；版本对应关系见第 1 节台账 |
| 存储 | SQLite（标准库 `sqlite3`） | 零依赖、单文件、够用 |
| YAML | **PyYAML 6.0.3（MIT，PyPI 元数据已核）**，只用 `safe_load` / `safe_dump` | 成熟事实标准；注意其默认 dump 需做排序与引号处理，生成后必须过校验 |
| HTTP | 阶段 1 先用标准库 `urllib`（零依赖、便于做超时/大小/重定向的显式控制）；若代码复杂度失控再引入 **httpx 0.28.1（BSD-3-Clause，PyPI 元数据已核）** | 订阅下载的风控点（超时、大小上限、重定向次数、UA）用标准库完全可控 |
| 测试 | pytest（其许可证为 MIT——PyPI 的 license 字段为空，**未在本环境直接核实**，引入前复核仓库 LICENSE） | 任务书指定 |
| 日志 | 标准库 `logging` + 自研脱敏过滤器 | 凭据脱敏是硬性要求（Q7） |
| 配置 | 本地 TOML（标准库 `tomllib` 只读）+ `config.example.toml` | 与任务书一致 |

依赖许可证小结：PyYAML = MIT（已核）；httpx = BSD-3-Clause（已核）；requests = Apache-2.0（已核，本选型不引入）；pytest = 待复核。上游三项目均为 GPL-3.0，本项目不复制其代码，故无传染性义务；V2RayAggregator 仅借鉴思路与字段设计。

---

## 7. 主要风险

1. **Verge 内置 Mihomo 版本滞后**：上游最新 v1.19.33 的字段（如 provider 的 age 加密、override-expr）在旧内核上可能不支持。对策：生成配置只用长期稳定的字段子集（type/url/path/interval/health-check/filter/override 前后缀），并在阶段 1 用实机内核做 `mihomo -t` 等价校验。
2. **控制面被 Verge 接管**：我们无法通过 profile 设置 external-controller/secret（会被丢弃）。阶段 2 调 API 必须先解决「如何拿到 Verge 当前控制器的地址与 secret」——路径存在（Verge 的本地配置）但**未实机验证**，是阶段 2 的第一个验证任务；在此之前不承诺 API 测速可用。
3. **file 型 provider 的安全路径限制**：provider 文件必须落在 Mihomo HomeDir 或 `SAFE_PATHS` 内，而 Verge 的 HomeDir 在其 AppData 目录下——工具的输出目录需据此规划（阶段 1 实机确认确切路径）。
4. **不可信订阅输入**：见任务书 9.2；解析层按「先清洗、后校验、再入库」处理，任何一步失败只丢弃该节点/该来源，不影响已有数据与配置。
5. **公开节点质量与合规**：免费节点池失效快、可能被劫持；仅作公开池隔离使用，默认关闭自动混入。
6. **调研环境的数据污染教训**：本次出现过「同名仓库内容被顶替」的异常（第 0 节）。后续阶段引用上游行为时，坚持以实机运行结果为准，不以单一网络来源下结论。

---

## 8. MVP 范围（阶段 1，与任务书一致，调研后确认无增删必要）

做：来源管理（本地 YAML / HTTP(S) URL / Base64 / V2RayAggregator 公开订阅四类输入）→ 下载容错 → 四种协议（SS/VMess/VLESS/Trojan）字段级解析 → 归一化 → 指纹去重 → SQLite 落库与统计 → 生成受控 Mihomo 配置（完整 profile 方案 A）→ 校验（YAML 结构 + 字段 + 可用时调内核验证）→ 失败保旧 → CLI（中文报错、正确退出码、`--help`）。
不做：GUI、自动测速与评分（阶段 2）、定时刷新与本地 HTTP 服务（阶段 3）、Hysteria2/TUIC 解析（预留接口）、修改 Verge/系统设置的任何行为。

---

## 9. 架构说明（文字版）

```
[订阅来源] 本地文件 / HTTP(S) / Base64 / V2RayAggregator 公开池
     │
Source Manager（来源登记、公私标记、启停）
     │
Subscription Fetcher（下载：超时/大小/重定向受控，失败保旧）
     │
Protocol Parser（Base64 解码 → URI/YAML 解析 → 字段级校验）
     │
Node Normalizer（统一 Node 模型）──► Storage Manager（SQLite：nodes/sources/history，凭据脱敏）
     │
Deduplication Engine（稳定指纹：协议+主机+端口+传输/TLS/SNI+认证摘要）
     │
（阶段2）Node Tester（调 Mihomo REST API 采样）─► Node Scorer（成功率/延迟/稳定性）
     │
Config Generator（受控 YAML：proxies / proxy-providers / groups，不写控制面键）
     │
Config Validator（结构+字段校验 → 临时文件 → 原子替换，失败回滚）
     │
Integration Layer ──► Clash Verge Rev（本地导入 / remote 更新 / file 型 provider）
     ▲
CLI（唯一入口，中文错误，退出码规范；核心逻辑在服务层，UI 后续可复用）
```

模块边界与任务书 3.1 一致；调研新增的约束只有两条：生成器不写控制面键（Q2）、输出目录需考虑 Mihomo 安全路径（Q3）。

---

## 10. 实施顺序

1. 用户完成第 5 节 Windows 自查 → 锁定 Python 小版本与 Verge/内核版本；
2. 初始化项目骨架（pyproject、目录、.gitignore、config.example、pytest 空跑通过）；
3. 数据层：SQLite schema + Node 模型 + 脱敏工具（含测试）；
4. 解析层：Base64/URI/YAML 四协议解析 + 指纹去重（固定样例测试）；
5. 下载层与来源管理（含失败保旧测试）；
6. 配置生成 + 校验 + 原子替换/回滚（离线测试）；
7. CLI 串联全流程；
8. 实机集成验证：生成配置导入 Verge、确认节点可见、（若可）用内核校验配置——通过后阶段 1 验收；
9. 阶段 2 先做「Verge 控制器地址/secret 获取」验证，再接 API 测速与评分。

---

## 11. 未验证事项清单

| # | 事项 | 原因 | 补验方式 |
|---|---|---|---|
| 1 | 用户 Windows 环境（系统/Python/Git/Verge 与内核版本） | 调研在 Linux VM 进行 | 第 5 节自查清单 |
| 2 | 生成配置在实机 Verge 中导入并真实出节点 | 无实机与真实节点 | 阶段 1 第 8 步集成验证 |
| 3 | Verge 当前控制器的地址/secret 的确切读取路径 | 只确认了 Verge 接管控制面的源码逻辑，未读实机配置 | 阶段 2 首个任务在实机核对 |
| 4 | file 型 provider 在 Verge 的 HomeDir 下的确切可用路径 | 源码有 IsSafePath 限制，实机路径未确认 | 阶段 1 实机确认 AppData 下目录结构 |
| 5 | pytest 许可证 | PyPI 元数据 license 字段为空 | 引入前查 pytest 仓库 LICENSE |
| 6 | mihomo 本地 git 完整克隆 | 本环境 git 通道异常，改用 API 局部镜像（关键文件已覆盖本报告全部引用点） | 在用户 Windows 上 `git clone` 三仓库复核 |
| 7 | 真实节点连接/测速 | 无真实合法测试节点（按任务书要求不得虚构） | 阶段 2 用用户自有订阅在本机验证 |

---

## 附：本地调研材料索引（`research/`，均为 GitHub API 按分支读取的局部镜像）

- `research/clash-verge-rev/`：LICENSE、`src-tauri/src/config/{prfitem.rs, profiles.rs, clash.rs}`、`src-tauri/src/core/timer.rs`、`src-tauri/src/enhance/{mod.rs, merge.rs}`（基准：dev @ 304a65f）
- `research/mihomo/`：LICENSE、`adapter/parser.go`、`adapter/provider/{parser.go, provider.go, healthcheck.go}`、`adapter/outboundgroup/{urltest.go, groupbase.go}`、`hub/route/{server.go, proxies.go, provider.go}`、`config/config.go`（基准：Meta @ 3f27ef3）
- `research/V2RayAggregator/`：LICENSE、`utils/{get_subs.py, sub_convert.py, list_merge.py, eternity_convert.py, subs_function.py, requirements.txt}`、`sub/sub_list.json`、`Eternity.yml`、`Eternity.txt`、`.github/workflows/{Collector.yml, merge.yml, speedtest.yml, clash_yaml.yml}`（基准：master @ 3b63ba6）
- 官方文档：wiki.metacubex.one《代理集合配置》《代理组配置》《APIs》及各协议页（2026-11-10 读取）
