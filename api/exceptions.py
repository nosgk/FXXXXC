# -*- coding: utf-8 -*-
"""Domain exceptions.

``MaxRollBackExceeded`` / ``MaxRetryExceeded`` are kept for backward
compatibility with external scripts; current code paths do not raise them.
"""


class LoginError(Exception):
    pass


class InputFormatError(Exception):
    pass


class MaxRollBackExceeded(Exception):
    pass


class MaxRetryExceeded(Exception):
    pass


class FontDecodeError(Exception):
    pass
