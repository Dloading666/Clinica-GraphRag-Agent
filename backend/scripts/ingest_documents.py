"""Ingest all documents from knowledge base directory"""
import asyncio
import sys

sys.path.insert(0, "/app")

KNOWLEDGE_BASE_PATH = "/app/knowledge_base/医疗知识库"


async def main():
    from app.config.database import init_postgres, AsyncSessionLocal
    from app.services.ingestion_service import IngestionService

    await init_postgres()

    service = IngestionService()
    async with AsyncSessionLocal() as db:
        print(f"正在从 {KNOWLEDGE_BASE_PATH} 导入文档...")
        results = await service.ingest_directory(KNOWLEDGE_BASE_PATH, db, build_graph=False)
        for r in results:
            if "error" in r:
                print(f"  ❌ {r.get('filename')}: {r['error']}")
            else:
                print(f"  ✅ {r['filename']}: {r['chunks']} 个文本块")
        await db.commit()
    print("文档导入完成")


if __name__ == "__main__":
    asyncio.run(main())
