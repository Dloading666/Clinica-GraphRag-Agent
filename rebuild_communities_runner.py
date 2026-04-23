import asyncio

from app.config.database import AsyncSessionLocal
from app.graph.graph_builder import GraphBuilder


async def main() -> None:
    async with AsyncSessionLocal() as db:
        count = await GraphBuilder().rebuild_communities(db)
        print({'communities_created': count})


if __name__ == '__main__':
    asyncio.run(main())
