# sag-agents-plugin

*[English](README.md) | [Tiếng Việt](README.vi.md)*

Plugin cài thẳng vào Claude Code, Hermes Agent, Codex để dùng SAG (Zleap-AI/SAG) làm
knowledge base chung — bù các thao tác ghi mà MCP read-only của SAG không có, mà **không
sửa bất kỳ dòng nào trong source code SAG**. Mọi giao tiếp với SAG chỉ qua REST API công
khai và MCP có sẵn của nó.

**Nguồn chân lý cho hành vi và hợp đồng kỹ thuật: [docs/SPEC.md](docs/SPEC.md).**
`docs/DESIGN.md` và `docs/AGENT-BEHAVIOR.md` là nhật ký thiết kế dẫn tới SPEC.md — hữu ích
để hiểu *tại sao*, nhưng khi có mâu thuẫn, SPEC.md thắng.

## Cài đặt

### Claude Code

```bash
claude plugin marketplace add <đường-dẫn-hoặc-url-repo-này>
claude plugin install sag-agents
```

Cần đặt biến môi trường trước khi dùng:

```bash
export SAG_URL="http://<sag-host>:8000"
export SAG_READ_TOKEN="<token chỉ đọc>"
```

Write token **không** đặt trong môi trường agent — xem [Cài đặt sagctl](#cài-đặt-sagctl).

### Hermes Agent

Trỏ `skills.external_dirs` vào thư mục `skills/` của repo này, xem
[adapters/hermes/config.example.yaml](adapters/hermes/config.example.yaml).

### Codex

Chạy `sagctl adapter emit codex` để sinh khối cấu hình cho `config.toml` và `AGENTS.md`
(có version marker để phát hiện lệch phiên bản), xem
[adapters/codex/](adapters/codex/).

## Cài đặt sagctl (bắt buộc cho cả 3 tool)

```bash
python scripts/install-shim.py    # đặt `sagctl` lên PATH, tạo ~/.sagctl/
sagctl login                       # sinh write token, lưu tại ~/.sagctl/
```

`sagctl` là engine duy nhất (Python 3.11+, stdlib-only) đứng sau cả CLI, MCP server ghi
`sagw`, và mọi hook. Chi tiết kiến trúc: [docs/SPEC.md §S0](docs/SPEC.md).

## Cấu trúc repo

```text
scripts/sagctl/     engine — mọi logic ghi, sàn an toàn, routing, audit
scripts/sagw_server.py   MCP write server mỏng bọc engine (6 tools)
skills/              5 skill dạy agent dùng knowledge base đúng cách
commands/             slash command thủ công (/sag-publish)
hooks/                nhắc nhận thức + mint token thủ công
adapters/             cấu hình cài đặt riêng cho từng agent tool
examples/             manifest mẫu, doc-templates, eval set mẫu
tests/                unit test cho các hàm thuần (không cần server thật)
docs/                 SPEC.md (chuẩn), nhật ký thiết kế, biên bản review
```

## Chạy test

```bash
python -m unittest discover -s tests -v
```

Unit test bao phủ toàn bộ hàm thuần (key encoding, manifest validation, routing, secret
scan, provenance, glob `**`, token thủ công, phát hiện leak `~/.sagctl/` vào repo) — không
cần server SAG thật, chạy được offline trong CI.

Để kiểm chứng trên một instance SAG thật:

```bash
sagctl selftest --url <SAG_URL> --token <token>
```

Kết quả và các mặc định đặc thù theo từng instance được ghi lại trong
[docs/SPEC.md](docs/SPEC.md).
