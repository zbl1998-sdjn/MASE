<div align="center">

# MASE
**A dual-whitebox memory engine for LLM agents.**
**88.71% on LV-Eval 256k with a local 7B model.**

> 🚫 **拒绝向量黑盒。把 Agent 记忆重新变成可读、可改、可验证的工程系统。**
> SQLite 负责结构化事实，Markdown / tri-vault 负责人类可读审计。
> **先治理记忆，再喂模型上下文。**

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-Apache%202.0-green)
![Tests](https://img.shields.io/badge/tests-69%2F69%20passing-brightgreen)
![Concurrency](https://img.shields.io/badge/concurrency-battle--tested-orange)
![NoLiMa-32k](https://img.shields.io/badge/NoLiMa--32k-60.71%25%20(%2B58.9pp)-red)
![LongMemEval](https://img.shields.io/badge/LongMemEval--S-84.8%25-blueviolet)

<b>中文</b> | <a href="docs/README_en.md">English</a>

![MASE vs baseline on NoLiMa long-context (3-way comparison)](docs/assets/nolima_3way_lineplot.png)

</div>

## What MASE Is

MASE 是一个**双白盒 Agent 记忆引擎**。

它不把记忆默认建在向量数据库之上，而是把 Agent 记忆拆成两类更可控的对象：

- **Event Log**：保留原始对话与检索入口
- **Entity Fact Sheet**：保存最新、可覆盖的结构化事实

这意味着 MASE 关注的首先不是“如何把更多上下文塞回模型”，而是：
**如何把冲突事实治理干净，再把最小必要事实交给模型。**

## Why Not Black-Box Memory

MASE 反对把 Agent 记忆默认做成黑盒向量召回，原因很简单：

1. **事实会更新，不是只会堆积。**
2. **记忆如果不可检查，就不可调试。**
3. **长上下文问题首先是上下文治理问题，而不只是窗口大小问题。**

## How MASE Works

MASE 的主叙事是记忆系统，不是 runtime 功能列表。

- **L1: SQLite + FTS5**：负责事件流水账与结构化事实检索
- **L2: Markdown / tri-vault**：负责人类可读、可迁移、可审计的记忆外化
- **Entity Fact Sheet**：新事实覆盖旧事实，避免冲突事实并存
- **Runtime Flow**：Router → Notetaker → Planner → Action → Executor，用来实现这套记忆引擎

## Evidence

| Benchmark | Model | MASE | Naked baseline | Δ |
|---|---|---|---|---|
| LV-Eval EN 256k | qwen2.5:7b local | **88.71%** | **4.84%** | **+84pp** |
| NoLiMa ONLYDirect 32k | qwen2.5:7b local, MASE chunked | **60.71%** | **1.79%** | **+58.9pp** |
| LongMemEval-S 500 | GLM-5 + kimi-k2.5 + LLM-judge | **84.8%** | **70.4%** | **+14.4pp** |

这三组数字分别证明：

- MASE 不只是“能记”，还能在长上下文里稳定提纯事实
- 架构本身，而不是模型参数量，决定了长上下文是否可用
- 它不是实验室概念稿，而是已经被 benchmark 和审计反复打磨过的工程项目


## 🚀 快速开始 (Quick Start)

### 0. 一键 clone + install (3 分钟)

```bash
# 1. 克隆仓库
git clone https://github.com/zbl1998-sdjn/MASE-demo.git
cd MASE-demo

# 2. 安装依赖（建议先 python -m venv .venv && source .venv/bin/activate）
pip install -e ".[dev]"

# 3. 复制环境变量模板（按需填入 GLM/Kimi/OpenAI key，本地模式可空）
cp .env.example .env

# 4. 冒烟测试（69 个单测应全绿）
python -m pytest tests/ -q
```

### 环境要求
- Python 3.10+
- Ollama（当前默认 benchmark baseline 使用本地 Ollama）
- 对应的 LLM API Key (.env 配置)

### 本地 Ollama 模型准备（当前测试栈）
当前 `config.json` 默认使用的是本地小模型编排，不再把 `Qwen3.5-27B` 作为默认测试范围。开跑前请先拉齐以下模型：

```bash
ollama pull qwen2.5:0.5b
ollama pull qwen2.5:1.5b
ollama pull qwen2.5:3b
ollama pull qwen2.5:7b
ollama pull deepseek-r1:7b
ollama pull ibm/granite3.3:2b
ollama pull lfm2.5-thinking:1.2b
```

其中：
- `qwen2.5:0.5b / 1.5b / 3b / 7b`：路由、记事、通用执行
- `deepseek-r1:7b`：深度推理 / planner / 核查
- `ibm/granite3.3:2b`、`lfm2.5-thinking:1.2b`：英文与辅助链路

### 1. 启动记忆控制台 (CLI)
随时查看或修改 AI 的记忆状态：
```bash
python mase_cli.py
```

### 2. 运行后台记忆整理 (Memory GC)
手动触发或设置定时任务，让 AI 提纯最近的对话记录：
```bash
python mase_tools/memory/gc_agent.py
```

### 3. 启动主 LangGraph 引擎
体验完整的 路由->记忆检索->规划->外部工具->执行 的全流程：
```bash
python langgraph_orchestrator.py
```

---

## 📂 目录结构说明

```text
E:\MASE-demo\
├── langgraph_orchestrator.py   # MASE 核心引擎（基于 LangGraph）
├── notetaker_agent.py          # 负责 SQLite 事实与流水账的读写
├── planner_agent.py            # 负责根据记忆生成执行计划
├── executor.py                 # 终极节点：根据上下文生成最终回复
├── mase_cli.py                 # 记忆的物理管理面板 (CRUD)
├── mase_tools/
│   ├── memory/
│   │   ├── db_core.py          # SQLite FTS5 与 Upsert 核心逻辑
│   │   ├── api.py              # 暴露给智能体的极简读写接口
│   │   └── gc_agent.py         # 异步记忆垃圾回收与提纯
│   └── mcp/
│       └── tools.py            # 外部工具集（支持 MCP 协议接入）
└── legacy_archive/             # V1 版本的旧代码（JSON 记忆、大单体循环等），仅供参考
```

---

*“最好的 AI 记忆，不应该是黑盒里的向量浮点数，而是清晰可见、人类可读、随时可被修正的结构化事实。”* — **MASE**

---

## 🤝 贡献 / Star History

### Contributing

欢迎 issue / PR — 特别欢迎以下方向的贡献：

- **新模型后端适配**: vLLM / llama.cpp / Together / OpenRouter 等 (`src/mase/model_interface.py`)
- **更多 integrations**: AutoGen / CrewAI / Semantic Kernel
- **新 benchmark 复跑**: BABILong / RULER / ∞Bench 适配 (`benchmarks/runner.py`)
- **bug 报告**: 长上下文召回失败案例尤其欢迎，附最小复现 + `data/mase_memory.db` 片段

提 PR 前请先跑 `python -m ruff check . && python -m pytest tests/ -q`，CI 全绿才能 merge。

### Citation

如果 MASE 帮到了你的研究，请引用：

```bibtex
@software{mase2026,
  author = {zbl1998-sdjn},
  title = {{MASE}: Memory-Augmented Smart Entity — Schema-less SQLite memory for LLM agents},
  year = {2026},
  url = {https://github.com/zbl1998-sdjn/MASE-demo},
  note = {Lifts qwen2.5:7b from 1.79\% to 60.71\% on NoLiMa-32k; 84.8\% on LongMemEval-S}
}
```

### Star History

[![Star History Chart](https://api.star-history.com/svg?repos=zbl1998-sdjn/MASE-demo&type=Date)](https://star-history.com/#zbl1998-sdjn/MASE-demo&Date)

### License

[Apache-2.0](LICENSE) © 2026 zbl1998-sdjn

---

## 💡 写在最后 (A Note from the Developer)

坦白讲，我只是一个**接触大模型仅 3 个月的新手**。

在探索 AI 的过程中我深刻地意识到：当人们面对一个深不可测、强大到宛如黑盒的 AI 个体时，**内心的恐惧往往要大于惊喜**。我们害怕它悄悄篡改记忆，害怕它产生无法理解的幻觉，害怕失去控制权。

这正是 MASE 放弃拥抱庞大黑盒、选择"双白盒"的初衷。在这个系统里：

> **没有无所不能的"个人英雄主义"，只有各司其职的"齐心协力"。**

我们不要求一个单一的巨型模型面面俱到，而是让 2.72 MB 的轻量级核心串联起 **Router / Notetaker / Planner / Action / Executor** 五个节点，让每个小模型各有所长，交织运作。正因为 MASE 保持了极简架构，它反而为未来的生态扩展（多智能体协同、MCP 接入、插件化）预留了无限可能。

**开源的魅力就在于不需要一个人做到完美。** 如果你也认同这种透明、极简、协作的理念，欢迎加入 MASE。我们一起，各有所长，搭好这个稳固的地基。

— *zbl1998-sdjn, 2026 春*
