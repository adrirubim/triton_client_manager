import time


def time_it(fn):
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        out = fn(*args, **kwargs)
        return out, time.perf_counter() - start

    return wrapper
