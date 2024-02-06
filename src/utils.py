import re
from contextlib import contextmanager
from multiprocessing import Condition, Lock
from typing import Optional


class WPriorityRWLock:
    def __init__(self):
        self._lock = Condition(Lock())
        self._readers = 0
        self._writers_waiting = 0
        self._writing = False

    def acquire_read(self):
        with self._lock:
            while self._writing or self._writers_waiting > 0:
                self._lock.wait()
            self._readers += 1

    def release_read(self):
        with self._lock:
            self._readers -= 1
            if self._readers == 0:
                self._lock.notify_all()

    def acquire_write(self):
        with self._lock:
            self._writers_waiting += 1
            while self._readers > 0 or self._writing:
                self._lock.wait()
            self._writers_waiting -= 1
            self._writing = True

    def release_write(self):
        with self._lock:
            self._writing = False
            self._lock.notify_all()

    @contextmanager
    def read(self):
        self.acquire_read()
        try:
            yield
        finally:
            self.release_read()

    @contextmanager
    def write(self):
        self.acquire_write()
        try:
            yield
        finally:
            self.release_write()


def get_shm_size() -> Optional[int]:
    with open("/proc/mounts") as f:
        for line in f:
            m = re.search("/dev/shm .+?,size=([^,]+)", line)
            if m:
                try:
                    size = int(m.group(1)[:-1])
                    e = 0
                    match m.group(1)[-1]:
                        case "k":
                            e = 1
                        case "m":
                            e = 2
                        case "g":
                            e = 3
                        case "t":
                            e = 4

                    return size * 1024**e
                except ValueError:
                    pass
