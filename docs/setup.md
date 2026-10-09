# Setup

Two separate things: **clone-to-green** (tests and lint, no model needed) and
**running the agent** (needs Ollama and a GPU). CI only ever does the first.

---

## 1. Clone to green — no model, no network

```bash
curl -fsSL https://astral.sh/uv/install.sh | sh   # installs to ~/.local/bin
uv sync --frozen
uv run pytest && uv run ruff check . && uv run mypy
```

Measured cold (fresh clone, empty `uv` cache): **18 s**. The budget is 60 s.

No GPU, no model, and no network are required. Agent-loop tests replay
recorded model responses from committed fixtures.

---

## 2. Ollama — installed without sudo

`sudo` requires a password on this machine, so the official install script
(which writes to `/usr/local` and installs a system service) is not usable.
The release tarball works fine unpacked into `$HOME`:

```bash
curl -fL https://github.com/ollama/ollama/releases/download/v0.40.1/ollama-linux-amd64.tar.zst \
  -o /tmp/ollama.tar.zst
tar --zstd -xf /tmp/ollama.tar.zst -C "$HOME/.local"
export PATH="$HOME/.local/bin:$PATH"
```

Note the asset is `.tar.zst`, not the `.tgz` that older docs reference — that
URL 404s. `zstd` and `tar --zstd` are both already present on Ubuntu 24.04.

Binary lands at `~/.local/bin/ollama` (28 MB); bundled CUDA libraries at
`~/.local/lib/ollama` (2.1 GB).

### Keep it running — user service, still no sudo

`~/.config/systemd/user/ollama.service`:

```ini
[Unit]
Description=Ollama (user-local, no sudo)
After=network-online.target

[Service]
ExecStart=%h/.local/bin/ollama serve
Restart=always
RestartSec=3
Environment="HOME=%h"

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now ollama
curl -s http://localhost:11434/api/version
```

Starts on login and restarts on crash. It does **not** survive logout —
`Linger=no`, and enabling linger needs root
(`sudo loginctl enable-linger $USER`). For a dev box, starting on login is
enough.

### Model

```bash
ollama pull qwen3:8b   # 5.2 GB
```

---

## 3. Measured on this machine

RTX 4070 Laptop GPU, 8188 MiB total, 7.4 GiB reported available to Ollama.

| Measurement | Value |
|---|---|
| Throughput, warm | **44.9 tok/s** (3 runs: 44.4, 44.9, 44.9) |
| Layers offloaded | **37/37, 100% GPU** |
| VRAM at 4k context | 5.6 GB (4644 MiB model + 576 MiB KV) |
| VRAM at 8k context | **6.2 GB** (4644 MiB model + 1152 MiB KV) |
| Determinism, `temperature=0 seed=42` | identical output across 3 runs |

44.9 tok/s sits in the middle of the 35–50 tok/s that M0 scope §7.3 assumed,
so the 20–30 minute estimate for a 60-task run stands.

8k context fits with ~1.2 GiB spare, which is what M0 scope §7 predicted.

The determinism result is encouraging but **not** the day-5 reproducibility
gate (M0 scope §6). That gate checks whether two full dev-subset runs produce
identical *metrics*, which involves tool calls, step accounting, and a much
longer context. One greedy generation matching itself is a precondition, not
the test.

### Qwen3 reasons by default, and it dominates runtime

Measured: answering "What is 17*23?" cost **847 completion tokens**. Almost all
of it is reasoning the answer does not need.

What works and what does not, tested against Ollama's OpenAI-compatible
endpoint:

| Attempt | completion_tokens |
|---|---|
| default | 847 |
| `think: false` | 837 — no effect |
| `chat_template_kwargs: {enable_thinking: false}` | 837 — no effect |
| `/no_think` in the prompt | 749 — barely helps |
| **`reasoning_effort: "none"`** | **4** |

Only `reasoning_effort` works. It is set from
`DEP_TRIAGE_LLM_REASONING_EFFORT`, default `none`.

The effect on the agent is not marginal. A two-tool question
("urllib3==1.26.4 is vulnerable, what is the lowest safe version?") went from
**timing out at 120 s** to **4 s**.

Revised per-task timing: **1.4–5 s**, against the 25 s/task that M0 scope §4.6
assumed. A full 60-task run is minutes, not 20–30 minutes. The M0 estimate
stays in the document as written, with this correction noted — the plan was
costed before the reasoning overhead was known, and the fix made it cheaper,
not more expensive.

### A driver mismatch that looks worse than it is

`nvidia-smi` currently fails:

```
Failed to initialize NVML: Driver/library version mismatch
NVML library version: 595.99
```

**Resolved by a reboot on 2026-10-09**; `nvidia-smi` now reports normally. Kept
here because the symptom is alarming and the cause is not.

Cause: the kernel module loaded at boot was 595.91.07, while the installed
userspace and DKMS packages were 595.99.02. The upgrade completed and the new
modules are built for the running kernel; they just are not loaded yet. Ubuntu
set no `reboot-required` flag, which is why nothing announced it.

**CUDA is unaffected.** Ollama offloads all 37 layers and reports 100% GPU, and
throughput is normal. Only NVML — which is what `nvidia-smi` talks to — is
broken. A reboot fixes `nvidia-smi`; nothing in this project is blocked
meanwhile.

---

## 4. Docker — needs root

Required for M5 only. Not needed for anything before that.

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2
sudo usermod -aG docker $USER     # then log out and back in
docker run --rm hello-world       # verify
```
