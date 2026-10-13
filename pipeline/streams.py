from redis.exceptions import ResponseError

EXTRACT = "ingest.extract"
EMBED = "ingest.embed"
FINALIZE = "ingest.finalize"
DELETE = "docs.delete"
GROUPS = {EXTRACT: "extractors", EMBED: "embedders", FINALIZE: "finalizers", DELETE: "deleters"}
MAXLEN = 100_000


def dlq(stream: str) -> str:
    return f"{stream}.dlq"


async def ensure_groups(redis) -> None:
    for stream, group in GROUPS.items():
        try:
            await redis.xgroup_create(stream, group, id="0", mkstream=True)
        except ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise
