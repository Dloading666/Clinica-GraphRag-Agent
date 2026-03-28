"""Build knowledge graph from ingested documents"""
import asyncio
import sys

sys.path.insert(0, "/app")


async def main():
    from app.config.database import init_postgres, AsyncSessionLocal
    from app.graph.graph_builder import GraphBuilder

    await init_postgres()

    builder = GraphBuilder()
    async with AsyncSessionLocal() as db:
        print("正在构建知识图谱...")
        print("第1步: 实体和关系抽取...")
        stats = await builder.build_from_documents(db)
        await db.commit()
        print(f"图谱构建完成: {stats}")

        print("第2步: 运行社区发现...")
        communities = await builder.rebuild_communities(db)
        await db.commit()
        print(f"社区检测完成: {communities} 个社区")


if __name__ == "__main__":
    asyncio.run(main())
