"""Keep PNG compression and disk writes out of the timing loop."""
from pathlib import Path
import queue
import threading

import cv2


class SnapshotWriter:
    def __init__(self,directory):
        self.directory=Path(directory)
        self.queue=queue.Queue(maxsize=32)
        self.thread=threading.Thread(target=self.write,daemon=True)
        self.thread.start()

    def save(self,name,frame):
        try:self.queue.put_nowait((name,frame.copy()))
        except queue.Full:pass

    def write(self):
        while True:
            item=self.queue.get()
            if item is None:return
            name,frame=item
            cv2.imwrite(str(self.directory/name),frame)

    def close(self):
        self.queue.put(None)
        self.thread.join()
