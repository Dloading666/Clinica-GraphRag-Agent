"""Initialize database: create tables and pgvector extension"""
import asyncio
import sys

sys.path.insert(0, "/app")  # for Docker


async def main():
    from app.config.database import init_postgres

    print("正在创建数据库表...")
    await init_postgres()
    print("数据库初始化完成")


if __name__ == "__main__":
    asyncio.run(main())
