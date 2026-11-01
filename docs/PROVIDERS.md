# 本地算力队列：provider 设计与接入

2026-10-30。目标是同一台 Mac 上的批量本地任务：H3、不同 TTS 方案，以及之后接入的其他计算程序。沿用 Python 标准库、SQLite、psutil 和原生 SwiftUI/AppKit。队列进程不导入模型库、不下载模型。

外部模型部署不随仓库分发。首次接入请先读 [安装](INSTALL.md) 和 [部署契约](DEPLOYMENT.md)；没有常驻服务时可使用独立会话模板，但不能替换已有 H3/Qwen 包装器。

## 边界与架构

```
CLI / 原生界面
  → 校验与入队（单条 / 原子批量）
  → SQLite jobs + attempts + cache + metrics
  → 单 worker：优先级降序、入队时间升序；每次一项
  → 独立 supervisor → 资源会话 → 通用 executor
  → provider → 受保护的子进程 → 校验产物
```

- provider：接入实现。内置 `h3`、`tts`；其他实现使用注册的命令协议。
- profile：同一 provider 下的模型、运行时或档位。TTS 不把每个模型硬编码为一个队列类型。
- 任务：固定输入、配置快照、部署依赖与输入指纹。attempt：一次执行，失败/停止后重试新建目录。
- 资源需求：`device: gpu|cpu`、`min_available_gib`（0–64 GiB，0 表示沿用系统保护值）。声明在 provider/注册清单中，任务不能自行降低。实际门槛取全局与 provider 的较大值。
- 产物：主文件路径、SHA256、类型、元数据、技术验收标记。`audio` 为可解码且非静音 PCM16 WAV；`video` 需要解码与视频流；`json` 需要合法 JSON；`file` 只保证非空和完整性。语义与观感仍需人工审核。

**第一版所有任务串行，不承诺 CPU/GPU 并发或 GPU 百分比分配。** 资源声明为将来的准入/并发策略留出边界；当前策略可预测，也避免模型争抢。队列不会抢占正在运行的任务。优先级只影响下一项；全局暂停、时段、智能空闲及保护锁适用于所有 provider。

H3 的中断片段需要重做。TTS 按自然段入队，失败只重做对应段；第一版每项启动独立进程并释放模型，尚未实现常驻模型或跨任务暖缓存，估时包含加载开销。

## 共享资源协议

所有接入使用部署根目录的 `.codex-inference.lock`，与已有 H3/Qwen 入口共享。锁覆盖运行、子进程清理及 Qwen 恢复。

- H3 继续通过原有 `agent_session.py h3 -- ...`，不修改共享部署脚本，因此旧请求的部署 SHA 不变。
- 新 GPU provider 由 `resource_session.py` 获取同一文件锁，复用部署的 `service` / `ready` 辅助函数；仅当 Qwen 原先在运行时临时停止并恢复原 profile / prefix-cache 配置。
- CPU provider 同样持锁，但不停止/启动 Qwen。CPU 是接入方对程序实际行为的声明，不是操作系统沙箱。
- 新 provider 等锁时可取消；取消后不切换 Qwen。H3 保留旧包装器行为：若它已经在包装器内等锁，STOP 会在取得锁并进入执行器后生效，不能强杀包装器。
- `waiting_resource / preparing / running / restoring` 明确区分等锁、准备、执行和恢复。等锁时间不消耗生成耗时估计。
- 这是协作协议，不能约束不经过队列/共享包装器的外部推理进程。其他项目应提交队列请求；不要直接调用底层 TTS benchmark worker、模型 API 或底层引擎来绕过锁。不要在已持锁的命令内部再调用队列并等待它完成。

## 使用内置 TTS

先执行 `./queue providers` 查看配置与本地文件是否存在。`files_present` 只表示配置路径存在，不代表模型已通过真实合成或质量验收。

```json
{
  "schema_version": 1,
  "provider": "tts",
  "profile": "qwen-custom",
  "text": "这是第一段配音。",
  "language": "zh",
  "seed": 42,
  "options": {"voice": "Vivian"}
}
```

```sh
./queue enqueue /absolute/tts.json --title '课程 · 第001段'
./queue status
# 只有用户明确启动时才执行 ./queue start / auto / smart
```

配置来自部署的 `TTS/profiles.json`。目前适配 `mlx-audio`、`mlx-audio-plus`、`indextts`、`auk`，使用每个 profile 自己的 Python 环境。本项目不改其环境/权重，也不依据目录名自动安装新模型。执行时启用 Hugging Face / Transformers 离线模式；缺依赖会明确失败。

克隆音色的 profile 必须显式提供 `reference_audio`（绝对路径、0.1–60 秒、单/双声道、PCM16 WAV）。`reference_text` 为对应逐字转写，Qwen Base / Ming / Fish 必填。非克隆 profile 不接受参考音频。语言必须在 profile 声明的列表中。

`options` 传递模型参数，不允许覆盖文本、参考素材、模型、输出路径或流式开关。IndexTTS 支持 `diffusion_steps/use_gpt_latent/temperature/emotion`；AuK 支持 `gen_seconds/nfe`，长段需拆分；其他 MLX 接口的选项取决于部署版本，不兼容参数会失败，不静默改用其他模型。配置的 generation 默认值仍生效。音色选择可用 MLX 方案的 `options.voice`；这些名称由对应模型定义。

参考素材做内容 SHA256；选中 profile 存完整快照；runner、共享会话入口、环境元数据做 SHA256。模型目录保存文件路径/大小/纳秒修改时间清单，用于检测通常的本地变更，**不是全量权重 SHA256 证明**。权重保持原部署不变；更新权重/模型配置应新建请求。独立环境内的手动代码修改也应更新部署版本或相关配置，不复用旧缓存。

## 批量入队

```json
{
  "schema_version": 1,
  "defaults": {"provider": "tts", "profile": "qwen-custom", "language": "zh"},
  "jobs": [
    {"title": "课程 · 001", "request": {"text": "第一段配音。"}},
    {"title": "课程 · 002", "request": {"text": "第二段配音。"}}
  ]
}
```

`./queue enqueue-batch /absolute/batch.json`，或通过界面的 JSON 导入。每批 1–500 项、文件不超过 4 MiB。defaults 与各项 request 做顶层覆盖。整批在一笔事务内提交；任一项校验失败整批回滚。相同指纹复用已有任务；返回的 imported 是输入项数量，去重后的任务数可能更少。导入不启用运行；若队列原本已获授权运行，新任务按当前模式执行。

不自动按标点切文本，避免改变课程分段、语气或参考音色；上游生成明确的段落列表。第一版也不隐含创建 TTS → H3 依赖图；上游确认音频、裁切和长度后再入队 H3。

## 接入其他本地程序

注册是安装受信任本地代码的操作；只注册用户认可的程序。清单示例：

```json
{
  "protocol": 1,
  "id": "my-transcriber",
  "label": "本地转写",
  "revision": "2026-10-30-v1",
  "argv": ["/absolute/venv/bin/python", "/absolute/runner.py", "--request", "{request}", "--output", "{output}"],
  "dependencies": ["/absolute/runner.py", "/absolute/model-config.json"],
  "resources": {"device": "gpu", "min_available_gib": 8},
  "output": "transcript.json",
  "output_kind": "json"
}
```

```sh
./queue register-provider /absolute/provider.json
./queue providers
./queue enqueue /absolute/request.json --title '课程 · 转写'
```

请求：

```json
{
  "schema_version": 1,
  "provider": "my-transcriber",
  "profile": "default",
  "payload": {"language": "zh"},
  "assets": {"audio": "/absolute/source.wav"}
}
```

runner 读取 `{request}` 指向的 attempt 请求 JSON，其中 `spec.payload` 是业务参数，`spec.assets` 是已解析的输入绝对路径。输出写入 `{output}`，在 attempt 的 `artifacts/` 内。返回非零退出码表示失败。stdout/stderr 自动写入 `render.log`；不把详细请求全文写入 UI。

argv 不经 shell，且只有整个参数为 `{request}`、`{output}`、`{workdir}` 时替换。用户文本只能从 JSON 读取。程序/脚本绝对路径及显式 dependencies 会固定 SHA256；额外模型/配置文件应列在 dependencies 或用 revision 固定不可变部署。若注册的是 `python -m ...`，必须显式声明模块文件依赖。不能把真正推理放后台，也不能越过保护另起不受管理的服务。

修改清单需 `register-provider ... --replace`，不会启动任务。旧任务仍保存旧快照；入口/依赖变化会拦截并暂停。`retry --refresh-deployment` 只接受审阅过的入口变化，不能接受输入、模型或参数改变；改变这些内容应新建请求。

有特殊验收或多阶段流程时，可添加 Python provider，实现 `normalize / resources / describe / run`，在 registry 注册。run 通过 ExecutionContext.run 启动子进程，返回规范产物；公共队列不应出现新的模型名分支。`h3` 是为兼容历史行为而保留的迁移适配器。

## 数据兼容和估时

- SQLite v4 只新增 provider_metrics 表及索引，不改 jobs、attempts、cache 或已有 settings。
- 旧请求没有 provider 字段时视为 h3；旧 normalize 输出和指纹不变，保留全部历史结果与失败证据。
- H3 继续使用原有 benchmarks/energy_metrics；其他 provider 按 provider + 配置指纹 + 机器隔离样本。TTS 只用相近文本长度粗估，无样本显示未知。
- 能耗仍是整机监测估计，不能当作某模型独占电量或插座读数。
- 应用磁盘路径、bundle ID、后台服务标识、H3_QUEUE_HOME 环境变量保持兼容。界面改用本地队列文案，并根据产物提供试听/预览/打开。

## 验证边界

隔离测试覆盖旧 H3 流程、多 provider 串行、共享锁争用与取消、Qwen 状态恢复、独立重试、批量原子性、缓存/估时隔离、来源变更、音频格式与文件范围检查。使用轻量假模型与短 WAV，不启动真实 H3/TTS，不改生产运行模式。

真实 TTS 质量、各 profile 依赖完整性、实际速度和资源峰值仍需用户授权后的实际合成验证；“适配代码就绪”不等于所有模型已经质量验收。
