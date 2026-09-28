"""Make Colab NVIDIA libraries available in SSH and VS Code terminals."""
import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess


def prepare_gpu(expected, driver_dir='/usr/lib64-nvidia', home=None, loader_dir='/etc/ld.so.conf.d'):
    driver = Path(driver_dir)
    if driver.is_dir():
        previous = os.environ.get('LD_LIBRARY_PATH', '')
        if str(driver) not in previous.split(':'):
            os.environ['LD_LIBRARY_PATH'] = str(driver) + (':' + previous if previous else '')
        line = f'export LD_LIBRARY_PATH={shlex.quote(str(driver))}${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}'
        for name in ['.bashrc', '.profile']:
            path = (Path(home) if home else Path.home()) / name
            text = path.read_text() if path.exists() else ''
            if line not in text:
                path.write_text(text.rstrip() + '\n' + line + '\n')
        # Covers VS Code Server, Python kernels and non-interactive processes too.
        loader = shutil.which('ldconfig')
        if loader and os.geteuid() == 0:
            config = Path(loader_dir) / 'colab-nvidia.conf'
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text(str(driver) + '\n')
            subprocess.run([loader], check=True)
    result = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'],
                            text=True, capture_output=True)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f'GPU check failed (nvidia-smi exit {result.returncode}): {detail}')
    names = result.stdout.strip()
    if not names or (expected != 'G4' and expected not in names):
        raise RuntimeError(f'Expected {expected}, detected: {names or "no NVIDIA GPU"}')
    print('GPU verified:', names, flush=True)


def remote_code(expected):
    # Only standard-library imports and prepare_gpu are needed on the remote VM.
    source = Path(__file__).read_text()
    source = source[:source.index('\ndef remote_code(')]
    return source + f'\nprepare_gpu({expected!r})\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', required=True)
    parser.add_argument('--gpu', default='T4')
    args = parser.parse_args()
    from setup_ssh import configure
    cli = shutil.which('colab')
    if not cli:
        parser.error('Run with uv run setup_gpu.py')
    config, alias = configure(args.session, cli, gpu=args.gpu)
    subprocess.run(['ssh', '-F', str(config), '-o', 'BatchMode=yes', alias,
                    'python3 -c ' + shlex.quote(remote_code(args.gpu))], check=True)


if __name__ == '__main__':
    main()
