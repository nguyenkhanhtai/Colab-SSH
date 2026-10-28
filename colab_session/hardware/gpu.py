"""Make Colab NVIDIA libraries available in SSH and VS Code terminals."""
import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
from typing import Optional


class GPULibraryConfigurator:
    """Configures driver paths and dynamic library loader configs for Colab GPUs."""

    def __init__(self, driver_dir: str | Path = '/usr/lib64-nvidia', loader_dir: str | Path = '/etc/ld.so.conf.d'):
        self.driver_dir = Path(driver_dir)
        self.loader_dir = Path(loader_dir)

    def configure(self, home: Optional[str | Path] = None) -> None:
        if not self.driver_dir.is_dir():
            return
        previous = os.environ.get('LD_LIBRARY_PATH', '')
        if str(self.driver_dir) not in previous.split(':'):
            os.environ['LD_LIBRARY_PATH'] = str(self.driver_dir) + (':' + previous if previous else '')
        line = f'export LD_LIBRARY_PATH={shlex.quote(str(self.driver_dir))}${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}'
        for name in ['.bashrc', '.profile']:
            path = (Path(home) if home else Path.home()) / name
            text = path.read_text() if path.exists() else ''
            if line not in text:
                path.write_text(text.rstrip() + '\n' + line + '\n')
        loader = shutil.which('ldconfig')
        if loader and os.geteuid() == 0:
            config = self.loader_dir / 'colab-nvidia.conf'
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text(str(self.driver_dir) + '\n')
            subprocess.run([loader], check=True)


class GPUHardwareVerifier:
    """Queries and validates NVIDIA GPU presence via nvidia-smi."""

    def verify(self, expected: str) -> str:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'],
            text=True,
            capture_output=True,
        )
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(f'GPU check failed (nvidia-smi exit {result.returncode}): {detail}')
        names = result.stdout.strip()
        if not names or (expected != 'G4' and expected not in names):
            raise RuntimeError(f'Expected {expected}, detected: {names or "no NVIDIA GPU"}')
        print('GPU verified:', names, flush=True)
        return names


class GPUConfigurator:
    """Facade orchestrating library setup and hardware verification (Single Responsibility)."""

    def __init__(self, driver_dir: str | Path = '/usr/lib64-nvidia', loader_dir: str | Path = '/etc/ld.so.conf.d'):
        self.lib_configurator = GPULibraryConfigurator(driver_dir, loader_dir)
        self.verifier = GPUHardwareVerifier()

    def prepare(self, expected: str, home: Optional[str | Path] = None) -> str:
        self.lib_configurator.configure(home)
        return self.verifier.verify(expected)


def prepare_gpu(expected, driver_dir='/usr/lib64-nvidia', home=None, loader_dir='/etc/ld.so.conf.d'):
    """Prepare GPU library path and verify expected accelerator."""
    configurator = GPUConfigurator(driver_dir=driver_dir, loader_dir=loader_dir)
    return configurator.prepare(expected, home=home)


def remote_code(expected):
    """Generate remote python code to verify and configure GPU."""
    source = Path(__file__).read_text()
    source = source[:source.index('\ndef remote_code(')]
    return source + f'\nprepare_gpu({expected!r})\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', required=True)
    parser.add_argument('--gpu', default='T4')
    args = parser.parse_args()
    from colab_session.ssh.config import configure
    cli = shutil.which('colab')
    if not cli:
        parser.error('Run with uv run setup_gpu.py')
    config, alias = configure(args.session, cli, gpu=args.gpu)
    subprocess.run(['ssh', '-F', str(config), '-o', 'BatchMode=yes', alias,
                    'python3 -c ' + shlex.quote(remote_code(args.gpu))], check=True)


if __name__ == '__main__':
    main()

