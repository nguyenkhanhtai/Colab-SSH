"""CLI entrypoint for running the web dashboard server."""
import argparse
import os

from colab_session.server.app import serve


def main(argv=None) -> None:
    default_host = os.environ.get('COLAB_SSH_HOST', '127.0.0.1')
    default_port = int(os.environ.get('COLAB_SSH_PORT', '6767'))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default=default_host)
    parser.add_argument('--port', type=int, default=default_port)
    args = parser.parse_args(argv)
    serve(args.host, args.port)


if __name__ == '__main__':
    main()

