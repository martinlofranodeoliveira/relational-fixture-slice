"""Fixed, synthetic lifecycle cases; never accepts an executable or PID."""

import os
import signal
import sys
import time


def main():
    if len(sys.argv) != 2:
        return 2
    mode = sys.argv[1]
    if mode == 'zero':
        for _ in range(32):
            block = b'x' * 4096
            while block:
                block = block[os.write(1, block):]
        return 0
    if mode == 'failure':
        return 7
    if mode == 'timeout':
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        os.write(1, b'ready\n')
        time.sleep(60)
        return 0
    if mode == 'orphan':
        child = os.fork()
        if child == 0:
            time.sleep(0.6)
            os._exit(0)
        return 0
    return 2


if __name__ == '__main__':
    sys.exit(main())
