"""
Bounded ThreadPoolExecutor

A wrapper around ThreadPoolExecutor that limits the number of pending tasks
in the internal queue to prevent unbounded memory growth.
"""

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock, Semaphore
from typing import Any, Callable


class ExecutorQueueFull(RuntimeError):
    """Raised when the bounded executor queue is full (non-blocking submit)."""


class BoundedThreadPoolExecutor:
    """
    ThreadPoolExecutor with a bounded internal queue.

    Unlike the standard ThreadPoolExecutor which has an unbounded queue,
    this implementation limits the number of pending tasks. When the queue
    is full, submit() will block until a slot becomes available.

    Args:
        max_workers: Maximum number of worker threads
        max_queue_size: Maximum number of tasks that can be queued
        thread_name_prefix: Prefix for worker thread names

    Example:
        executor = BoundedThreadPoolExecutor(max_workers=4, max_queue_size=100)

        # This will block if 100 tasks are already queued
        future = executor.submit(my_function, arg1, arg2)
    """

    def __init__(self, max_workers: int, max_queue_size: int, thread_name_prefix: str = ""):
        """
        Initialize the bounded executor.

        Args:
            max_workers: Number of worker threads
            max_queue_size: Maximum pending tasks allowed
            thread_name_prefix: Prefix for thread names (optional)
        """
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=thread_name_prefix)

        # Semaphore to limit queue size
        # Each submit() acquires, each completion releases
        self.semaphore = Semaphore(max_queue_size)
        self._available_slots = max_queue_size
        self._slots_lock = Lock()

        self.max_workers = max_workers
        self.max_queue_size = max_queue_size

    def submit(self, fn: Callable, *args, **kwargs) -> Future:
        """
        Submit a task to the executor.

        Blocks if max_queue_size tasks are already pending.

        Args:
            fn: Function to execute
            *args: Positional arguments for fn
            **kwargs: Keyword arguments for fn

        Returns:
            Future object representing the pending task
        """
        # Acquire semaphore (non-blocking). If the queue is full, reject instead
        # of blocking the caller thread (critical for JobThread liveness).
        if not self.semaphore.acquire(blocking=False):
            raise ExecutorQueueFull("Bounded executor queue is full")
        with self._slots_lock:
            self._available_slots -= 1

        # Submit to underlying executor
        future = self.executor.submit(self._wrapper, fn, *args, **kwargs)

        return future

    def _wrapper(self, fn: Callable, *args, **kwargs) -> Any:
        """
        Wrapper that releases semaphore when task completes.

        This ensures the semaphore is released whether the task
        succeeds or fails.
        """
        try:
            return fn(*args, **kwargs)
        finally:
            with self._slots_lock:
                self._available_slots += 1
            self.semaphore.release()

    def shutdown(self, wait: bool = True, cancel_futures: bool = False):
        """
        Shutdown the executor.

        Args:
            wait: If True, wait for all pending tasks to complete
            cancel_futures: If True, cancel pending tasks (Python 3.9+)
        """
        try:
            # Python 3.9+ supports cancel_futures
            self.executor.shutdown(wait=wait, cancel_futures=cancel_futures)
        except TypeError:
            # Python 3.7-3.8 doesn't support cancel_futures
            self.executor.shutdown(wait=wait)

    def get_available_slots(self) -> int:
        """Get number of available task slots (semaphore count)."""
        with self._slots_lock:
            return self._available_slots

    def get_queue_size(self) -> int:
        """
        Get approximate number of pending tasks.

        Returns:
            Number of tasks waiting to be processed
        """
        try:
            return self.executor._work_queue.qsize()
        except AttributeError:
            # Fallback if internal structure changes
            return 0

    def get_stats(self) -> dict:
        """
        Get executor statistics.

        Returns:
            Dictionary with executor stats
        """
        return {
            "max_workers": self.max_workers,
            "max_queue_size": self.max_queue_size,
            "pending_tasks": self.get_queue_size(),
            "available_slots": self.get_available_slots(),
        }

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.shutdown(wait=True)
        return False
