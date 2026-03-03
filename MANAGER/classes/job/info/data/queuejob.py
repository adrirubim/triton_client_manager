from queue import Queue
import time


class QueueJob(Queue):
    """
    Queue with timestamp tracking for cleanup purposes.
    
    Tracks the last time an item was added to the queue,
    allowing for idle-based cleanup of empty queues.
    """
    
    def __init__(self, maxsize=0):
        super().__init__(maxsize)
        self.last_entry = time.time()  # Initialize with creation time
    
    def put(self, item, block=True, timeout=None):
        """Override put to update last_entry timestamp"""
        super().put(item, block, timeout)
        self.last_entry = time.time()
    
    def put_nowait(self, item):
        """Override put_nowait to update last_entry timestamp"""
        super().put_nowait(item)
        self.last_entry = time.time()
