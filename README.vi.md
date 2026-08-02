<div align="center">

# sag-agents-plugin

**Biến [SAG](https://github.com/Zleap-AI/SAG) thành knowledge base chung, ghi được, cho các AI coding agent — mà không sửa một dòng source code nào của SAG.**

[![CI](https://github.com/vuongdam2k01/sag-agents-plugin/actions/workflows/ci.yml/badge.svg)](https://github.com/vuongdam2k01/sag-agents-plugin/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Dependencies: none](https://img.shields.io/badge/dependencies-stdlib%20only-green.svg)](#nguyên-tắc-thiết-kế)

*[English](README.md) · [Tiếng Việt](README.vi.md)*

</div>

---

## Đây là gì

SAG có sẵn một MCP server **chỉ đọc** rất tốt: 8 tool truy xuất trên một corpus tài liệu
đã được index. Thứ SAG không có là nửa còn lại của vòng lặp — một đường an toàn để agent
*đóng góp* ngược vào corpus đó.

`sag-agents-plugin` chính là nửa còn lại. Nó cài thẳng vào **Claude Code**, **Hermes
Agent** và **Codex**, mang lại cho agent:

- **Đọc** — MCP server upstream của chính SAG (`sag`), giữ nguyên, 8 tool.
- **Ghi** — một MCP server chạy local (`sagw`, 6 tool) cộng với CLI (`sagctl`), cả hai
  dùng chung một engine, chỉ giao tiếp với SAG qua **REST API công khai**.
- **Phán đoán** — 7 skill dạy agent *khi nào* một tài liệu là tri thức bền vững đáng chia
  sẻ, cùng một hợp đồng tự đánh giá có kiểu (typed) bắt buộc phải điền trước khi ghi bất
  cứ thứ gì.
- **Sàn an toàn** — một tập kiểm tra tất định, không dùng LLM (trạng thái git, luật
  allow/deny theo path, quét secret, trần chi phí) chạy trước **mọi** lần upload và không
  thể bị model thuyết phục bỏ qua.

> **Hợp đồng hành vi và kỹ thuật nằm ở [docs/SPEC.md](docs/SPEC.md)** — file đó là chuẩn.
> `docs/DESIGN.md` và `docs/AGENT-BEHAVIOR.md` là nhật ký thiết kế giải thích *tại sao*;
> khi mâu thuẫn, SPEC.md thắng.

### Vì sao "không sửa source" lại quan trọng

Mọi thao tác đều đi qua REST API đã được tài liệu hoá của SAG và MCP server có sẵn của
nó. Bạn có thể nâng cấp SAG, hoặc trỏ plugin sang một instance SAG của người khác, mà
không cần fork, không cần hàng đợi patch, không cần migration. Cái giá phải trả là plugin
phải tự khám phá hành vi thật của SAG bằng thực nghiệm — đó chính là việc `sagctl
selftest` làm (17 case thăm dò, kết quả ghi lại trong [docs/SPEC.md](docs/SPEC.md)).

---

## Mục lục

- [Kiến trúc](#kiến-trúc)
- [Bắt đầu nhanh](#bắt-đầu-nhanh)
- [Cài đặt](#cài-đặt)
- [Cấu hình: manifest](#cấu-hình-manifest)
- [Publish không cần file, không cần repo](#publish-không-cần-file-không-cần-repo)
- [Một lần publish diễn ra thế nào](#một-lần-publish-diễn-ra-thế-nào)
- [MCP tools](#mcp-tools)
- [Tham chiếu CLI](#tham-chiếu-cli)
- [Skills](#skills)
- [Mô hình bảo mật](#mô-hình-bảo-mật)
- [Phát triển](#phát-triển)
- [Cấu trúc repo](#cấu-trúc-repo)
- [Tài liệu](#tài-liệu)
- [Đóng góp](#đóng-góp)
- [Giấy phép](#giấy-phép)

---

## Kiến trúc

```text
┌─────────────────────────────────────────────────────────────┐
│  Agent host  (Claude Code · Hermes Agent · Codex)           │
│                                                             │
│   skills/  ── phán đoán: đây có phải tri thức bền vững?     │
│   hooks/   ── nhắc nhận thức + mint token thủ công 1 lần    │
└──────────┬─────────────────────────────────┬────────────────┘
           │ ĐỌC                             │ GHI
           │                                 │
   ┌───────▼────────┐              ┌─────────▼──────────┐
   │  MCP  `sag`    │              │  MCP  `sagw`       │
   │  upstream SAG  │              │  scripts/          │
   │  8 tool đọc    │              │  sagw_server.py    │
   │  read token    │              │  6 tool ghi        │
   └───────┬────────┘              └─────────┬──────────┘
           │                                 │
           │                       ┌─────────▼──────────┐
           │                       │  engine sagctl     │
           │                       │  sàn an toàn ·     │
           │                       │  routing · audit   │
           │                       │  (cũng là CLI)     │
           │                       └─────────┬──────────┘
           │                                 │ write token
           │                                 │ (~/.sagctl/, không vào env agent)
   ┌───────▼─────────────────────────────────▼──────────┐
   │              SAG  (giữ nguyên, không sửa)          │
   │              REST API  +  MCP có sẵn               │
   └────────────────────────────────────────────────────┘
```

Một engine, ba bề mặt tiêu thụ. Đường đọc và đường ghi dùng **hai token khác nhau**, và
write token không bao giờ vào môi trường của agent.

---

## Bắt đầu nhanh

Cài plugin xong thì gõ `/sag-setup` và trả lời câu hỏi của nó — skill sẽ đo instance SAG
của bạn, mint token, scaffold manifest, và nối agent tool này vào. Nó có hai chế độ:
**bootstrap** dựng scope mới, hoặc **join** vào scope agent khác đã tạo (bạn đưa
`source_id`).

Bản làm tay, nếu bạn muốn tự điều khiển:

```bash
git clone https://github.com/vuongdam2k01/sag-agents-plugin.git
cd sag-agents-plugin

# 1. Cài engine (đặt `sagctl` lên PATH, tạo ~/.sagctl/)
#    Dùng python3 hoặc python — tuỳ máy bạn có cái nào.
python3 scripts/install-shim.py

# 2. Đăng nhập — lưu write token tại ~/.sagctl/credentials.json (quyền 0600)
sagctl login --url http://<sag-host>:8000 --name <tên-của-bạn>

# 3. Đo chính instance của bạn — key_format là kết quả đo, không phải hằng số
sagctl setup probe --url http://<sag-host>:8000 --token <token>

# 4. Tạo source và nối vào một project
sagctl source create "my-project-knowledge"
cp examples/sag-sync.example.json /đường-dẫn/tới/repo/.sag-sync.json
#   → sửa source_id trong file đó

# 5. Xem trước sẽ publish gì, rồi chạy thật
sagctl sync --manifest .sag-sync.json          # mặc định là dry-run
sagctl sync --manifest .sag-sync.json --yes
```

**Yêu cầu:** Python 3.11+, Git, một instance SAG truy cập được. Không cần package pip nào.

---

## Cài đặt

### Claude Code

```bash
claude plugin marketplace add https://github.com/vuongdam2k01/sag-agents-plugin
claude plugin install sag-agents
```

Đặt biến môi trường phía đọc trước khi dùng:

```bash
export SAG_URL="http://<sag-host>:8000"
export SAG_READ_TOKEN="<token chỉ đọc>"
```

**Write token cố ý không nằm trong môi trường agent** — nó ở
`~/.sagctl/credentials.json`, được `sagw`/`sagctl` đọc tại thời điểm gọi. Xem
[Mô hình bảo mật](#mô-hình-bảo-mật).

Plugin đăng ký bốn hook ([hooks/hooks.json](hooks/hooks.json)), slash command
`/sag-publish`, và 7 skill. Plugin **không** tự đăng ký `.mcp.json` ở cấp plugin — bản
trước có, và nó phát ra một URL đọc không scope (`${SAG_URL}/mcp/`, không có
`source_id`) mà mọi project cùng bật plugin đều âm thầm chạm tới được, đồng thời chạy
song song một server `sagw` thứ hai, versioned độc lập với bản project-scoped (phát
hiện thật, 2026-08-02). MCP server luôn được sinh riêng theo từng project, scope theo
`source_id` của project đó:

```bash
sagctl adapter-emit claude-code --write .
```

Chạy lệnh này một lần cho mỗi repo bạn muốn có SAG tools — xem
[adapters/claude-code/](adapters/claude-code/).

### Hermes Agent

```bash
sagctl adapter-emit hermes --plugin-root /opt/agent-skills/sag-agents-plugin
```

Sinh ra `mcp_servers`, `skills.external_dirs`, và phần chia profile theo vai trò. Xem
[adapters/hermes/](adapters/hermes/).

### Codex

```bash
sagctl adapter-emit codex --plugin-root /opt/agent-skills/sag-agents-plugin
```

Lệnh này in ra khối cấu hình cho `config.toml` và phần cho `AGENTS.md`, mỗi khối có một
version marker để phát hiện lệch phiên bản. Xem [adapters/codex/](adapters/codex/).

### Engine (bắt buộc cho cả ba tool)

Trên Claude Code plugin đã mang sẵn engine — gõ `/sag-install-engine` thay vì clone. Nơi
khác thì từ một checkout:

```bash
python3 scripts/install-shim.py
```

```bash
sagctl login --url <SAG_URL> --name <tên>
```

`sagctl` chạy trên Python 3.11+, **chỉ dùng stdlib**, và là bản cài đặt duy nhất đứng sau
CLI, MCP server `sagw`, và mọi hook.

---

## Cấu hình: manifest

Mỗi repo publish lên SAG mang theo một file `.sag-sync.json` đặt ở một thư mục là **tổ
tiên (ancestor) của commit đang được publish**:

```json
{
  "source_id": "...",
  "sandbox_source_id": "...",
  "key_format": "flat",
  "require": "committed",
  "canonical_branch": "main",
  "min_confidence": 0.8,
  "criteria": [
    { "id": "c1", "text": "Không đưa meeting notes vào" }
  ],
  "deny_paths": ["docs/pricing/**"],
  "ask_paths": [],
  "include": ["docs/**/*.md"],
  "exclude": [],
  "max_files": 50,
  "max_publishes_per_day": 30,
  "stale_branch_days": 14
}
```

`include` ở trên (`docs/**/*.md`) là lựa chọn của *repo ví dụ* này — chỉ publish thư mục
docs — không phải mặc định của engine. Mặc định thật là `["**/*"]`: mọi định dạng SAG
nhận (`.pdf`, `.docx`, `.csv`, `.json`, ...), không chỉ markdown. Provenance của những
định dạng không nhét được YAML frontmatter thì nằm trong state store thay vì trong bytes
của file — xem [Publish không cần file, không cần repo](#publish-không-cần-file-không-cần-repo).

| Trường | Ý nghĩa |
|---|---|
| `key_format` | `flat` (mặc định) hoặc `path`. **Hãy kiểm chứng bằng `sagctl selftest --case S1`** — phần lớn instance SAG cắt tên file upload về basename, đó là lý do `flat` là mặc định. |
| `require` | Trạng thái Git tối thiểu để được publish: `committed` (mặc định) · `pushed` · `merged`. Chỉ áp dụng khi manifest nằm trên một repo Git thật — ngoài repo thì điều kiện này không áp dụng, không phải bị bỏ qua. |
| `canonical_branch` | Chỉ dùng bởi `require: pushed\|merged` và bởi kiểm tra stale-branch của `maintain` — ngoài ra là tham số chết. |
| `include` | Mặc định `**/*` — mọi định dạng SAG nhận, không chỉ markdown (SPEC A3). Thu hẹp nó một cách có chủ đích; thu hẹp `include` là âm thầm quyết định cái gì được coi là tri thức trước khi model kịp được hỏi, và `doctor --unassessed` cũng chỉ quét trong phạm vi đó. |
| `min_confidence` | Dưới ngưỡng này, verdict `knowledge` sẽ vào hàng đợi chờ người duyệt thay vì auto-publish. |
| `criteria` | Luật bằng ngôn ngữ tự nhiên cho *model* phán đoán. Nếu có criteria mà assessment không ack cái nào ⇒ đẩy vào queue, không auto. |
| `deny_paths` | Chặn tất định ở phía engine. Chặn **cả manual mode**. |
| `ask_paths` | Ép vào hàng đợi duyệt; manual mode có thể thoả mãn được. |
| `max_publishes_per_day` | Trần chi phí, do engine cưỡng chế. |

**Thứ tự ưu tiên:** `deny_paths` > `ask_paths` > `include`/`exclude` > `criteria` >
`confidence`.

Trạng thái runtime (config, audit log, queue, bộ đếm chi phí) nằm dưới
`~/.sagctl/<sha256(source_id)[:12]>/` — **không bao giờ trong repo**. Engine sẽ abort nếu
phát hiện `sagctl.config.json`, `audit.jsonl`, hay `queue.jsonl` bên trong working tree.
Khi các agent chạy trên nhiều máy, hãy trỏ tất cả về một state service dùng chung — xem
[Chạy agent trên nhiều máy](#chạy-agent-trên-nhiều-máy).

Bắt đầu từ [examples/sag-sync.example.json](examples/sag-sync.example.json).

---

## Chạy agent trên nhiều máy

Scope là một `source_id`, không phải một thư mục. Bao nhiêu agent, trên bao nhiêu máy,
trong bao nhiêu repo cũng được — chúng dùng chung một scope bằng cách khai cùng
`source_id` trong `.sag-sync.json` của mình. Việc publish vẫn đúng mà không cần phối hợp
gì: `publish_one()` không bao giờ tin state cục bộ — nó luôn liệt kê document theo key
trên SAG rồi mới replace, nên SAG giữ inventory và các máy tự hội tụ.

Ba thứ **không** tự hội tụ, vì chúng là file cục bộ của từng máy:

| | Hệ quả trên N máy |
|---|---|
| `cost.json` | `max_publishes_per_day` thành N × giá trị trong manifest |
| `queue.jsonl` | item vào queue ở máy A không thể duyệt từ máy B |
| `audit.jsonl` | `doctor` và post-hoc review mỗi máy chỉ thấy 1/N lịch sử |

Chạy state service một lần, ở nơi cả fleet truy cập được:

```bash
SAGSTATE_TOKEN=<shared-secret> python scripts/sagstate_server.py --host 0.0.0.0 --port 9000
```

Rồi trên mỗi máy chạy agent:

```bash
export SAGCTL_STATE_URL="http://<state-host>:9000"
```

```bash
export SAGCTL_STATE_TOKEN="<shared-secret>"
```

Đó là toàn bộ cấu hình — một cost cap, một queue, một audit log cho cả fleet. Không set
gì thì engine giữ nguyên file cục bộ như cũ; không có bước migrate, không đổi hành vi với
setup một máy.

Kiểm chứng đã ăn:

```bash
sagctl doctor
```

Khối `state` báo `backend: http` và service có tới được không. Nếu một máy báo `local`
còn máy khác báo `http` thì chúng **không** dùng chung state, dù cùng publish vào một
source trên SAG.

Service này là kho lưu trữ câm, không giữ policy nào: manifest vẫn quyết định cái gì được
publish, deterministic floor vẫn chạy trên máy của agent. Chiếm được nó thì kẻ tấn công
giả mạo được lịch sử audit và reset được bộ đếm chi phí, chứ không publish được thứ mà
floor đã từ chối. Xem [SPEC amendment A1](docs/SPEC.md#a1-state-location-is-pluggable--local-default--http-fleet-shared).

### Sinh cấu hình cho từng máy

`source_id` chỉ khai một lần — trong manifest, trong Git. Mọi cấu hình phía agent đều
sinh ra từ đó, không chép tay giữa các máy. Chạy trong repo, trên máy đang cài:

```bash
sagctl adapter-emit claude-code --write .
```

Với target khác:

```bash
sagctl adapter-emit hermes --plugin-root /opt/agent-skills/sag-agents-plugin
```

```bash
sagctl adapter-emit codex --plugin-root /opt/agent-skills/sag-agents-plugin
```

URL đọc sinh ra có mang scope — `${SAG_URL}/mcp/?source_id=<id>` — nên agent làm việc ở
project A không vô tình lôi được tri thức của project B. Không tìm thấy manifest thì lệnh
vẫn chạy nhưng in cảnh báo và đánh dấu cấu hình là unscoped: đó phải là một lựa chọn nhìn
thấy được, không phải mặc định lặng lẽ.

File nào thường đã có nội dung khác (`settings.json`, `config.yaml`, `config.toml`) thì
được in ra để bạn tự merge chứ không ghi đè. Chỉ `.mcp.json` — vốn hoàn toàn của plugin —
mới được ghi thẳng.

**Scoping này đáng giá tới đâu — đã đo, không phải phỏng đoán.** Case `S17` trên
`sag.home` (2026-08-01) cho thấy `?source_id=` **có** được server cưỡng chế với việc truy
cập document: agent scope về source B không lấy được document của source A. Nhưng
`list_sources` vẫn trả về mọi source trên instance, nên agent vẫn liệt kê được tên và id
của các project khác — nội dung được tách, metadata thì không. Và trần vẫn nguyên: cả
fleet dùng chung một read token, nên agent nào tự dựng url không scope thì với tới tất cả.
Scoping giới hạn công cụ đưa cho agent, không giới hạn thứ mà credential của nó làm được.

Kết quả đó mô tả `sag.home`. Đo instance của bạn:

```bash
sagctl selftest --url http://<sag-host>:8000 --token <token> --case S17
```

Xem [SPEC amendment A2](docs/SPEC.md#a2-agent-side-config-is-generated-from-the-manifest-read-mcp-is-scoped).

---

## Publish không cần file, không cần repo

Trước đây engine hàn cứng hai giới hạn chưa bao giờ thật sự là policy: provenance chỉ
nhét vừa vào YAML frontmatter nên chỉ markdown publish được; và publish đòi hỏi một commit
Git nên agent nào không làm việc trong một checkout — một profile Hermes, một phiên
research — thì không publish được gì cả. Cả hai đều là chi tiết lưu trữ (frontmatter cần
text; commit cần repo) bị thực thi như thể là luật quyết định cái gì là tri thức. Giờ
không còn đúng nữa (SPEC amendment A3).

**Mọi định dạng SAG nhận đều publish được.** `include` giờ mặc định `**/*`. Provenance của
những gì không nhét được frontmatter (`.pdf`, `.docx`, `.csv`, `.json`, ...) nằm trong
state store thay vì trong file — cùng một nguồn thẩm quyền, cùng chỗ `maintain` và
`doctor` đã nhìn vào.

**Nhưng PDF/DOCX không được upload thô — mà được chưng cất.** Engine không parse định
dạng binary; việc đó vẫn thuộc về agent, và Claude Code (cùng nhiều nơi khác) đã có sẵn
skill đọc tài liệu cho đúng việc này. Đọc tài liệu, viết markdown, publish cái đó:

```bash
sagctl publish docs/contract-analysis.md --assessment '{"verdict":"knowledge", ...}'
```

ghi lại bản gốc vào `derived_from` — xem bên dưới. Bản chưng cất chunk tốt hơn hẳn so với
parse phía server (heading do agent viết, không phải output của `markitdown`), và sàn an
toàn quét được đầy đủ; một file binary sàn không đọc được thì vào hàng chờ người duyệt,
không bị âm thầm chứng nhận "sạch".

**Không cần file nào cả — `sagctl publish-content` / MCP tool `sag_publish_content`.**
Dành cho text agent tự viết: một bản tổng hợp từ phiên chat, một bản chưng cất không đáng
giữ thành file riêng.

```bash
sagctl publish-content research/2026-08-01-pricing-competitors.md \
  --content-file /tmp/synthesis.md \
  --derived-from "docs/vendor-report.pdf@a1b2c3d,https://example.com/pricing" \
  --assessment '{"verdict":"knowledge", ...}'
```

`relpath` (tham số đầu) là key do bạn chọn — được khớp với
`include`/`exclude`/`deny_paths`/`ask_paths` y hệt như path của file thật, và mã hoá vào
key SAG theo đúng cách cũ. Không khái niệm policy mới, không trường manifest mới. Không có
manual-mode bypass ở đây: luôn cần assessment, vì không có file để token của slash command
gắn vào.

**Manifest vẫn phải resolve được**, chỉ là không cần đi ngược từ một file nữa:
`--manifest <path>`, `--manifest-name <name>` (tìm dưới
`~/.sagctl/manifests/<name>.json`), biến môi trường `SAGCTL_MANIFEST`, hoặc một
`.sag-sync.json` ở trên thư mục hiện tại — bản thân thư mục đó không cần là repo Git.

**Cái không đổi:** sàn an toàn vẫn chạy đủ (secret scan, `deny_paths`, cost cap), model
vẫn không được tự khai `secret_free`, và orphan/stale-branch detection của `maintain`
**bỏ qua hẳn** tài liệu publish theo cách này — hỏi "path này còn trong repo không" là vô
nghĩa, và nguy hiểm, với một tài liệu chưa từng là path thật trong repo nào.

---

## Một lần publish diễn ra thế nào

```text
  agent vừa viết xong docs/adr/0007-queue-choice.md
              │
              ▼
  ┌───────────────────────────────────────────┐
  │ 1. TỰ ĐÁNH GIÁ  (model, typed, S5)        │
  │    verdict: knowledge | not-knowledge |   │
  │             unsure                        │
  │    durable / audience / retrieval_fit     │
  │    criteria_ack[] · confidence · lý do    │
  └────────────────┬──────────────────────────┘
                   ▼
  ┌───────────────────────────────────────────┐
  │ 2. SÀN TẤT ĐỊNH  (engine, không LLM)      │
  │    manifest ancestor giải được             │
  │  ∧ include ∧ ¬exclude ∧ ¬deny_paths       │
  │  ∧ trạng thái git thoả `require`          │
  │  ∧ quét secret (regex+entropy, gitleaks)  │
  │  ∧ dedupe theo key ∧ trần chi phí         │
  │    ── bất kỳ mệnh đề đỏ ⇒ từ chối cứng ── │
  └────────────────┬──────────────────────────┘
                   ▼
  ┌───────────────────────────────────────────┐
  │ 3. ROUTING  (verdict trước, conf sau)     │
  │  knowledge ∧ conf≥min ∧ criteria_ack ⇒ AUTO
  │  unsure | conf thấp | ask_paths      ⇒ QUEUE
  │  not-knowledge                       ⇒ BỎ
  │  deny_paths                          ⇒ TỪ CHỐI
  └────────────────┬──────────────────────────┘
                   ▼
  ┌───────────────────────────────────────────┐
  │ 4. UPLOAD                                 │
  │    provenance chỉ chèn vào *bytes* gửi    │
  │    đi — file trên đĩa giữ nguyên          │
  │    thay thế = delete rồi upload           │
  │    assert response.filename == key        │
  │    assessment đầy đủ → audit JSONL        │
  └───────────────────────────────────────────┘
```

Model cung cấp **phán đoán**. Engine cung cấp **sự thật** (`canonical`, `secret_free`,
`key`, `initiator`) — model không bao giờ được tự khẳng định những điều đó về chính nó.

### Trích dẫn bằng path, không phải ID

SAG không có API cập nhật tài liệu (sửa nội dung = xoá + upload lại), nên `document_id` và
`chunk_id` **đổi sau mỗi lần republish**. Trích dẫn bền vững duy nhất là
`source_id + path trong repo (+ heading)`. Các skill cưỡng chế điều này.

---

## MCP tools

### `sag` — đọc (upstream SAG, không sửa)

`list_sources` · `list_documents` · `outline` · `search` · `grep` · `read` · `get_chunk` ·
`get_entity`

Skill [sag-knowledge](skills/sag-knowledge/SKILL.md) dạy phễu truy xuất và ngân sách cho
mỗi lượt tra cứu, cùng với khi nào nên dùng `grep` (định danh chính xác) thay cho `search`
(ngữ nghĩa).

### `sagw` — ghi (plugin này)

| Tool | Tham số | Permission mặc định |
|---|---|---|
| `sag_publish` | `{path, assessment}` | **allow** — assessment luôn bắt buộc |
| `sag_publish_status` | `{path}` | **allow** — chỉ đọc |
| `sag_sync_preview` | `{}` | **allow** — chỉ đọc, dry-run |
| `sag_reprocess` | `{path}` | **allow** |
| `sag_publish_unreviewed` | `{path, reason}` | **ask** — bỏ qua `require`, **không** bỏ qua quét secret hay `deny_paths` |
| `sag_unpublish` | `{path, reason}` | **ask** — đường khắc phục, luôn có sẵn |

**Không có cờ manual-mode trên bề mặt MCP.** `sag_publish` luôn đòi assessment; cách duy
nhất để bỏ qua đánh giá là slash command `/sag-publish`, lệnh này mint một token dùng một
lần, gắn với `sha256(args)`, TTL 5 phút.

---

## Tham chiếu CLI

```bash
# xác thực & sức khoẻ
sagctl login --url <URL> --name <tên>        # write token → ~/.sagctl/credentials.json
sagctl whoami
sagctl health

# đường publish
sagctl publish <path> [--assessment-file f.json] [--wait] [--dry-run]
sagctl publish-status <source_id> <key>
sagctl unpublish <source_id> <key> --reason "..."
sagctl reprocess <source_id> <key>

# hàng loạt
sagctl sync --manifest .sag-sync.json        # mặc định dry-run; --yes để chạy thật

# hàng đợi duyệt
sagctl queue list <source_id>
sagctl queue approve <source_id> <queue_id> [--reviewer TÊN]
sagctl queue reject  <source_id> <queue_id> --reason "..."

# bảo trì
sagctl maintain dedupe        --manifest .sag-sync.json
sagctl maintain orphans       --manifest .sag-sync.json
sagctl maintain stale-branch  --manifest .sag-sync.json
sagctl maintain review-self-gate <source_id> --days 7

# source & document
sagctl source list | get <id> | create "<tên>" | update <id> --fields '{...}' | delete <id> --yes
sagctl document list <source_id>

# chẩn đoán
sagctl doctor --manifest .sag-sync.json --source-id <id>   # file khớp manifest mà chưa từng đánh giá
sagctl scan <path>                                          # quét secret theo yêu cầu
sagctl selftest --url <URL> --token <tok> [--case S1,S4]    # thăm dò một instance SAG thật
sagctl eval --questions q.jsonl --source-id <id> [--save-baseline]
sagctl criteria-add --manifest .sag-sync.json <id> "<nội dung tiêu chí>"
sagctl adapter-emit codex|hermes|claude-code [--out FILE]
sagctl api GET /system/capabilities                         # cửa thoát hiểm; mặc định agent bị deny
```

**Write token không bao giờ được nhận qua tham số dòng lệnh** — làm vậy sẽ rò vào lịch sử
shell và danh sách tiến trình. Nó chỉ được đọc từ `~/.sagctl/`.

---

## Skills

| Skill | Model tự gọi | Mục đích |
|---|---|---|
| [sag-knowledge](skills/sag-knowledge/SKILL.md) | có | Tìm, duyệt, trích dẫn, đọc — phễu truy xuất và kỷ luật trích dẫn. |
| [sag-publish](skills/sag-publish/SKILL.md) | có | Tự đánh giá tài liệu vừa viết và publish nếu là tri thức bền vững đáng chia sẻ. |
| [sag-maintain](skills/sag-maintain/SKILL.md) | có | Kiểm tra sức khoẻ: tài liệu failed, orphan, trùng lặp, review self-gate. Đề xuất, không tự phá. |
| [sag-sync-project](skills/sag-sync-project/SKILL.md) | **không** | Sync hàng loạt cả repo. Chỉ người kích hoạt. |
| [sag-source-admin](skills/sag-source-admin/SKILL.md) | **không** | Tạo/sửa/xoá source. Có tính phá huỷ, chỉ người kích hoạt. |
| [sag-status](skills/sag-status/SKILL.md) | có | Chẩn đoán chỉ đọc: đang ở scope nào, state có dùng chung không, url đọc có scope không, file nào chưa assess. |
| [sag-setup](skills/sag-setup/SKILL.md) | **không** | Setup lần đầu trên máy này — dựng scope mới hoặc join scope sẵn có. Chỉ người kích hoạt. |

Ba skill có đặc quyền đặt `disable-model-invocation: true` — một yêu cầu kiểu "dọn dẹp
knowledge base" **không** đồng nghĩa với cho phép chạy chúng.

### Lớp nhắc nhận thức

- **Hook `Stop` / `SessionEnd` (chính)** — so danh sách file thay đổi trong phiên với
  include-glob của manifest, đối chiếu audit log, liệt kê những file chưa từng được đánh
  giá. Chỉ thông báo, có chống lặp.
- **`PostToolUse(Write|Edit)` (phụ)** — nhắc nhẹ, khử trùng lặp mỗi file một lần trong
  phiên.
- **`UserPromptSubmit`** — mint token thủ công dùng một lần, và *chỉ* khi prompt khớp đúng
  dạng `/sag-publish <args>`.
- **Hermes / Codex** — chỉ mang tính khuyến cáo (system prompt của profile / `AGENTS.md`)
  cộng một `sagctl doctor` chạy theo lịch. Nói thẳng: cưỡng chế bằng máy chỉ có trên
  Claude Code.

---

## Mô hình bảo mật

Đây là **rào chắn chống tai nạn và prompt injection nông, không phải một biên giới bảo
mật.** Agent và engine chạy cùng một OS user; kẻ tấn công đã có quyền thực thi mã dưới
user đó có thể vượt qua mọi thứ ở đây. Phương án làm cứng (OS user riêng, engine chạy như
service) là một hướng tương lai đã ghi nhận, không phải thứ đang ship.

Những gì **thực sự** được cưỡng chế:

| Kiểm soát | Cách cưỡng chế |
|---|---|
| Cô lập write token | Nằm ở `~/.sagctl/credentials.json` (`0600`), không vào env agent, không nhận qua CLI. Read token tách riêng, chỉ đọc. |
| Quét secret | Regex + entropy trên mọi upload, cộng `gitleaks` nếu có trên PATH. **`sag_publish_unreviewed` không bỏ qua bước này.** |
| `deny_paths` | Chặn cả manual mode — vì đó là luật do chính con người tự đặt cho mình. |
| Token thủ công | Gắn với `sha256(args)`, dùng một lần (bị unlink khi tiêu thụ), TTL 5 phút. Token mint cho path A không publish được path B. |
| `initiator` | Do engine suy ra từ sự tồn tại của token. Model không thể tự nhận `user-manual`. |
| Vệ sinh repo | Engine abort nếu tìm thấy file trạng thái runtime bên trong working tree. |
| Audit | Mọi assessment và quyết định route được ghi nối vào JSONL local, tra được bằng `sagctl doctor`. |

**Giới hạn đã biết, nói thẳng:**

- SAG (theo kết quả kiểm chứng) **không cô lập giữa các identity** và **không có
  attribution phía server** — cả fleet agent dùng chung một cặp read/write token theo
  thiết kế, vì thêm identity thứ hai cũng chẳng mua được gì. Attribution chỉ tồn tại trong
  audit log local.
- JWT của SAG có vòng đời cố định **7 ngày, không có endpoint revoke/refresh**. Token bị
  lộ **không thể thu hồi**, chỉ có thể chờ hết hạn — hãy xoay vòng theo chu kỳ ngắn hơn 7
  ngày trong môi trường nhạy cảm.

Cả hai phát hiện đều là thực nghiệm (selftest case S11/S12/S13 trên một instance thật),
không phải giả định. Chi tiết đầy đủ trong [docs/SPEC.md](docs/SPEC.md).

Để báo cáo lỗ hổng, xem [SECURITY.md](SECURITY.md).

---

## Phát triển

```bash
# unit test — offline, không cần instance SAG
python -m unittest discover -s tests -v

# tích hợp — thăm dò một instance SAG thật, 16 case
sagctl selftest --url <SAG_URL> --token <token>
sagctl selftest --url <SAG_URL> --token <token> --case S1    # một case (nhiều case thì ngăn bằng dấu phẩy)
```

87 unit test bao phủ toàn bộ hàm thuần: key encoding, validate manifest, routing, quét
secret, chèn provenance, khớp glob `**`, vòng đời token thủ công, phân trang REST client,
khả năng chịu lỗi mạng, và phát hiện rò `~/.sagctl/` vào repo. Chúng chạy offline trong CI
trên Linux và Windows, qua Python 3.11–3.13.

`selftest` khác về bản chất: nó kiểm chứng rằng **bản thân SAG** vẫn hành xử đúng như spec
giả định. Hãy chạy nó trước khi cấp phát một source mới hoặc sau khi nâng cấp SAG — đặc
biệt case **S1** (`key_format`) và **S4** (tính đồng bộ của delete), hai case quyết định
hai mặc định đã khoá.

> ⚠️ `selftest` upload tài liệu thật và tiêu thụ quota LLM thật trên tài khoản nhà cung
> cấp của host SAG. Riêng case S6 upload 120 tài liệu — hãy giảm `n` nếu bạn chạy lại
> nhiều lần trên một tài khoản bị giới hạn chặt.

### Nguyên tắc thiết kế

1. **Không bao giờ sửa SAG.** Chỉ REST API và MCP có sẵn.
2. **Chỉ stdlib.** Python 3.11+, không phụ thuộc pip, để engine vendor gọn vào bất kỳ
   container hay agent host nào.
3. **Model phán đoán; engine quyết định.** Verdict là đầu vào tham khảo cho một router tất
   định — không bao giờ thay thế nó.
4. **Kiểm chứng, đừng giả định.** Mọi khẳng định về hành vi của SAG đều truy được về một
   selftest case có số hiệu và kết quả đã ghi nhận.
5. **Đề xuất hơn là phá huỷ.** Bảo trì thì báo cáo; con người hành động. Ngoại lệ duy nhất
   là xoá bản trùng khi chứng minh được quan hệ ancestry trong Git.

---

## Cấu trúc repo

```text
.claude-plugin/      manifest plugin + marketplace
scripts/sagctl/      engine — logic ghi, sàn an toàn, routing, audit
scripts/sagw_server.py   MCP write server mỏng bọc engine (6 tool)
scripts/install-shim.py  đặt `sagctl` lên PATH, tạo ~/.sagctl/
skills/              7 skill: setup, status, và cách dùng knowledge base đúng
commands/            slash command /sag-publish
hooks/               nhắc nhận thức + mint token thủ công
adapters/            cấu hình cài đặt riêng từng agent tool (claude-code, hermes, codex)
examples/            manifest mẫu, doc template, eval set mẫu
tests/               87 unit test cho hàm thuần — không cần server
docs/                SPEC.md (chuẩn), nhật ký thiết kế, biên bản review
```

---

## Tài liệu

| Tài liệu | Nội dung |
|---|---|
| [docs/SPEC.md](docs/SPEC.md) | **Chuẩn.** Hợp đồng cài đặt đã khoá (S0–S12), kết quả selftest trên instance thật, và kế hoạch theo phase. |
| [docs/DESIGN.md](docs/DESIGN.md) | Nhật ký thiết kế — lập luận dẫn tới spec. |
| [docs/AGENT-BEHAVIOR.md](docs/AGENT-BEHAVIOR.md) | Hành vi agent mong muốn, chi tiết. |
| [docs/REVIEW-OPUS.md](docs/REVIEW-OPUS.md) | Biên bản review thiết kế đối kháng đã làm cứng spec. |
| [examples/README.md](examples/README.md) | Cách dùng manifest mẫu, doc template và eval set. |

---

## Đóng góp

Rất hoan nghênh đóng góp. Hãy đọc [CONTRIBUTING.md](CONTRIBUTING.md) trước — đặc biệt hai
luật không thương lượng:

1. **Không thay đổi nào được phép đòi hỏi sửa source code của SAG.**
2. **Không thay đổi nào được phép thêm phụ thuộc runtime ngoài thư viện chuẩn Python.**

Bất cứ điều gì mâu thuẫn với [docs/SPEC.md](docs/SPEC.md) đều cần đổi spec trước, thống
nhất trong một issue — không phải một quyết định ngẫu hứng của kỹ sư trong PR.

Khi tham gia, bạn đồng ý với [Quy tắc ứng xử](CODE_OF_CONDUCT.md).

## Giấy phép

[MIT](LICENSE) © 2026 vuongdam2k01

Bản thân SAG là một project riêng với giấy phép riêng — xem
[Zleap-AI/SAG](https://github.com/Zleap-AI/SAG).
