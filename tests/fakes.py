"""Test doubles shared by unit tests."""


class RecordingRedis:
    """Records XACKs; enough for Consumer.handle unit tests."""

    def __init__(self):
        self.acks: list[tuple[str, str, str]] = []

    async def xack(self, stream, group, message_id):
        self.acks.append((stream, group, message_id))
        return 1
