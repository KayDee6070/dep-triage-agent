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

**Current evaluation condition, verified 2026-10-15:** M3 ran at **4,096
context tokens**, not 8,192. The user service above has no context override;
neither the model parameters nor the OpenAI-compatible client supplies one.
The historical measurements below compare 4k and 8k, but do not establish
a persistent 8k service configuration. M4 matched 782 journal prompts to the
saved model usage and found no observed truncation. See the
[runtime diagnosis](milestones/M4-report.md#runtime-context-4k-was-real-overflow-was-not-observed).
Do not increase context to improve an eval score or silently describe the old
results as 8k. Verify the actual allocation before future final measurement.

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

The three matching hardware-test outputs were **not** the day-5 reproducibility
gate (M0 scope §6). M3 subsequently ran that gate: agent and `always_lookup`
passed, `no_agent` failed. Three additional complete repeats and variance are
preserved in the [M3 report](milestones/M3-report.md). Temperature 0 and seed
42 did not make all development metrics deterministic.

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

## 4. Docker — installed; M5 complete

Docker Engine 29.1.3 and Compose 2.40.3 were installed on 2026-10-15.
Buildx v0.38.0 is installed user-local at `~/.docker/cli-plugins/docker-buildx`;
its release asset SHA256 was checked before installation. The clean-checkout
image build and offline/live checks are in the [M5 report](milestones/M5-report.md).
Use [Docker instructions](docker.md) for the current build and run commands.

The current session may need `sg docker -c 'docker ...'` to apply Kuntal's
already-granted Docker group. No sudo is needed for normal builds or runs.

For a new machine only, installation of the daemon requires the owner to run
the following root commands; an assistant session must not attempt sudo:

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2
sudo usermod -aG docker $USER     # then log out and back in
docker run --rm hello-world       # verify
```
