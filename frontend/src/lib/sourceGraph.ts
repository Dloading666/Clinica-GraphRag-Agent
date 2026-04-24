import type { KGData, KGLink, KGNode, SourceItem } from '../types'

function compact(value: string | undefined, fallback: string) {
  const text = (value || '').replace(/\s+/g, ' ').trim()
  return text || fallback
}

function parseRelation(item: SourceItem) {
  const idParts = item.id?.split(':') ?? []
  if (idParts.length >= 4 && idParts[0] === 'relation') {
    return {
      source: idParts[1],
      label: idParts[2],
      target: idParts.slice(3).join(':'),
    }
  }

  const match = item.title.match(/(.+?)\s*--\[(.+?)\]-->\s*(.+)/)
  if (!match) return null

  return {
    source: match[1].trim(),
    label: match[2].trim(),
    target: match[3].trim(),
  }
}

function parseCommunityId(item: SourceItem) {
  const idMatch = item.id?.match(/^community:(.+)$/)
  if (idMatch) return idMatch[1]

  const titleMatch = item.title.match(/(\d+)/)
  return titleMatch?.[1] ?? item.title
}

function entityNode(name: string, type = '相关实体', description = ''): KGNode {
  return {
    id: `entity:${name}`,
    label: name,
    type,
    size: 15,
    properties: { description },
  }
}

function addNode(
  nodes: KGNode[],
  nodeMap: Map<string, KGNode>,
  node: KGNode,
  limit: number
) {
  const existing = nodeMap.get(node.id)
  if (existing) {
    existing.size = Math.max(existing.size ?? 10, node.size ?? 10)
    existing.properties = { ...existing.properties, ...node.properties }
    return true
  }

  if (nodes.length >= limit) return false

  nodeMap.set(node.id, node)
  nodes.push(node)
  return true
}

function addLink(links: KGLink[], seen: Set<string>, link: KGLink) {
  const key = `${link.source}->${link.label}->${link.target}`
  if (seen.has(key)) return
  seen.add(key)
  links.push(link)
}

export function buildKgFromSourceItems(
  sourceItems: SourceItem[] | undefined,
  limit = 80
): KGData {
  const items = sourceItems ?? []
  const nodes: KGNode[] = []
  const links: KGLink[] = []
  const nodeMap = new Map<string, KGNode>()
  const seenLinks = new Set<string>()
  const communityIds: string[] = []
  const entityNames: string[] = []

  for (const item of items) {
    if (item.source_type === 'entity') {
      const name = compact(item.title, item.id.replace(/^entity:/, '实体'))
      entityNames.push(name)
      addNode(
        nodes,
        nodeMap,
        entityNode(name, item.entity_type || item.label || '相关实体', item.content),
        limit
      )
      continue
    }

    if (item.source_type === 'relation') {
      const relation = parseRelation(item)
      if (!relation) continue

      entityNames.push(relation.source, relation.target)
      const sourceAdded = addNode(
        nodes,
        nodeMap,
        entityNode(relation.source, '相关实体'),
        limit
      )
      const targetAdded = addNode(
        nodes,
        nodeMap,
        entityNode(relation.target, '相关实体'),
        limit
      )
      if (sourceAdded && targetAdded) {
        addLink(links, seenLinks, {
          source: `entity:${relation.source}`,
          target: `entity:${relation.target}`,
          label: relation.label,
          weight: 0.8,
        })
      }
      continue
    }

    if (item.source_type === 'community') {
      const communityId = parseCommunityId(item)
      communityIds.push(communityId)
      addNode(nodes, nodeMap, {
        id: `community:${communityId}`,
        label: `社区 ${communityId}`,
        type: '社区摘要',
        size: 19,
        properties: {
          description: item.content,
          community_id: communityId,
        },
      }, limit)
      continue
    }

    if (item.source_type === 'chunk') {
      const chunkId = item.id || `chunk:${nodes.length + 1}`
      const documentName = compact(item.document_name, '')
      addNode(nodes, nodeMap, {
        id: chunkId,
        label: compact(item.title, '文献片段').slice(0, 18),
        type: '文献片段',
        size: 13,
        properties: {
          description: item.content,
          document_name: documentName,
        },
      }, limit)

      if (documentName) {
        const docId = `document:${documentName}`
        if (addNode(nodes, nodeMap, {
          id: docId,
          label: documentName.replace(/\.(docx|pdf)$/i, '').slice(0, 16),
          type: '文档',
          size: 16,
          properties: { description: documentName },
        }, limit)) {
          addLink(links, seenLinks, {
            source: docId,
            target: chunkId,
            label: '包含',
            weight: 0.65,
          })
        }
      }
    }
  }

  const uniqueEntityNames = [...new Set(entityNames.filter(Boolean))]
  for (const item of items.filter((source) => source.source_type === 'community')) {
    const communityId = parseCommunityId(item)
    const communityNodeId = `community:${communityId}`
    let matched = 0

    for (const name of uniqueEntityNames) {
      if (matched >= 10) break
      if (!item.content.includes(name)) continue

      addLink(links, seenLinks, {
        source: communityNodeId,
        target: `entity:${name}`,
        label: '关联',
        weight: 0.45,
      })
      matched += 1
    }
  }

  return {
    nodes,
    links,
    meta: {
      mode: 'source_items',
      community_ids: [...new Set(communityIds)],
      source_entity_names: uniqueEntityNames,
      note: '当前回答证据子图',
    },
  }
}
