#!/usr/bin/env bash
set -euo pipefail

# Each invocation gets its own workspace and output checkpoint.
RUN_DIR=$(mktemp -d /content/nanogpt-smoke-XXXXXX)
echo "Workspace: $RUN_DIR"
git clone --depth 1 https://github.com/karpathy/nanoGPT.git "$RUN_DIR/repo"
cd "$RUN_DIR/repo"
git rev-parse HEAD | tee revision.txt
python3 -m pip install numpy requests torch
python3 -c 'import torch; assert torch.cuda.is_available(), "CUDA unavailable"; print(torch.cuda.get_device_name(0))'
python3 data/shakespeare_char/prepare.py
python3 -u train.py config/train_shakespeare_char.py \
  --device=cuda --dtype=float16 --compile=False \
  --n_layer=2 --n_head=2 --n_embd=128 \
  --batch_size=16 --block_size=128 --gradient_accumulation_steps=1 \
  --max_iters=100 --lr_decay_iters=100 --warmup_iters=10 \
  --eval_interval=50 --eval_iters=10 --log_interval=10 \
  --always_save_checkpoint=True --wandb_log=False --out_dir=out-smoke
test -s out-smoke/ckpt.pt
# Expose a predictable artifact location for `job pull`.
mkdir -p /content/nanogpt-artifacts
cp out-smoke/ckpt.pt revision.txt /content/nanogpt-artifacts/
echo "Training complete; checkpoint: /content/nanogpt-artifacts/ckpt.pt"
