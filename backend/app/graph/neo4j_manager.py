"""Neo4j 临床知识图谱高级操作封装"""
from typing import List, Dict, Any, Optional

from app.config.database import neo4j_manager
from app.config.settings import settings


class ClinicalGraphManager:
    """封装 neo4j_manager，提供临床领域专用图谱操作"""

    # ──────────────────────────────────────────────
    # 索引 & 约束
    # ──────────────────────────────────────────────

    def create_indexes(self) -> None:
        """创建 Neo4j 全文索引（以及可选的向量索引）"""
        queries = [
            # 实体名称全文索引
            """
            CREATE FULLTEXT INDEX entity_name_fulltext IF NOT EXISTS
            FOR (n:__Entity__)
            ON EACH [n.name, n.description]
            """,
            # 实体名称精确索引
            "CREATE INDEX entity_name_idx IF NOT EXISTS FOR (n:__Entity__) ON (n.name)",
            # 社区 ID 索引
            "CREATE INDEX community_id_idx IF NOT EXISTS FOR (n:__Community__) ON (n.community_id)",
            # Chunk ID 索引
            "CREATE INDEX chunk_id_idx IF NOT EXISTS FOR (n:__Chunk__) ON (n.chunk_id)",
        ]
        for q in queries:
            try:
                neo4j_manager.execute_query(q.strip())
            except Exception as e:
                print(f"[Neo4j] 创建索引跳过（可能已存在）: {e}")

    # ──────────────────────────────────────────────
    # 实体 CRUD
    # ──────────────────────────────────────────────

    def upsert_entity(
        self,
        name: str,
        entity_type: str,
        description: str,
        pg_id: int,
        embedding: Optional[List[float]] = None,
    ) -> None:
        """在 Neo4j 中插入或更新实体节点（按 name + type 合并）"""
        query = """
        MERGE (e:__Entity__ {name: $name, entity_type: $entity_type})
        SET e.description = $description,
            e.pg_id = $pg_id,
            e.updated_at = timestamp()
        """
        params: Dict[str, Any] = {
            "name": name,
            "entity_type": entity_type,
            "description": description,
            "pg_id": pg_id,
        }
        if embedding is not None:
            query += "\nSET e.embedding = $embedding"
            params["embedding"] = embedding
        try:
            neo4j_manager.execute_query(query.strip(), params)
        except Exception as e:
            print(f"[Neo4j] upsert_entity 失败 ({name}): {e}")

    # ──────────────────────────────────────────────
    # 关系 CRUD
    # ──────────────────────────────────────────────

    def upsert_relationship(
        self,
        source_name: str,
        target_name: str,
        rel_type: str,
        description: str,
        weight: float,
    ) -> None:
        """在 Neo4j 中插入或更新关系（按 source + target + type 合并）"""
        # 关系类型必须是合法的 Neo4j 标识符，替换非法字符
        safe_rel_type = rel_type.strip().replace(" ", "_").replace("-", "_")
        query = f"""
        MATCH (s:__Entity__ {{name: $source}})
        MATCH (t:__Entity__ {{name: $target}})
        MERGE (s)-[r:RELATES {{rel_type: $rel_type}}]->(t)
        SET r.description = $description,
            r.weight = $weight,
            r.updated_at = timestamp()
        """
        try:
            neo4j_manager.execute_query(query.strip(), {
                "source": source_name,
                "target": target_name,
                "rel_type": rel_type,
                "description": description,
                "weight": weight,
            })
        except Exception as e:
            print(f"[Neo4j] upsert_relationship 失败 ({source_name} → {target_name}): {e}")

    # ──────────────────────────────────────────────
    # Leiden 社区检测（需要 Neo4j GDS）
    # ──────────────────────────────────────────────

    def run_leiden_community_detection(self) -> int:
        """
        使用 GDS Leiden 算法进行社区检测。
        1. 投影图
        2. 运行 Leiden
        3. 返回检测到的社区数量
        """
        graph_name = "clinicalGraph"

        # 先删除可能存在的旧投影
        try:
            neo4j_manager.execute_query(
                "CALL gds.graph.drop($graph_name, false) YIELD graphName",
                {"graph_name": graph_name},
            )
        except Exception:
            pass

        # 投影图：包含 __Entity__ 节点和 RELATES 关系
        project_query = """
        CALL gds.graph.project(
            $graph_name,
            '__Entity__',
            {
                RELATES: {
                    orientation: 'UNDIRECTED',
                    properties: { weight: { property: 'weight', defaultValue: 0.5 } }
                }
            }
        ) YIELD graphName, nodeCount, relationshipCount
        RETURN nodeCount, relationshipCount
        """
        try:
            neo4j_manager.execute_query(project_query.strip(), {"graph_name": graph_name})
        except Exception as e:
            print(f"[Neo4j GDS] 图投影失败: {e}")
            return 0

        # 运行 Leiden 写回
        leiden_query = """
        CALL gds.leiden.write(
            $graph_name,
            {
                writeProperty: 'communityId',
                includeIntermediateCommunities: false,
                maxLevels: 10,
                tolerance: 0.0001,
                gamma: 1.0,
                theta: 0.01,
                randomSeed: 42
            }
        ) YIELD communityCount, modularity
        RETURN communityCount
        """
        try:
            result = neo4j_manager.execute_query(leiden_query.strip(), {"graph_name": graph_name})
            if result:
                count = result[0].get("communityCount", 0)
                return int(count)
        except Exception as e:
            print(f"[Neo4j GDS] Leiden 算法失败: {e}")
        finally:
            # 清理投影
            try:
                neo4j_manager.execute_query(
                    "CALL gds.graph.drop($graph_name, false) YIELD graphName",
                    {"graph_name": graph_name},
                )
            except Exception:
                pass
        return 0

    # ──────────────────────────────────────────────
    # 社区操作
    # ──────────────────────────────────────────────

    def get_community_members(self, community_id: int) -> List[Dict]:
        """获取指定社区的所有实体节点"""
        query = """
        MATCH (e:__Entity__)
        WHERE e.communityId = $community_id
        RETURN e.name AS name, e.entity_type AS entity_type,
               e.description AS description, e.pg_id AS pg_id
        """
        try:
            results = neo4j_manager.execute_query(query, {"community_id": community_id})
            return results
        except Exception as e:
            print(f"[Neo4j] get_community_members 失败: {e}")
            return []

    def write_community_summary(
        self,
        community_id: str,
        summary: str,
        level: int,
        rank: float,
    ) -> None:
        """写入社区摘要节点"""
        query = """
        MERGE (c:__Community__ {community_id: $community_id})
        SET c.summary = $summary,
            c.level = $level,
            c.rank = $rank,
            c.updated_at = timestamp()
        """
        try:
            neo4j_manager.execute_query(query, {
                "community_id": str(community_id),
                "summary": summary,
                "level": level,
                "rank": rank,
            })
        except Exception as e:
            print(f"[Neo4j] write_community_summary 失败: {e}")

    def get_communities_by_level(self, level: int) -> List[Dict]:
        """获取指定层级的所有社区"""
        query = """
        MATCH (c:__Community__)
        WHERE c.level = $level
        RETURN c.community_id AS community_id, c.summary AS summary,
               c.rank AS rank, c.level AS level
        ORDER BY c.rank DESC
        """
        try:
            results = neo4j_manager.execute_query(query, {"level": level})
            return [dict(r) for r in results]
        except Exception as e:
            print(f"[Neo4j] get_communities_by_level 失败: {e}")
            return []

    def get_all_community_ids(self) -> List[int]:
        """获取所有不重复的社区 ID"""
        query = """
        MATCH (e:__Entity__)
        WHERE e.communityId IS NOT NULL
        RETURN DISTINCT e.communityId AS community_id
        ORDER BY community_id
        """
        try:
            results = neo4j_manager.execute_query(query)
            return [r["community_id"] for r in results]
        except Exception as e:
            print(f"[Neo4j] get_all_community_ids 失败: {e}")
            return []

    def get_community_relationships(self, community_id: int) -> List[Dict]:
        """获取社区内实体间的关系"""
        query = """
        MATCH (s:__Entity__)-[r:RELATES]->(t:__Entity__)
        WHERE s.communityId = $community_id AND t.communityId = $community_id
        RETURN s.name AS source, t.name AS target,
               r.rel_type AS rel_type, r.description AS description,
               r.weight AS weight
        LIMIT 100
        """
        try:
            results = neo4j_manager.execute_query(query, {"community_id": community_id})
            return [dict(r) for r in results]
        except Exception as e:
            print(f"[Neo4j] get_community_relationships 失败: {e}")
            return []

    # ──────────────────────────────────────────────
    # 图谱扩展（Local Search 核心）
    # ──────────────────────────────────────────────

    def graph_expansion(
        self,
        entity_names: List[str],
        top_chunks: int = 3,
        top_communities: int = 3,
        top_inside_rels: int = 10,
        top_outside_rels: int = 10,
    ) -> Dict:
        """
        给定实体名称列表，返回图谱扩展上下文：
        - entities: 找到的实体信息
        - inside_rels: 社区内部关系
        - outside_rels: 社区外部关系
        - communities: 相关社区摘要
        - chunks: （占位，通过 PG 向量搜索获取）
        """
        if not entity_names:
            return {"entities": [], "inside_rels": [], "outside_rels": [], "communities": [], "chunks": []}

        # 获取实体详情及其社区 ID
        entity_query = """
        MATCH (e:__Entity__)
        WHERE e.name IN $names
        RETURN e.name AS name, e.entity_type AS entity_type,
               e.description AS description, e.communityId AS community_id
        """
        entities = []
        community_ids = set()
        try:
            results = neo4j_manager.execute_query(entity_query, {"names": entity_names})
            for r in results:
                entities.append(dict(r))
                if r.get("community_id") is not None:
                    community_ids.add(r["community_id"])
        except Exception as e:
            print(f"[Neo4j] graph_expansion entity query 失败: {e}")

        # 社区内部关系
        inside_rels = []
        if entity_names:
            inside_query = """
            MATCH (s:__Entity__)-[r:RELATES]->(t:__Entity__)
            WHERE s.name IN $names AND t.name IN $names
            RETURN s.name AS source, t.name AS target,
                   r.rel_type AS rel_type, r.description AS description,
                   r.weight AS weight
            ORDER BY r.weight DESC
            LIMIT $limit
            """
            try:
                results = neo4j_manager.execute_query(inside_query, {
                    "names": entity_names,
                    "limit": top_inside_rels,
                })
                inside_rels = [dict(r) for r in results]
            except Exception as e:
                print(f"[Neo4j] graph_expansion inside_rels 失败: {e}")

        # 社区外部关系（单跳邻居）
        outside_rels = []
        if entity_names:
            outside_query = """
            MATCH (s:__Entity__)-[r:RELATES]->(t:__Entity__)
            WHERE s.name IN $names AND NOT t.name IN $names
            RETURN s.name AS source, t.name AS target,
                   r.rel_type AS rel_type, r.description AS description,
                   r.weight AS weight
            ORDER BY r.weight DESC
            LIMIT $limit
            """
            try:
                results = neo4j_manager.execute_query(outside_query, {
                    "names": entity_names,
                    "limit": top_outside_rels,
                })
                outside_rels = [dict(r) for r in results]
            except Exception as e:
                print(f"[Neo4j] graph_expansion outside_rels 失败: {e}")

        # 相关社区摘要
        communities = []
        if community_ids:
            comm_query = """
            MATCH (c:__Community__)
            WHERE c.community_id IN $cids
            RETURN c.community_id AS community_id, c.summary AS summary,
                   c.level AS level, c.rank AS rank
            ORDER BY c.rank DESC
            LIMIT $limit
            """
            try:
                results = neo4j_manager.execute_query(comm_query, {
                    "cids": [str(cid) for cid in community_ids],
                    "limit": top_communities,
                })
                communities = [dict(r) for r in results]
            except Exception as e:
                print(f"[Neo4j] graph_expansion communities 失败: {e}")

        return {
            "entities": entities,
            "inside_rels": inside_rels,
            "outside_rels": outside_rels,
            "communities": communities,
            "chunks": [],  # 由 local_search.py 通过 PG 向量搜索填充
        }

    # ──────────────────────────────────────────────
    # 实体邻居 & 路径查询
    # ──────────────────────────────────────────────

    def get_entity_relationships(
        self, entity_name: str, max_depth: int = 2
    ) -> Dict:
        """获取实体的多跳邻居和关系（用于可视化）"""
        query = f"""
        MATCH path = (e:__Entity__ {{name: $name}})-[r:RELATES*1..{max_depth}]-(neighbor:__Entity__)
        RETURN e.name AS source, neighbor.name AS target,
               [rel in relationships(path) | rel.rel_type] AS rel_types,
               [rel in relationships(path) | rel.description] AS descriptions,
               length(path) AS depth
        LIMIT 50
        """
        try:
            results = neo4j_manager.execute_query(query, {"name": entity_name})
            return {"relationships": [dict(r) for r in results]}
        except Exception as e:
            print(f"[Neo4j] get_entity_relationships 失败: {e}")
            return {"relationships": []}

    def find_shortest_path(self, entity_a: str, entity_b: str) -> List[Dict]:
        """查找两个实体间的最短路径"""
        query = """
        MATCH (a:__Entity__ {name: $name_a}), (b:__Entity__ {name: $name_b})
        MATCH path = shortestPath((a)-[r:RELATES*]-(b))
        RETURN [n in nodes(path) | n.name] AS node_names,
               [rel in relationships(path) | rel.rel_type] AS rel_types,
               length(path) AS path_length
        """
        try:
            results = neo4j_manager.execute_query(query, {
                "name_a": entity_a,
                "name_b": entity_b,
            })
            return [dict(r) for r in results]
        except Exception as e:
            print(f"[Neo4j] find_shortest_path 失败: {e}")
            return []

    # ──────────────────────────────────────────────
    # 可视化数据
    # ──────────────────────────────────────────────

    def get_knowledge_graph_for_query(
        self, entity_names: List[str], limit: int = 50
    ) -> Dict:
        """获取用于前端可视化的节点和关系数据"""
        if not entity_names:
            return {"nodes": [], "links": []}

        nodes_query = """
        MATCH (e:__Entity__)
        WHERE e.name IN $names
        OPTIONAL MATCH (e)-[r:RELATES]-(neighbor:__Entity__)
        WHERE neighbor.name IN $names
        RETURN DISTINCT e.name AS name, e.entity_type AS entity_type,
               e.description AS description
        LIMIT $limit
        """
        links_query = """
        MATCH (s:__Entity__)-[r:RELATES]->(t:__Entity__)
        WHERE s.name IN $names AND t.name IN $names
        RETURN s.name AS source, t.name AS target,
               r.rel_type AS rel_type, r.weight AS weight
        LIMIT $limit
        """
        nodes, links = [], []
        try:
            results = neo4j_manager.execute_query(nodes_query, {
                "names": entity_names, "limit": limit
            })
            nodes = [dict(r) for r in results]

            results = neo4j_manager.execute_query(links_query, {
                "names": entity_names, "limit": limit
            })
            links = [dict(r) for r in results]
        except Exception as e:
            print(f"[Neo4j] get_knowledge_graph_for_query 失败: {e}")

        return {"nodes": nodes, "links": links}


# 全局单例
clinical_graph_manager = ClinicalGraphManager()
