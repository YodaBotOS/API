import json
from fastapi.responses import Response


class StringIntEncoder:
    @staticmethod
    def encode(s: str) -> int:
        b = s.encode()
        return int.from_bytes(b, byteorder='big')

    @staticmethod
    def decode(i: int) -> str:
        return i.to_bytes(((i.bit_length() + 7) // 8), byteorder='big').decode()
