# nanoGPT smoke training on Colab

Run these commands from the root of this repository:

```bash
.venv/bin/colab-ssh job run-config examples/nanogpt/colab-job.json
```

The dispatcher reuses a T4 runtime or creates one. The script clones upstream
https://github.com/karpathy/nanoGPT, records its commit, prepares Shakespeare
characters, and trains a 2-layer, 128-dimensional GPT for 100 iterations on CUDA.
W&B and torch.compile are disabled. Each invocation uses a new workspace.
The final checkpoint and upstream revision are copied to
`/content/nanogpt-artifacts` (replaced by the next run).

Use the session and job ID printed by submission:

```bash
.venv/bin/colab-ssh job logs JOB_ID --session SESSION --tail 50
.venv/bin/colab-ssh job status JOB_ID --session SESSION
.venv/bin/colab-ssh job pull JOB_ID --session SESSION
.venv/bin/colab-ssh --stop SESSION
```

Pull artifacts after successful completion and before stopping the runtime.
They are saved under `outputs/nanogpt/nanogpt-artifacts/` locally.
This is a pipeline check; 100 iterations are insufficient for a useful language model.
