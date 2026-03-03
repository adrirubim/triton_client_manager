from __future__ import annotations

from typing import TYPE_CHECKING, Generator, Iterator
import tritonclient.grpc as grpcclient 
import tritonclient.http as httpclient

if TYPE_CHECKING:
    from classes.triton.info.data import TritonServer

class TritonInference:

    def __init__(self, config: dict):
        pass

    def handle(self, server: TritonServer) -> Generator:
        # TODO Parse inputs
        pass


    def http(self):
        pass

    def grpc(self):
        pass

    
    def parse(self):
        pass