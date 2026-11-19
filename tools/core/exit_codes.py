from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0
    CHECK_FAILED = 1
    USAGE = 2
    SAFETY = 3
    IO = 4
