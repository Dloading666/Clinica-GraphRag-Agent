"""中文医学文本分块器（基于 jieba 分词）"""
import re
from typing import List

import jieba

from app.config.settings import settings


class MedicalTextChunker:
    """基于句子边界的中文医学文本分块器"""

    def __init__(self):
        self.chunk_size = settings.chunk.chunk_size
        self.overlap = settings.chunk.chunk_overlap
        # 句子结束符正则（保留标点）
        self._sentence_pattern = re.compile(r'([^。！？!?…]+[。！？!?…]+)', re.DOTALL)

    # ──────────────────────────────────────────────
    # 公共接口
    # ──────────────────────────────────────────────

    def chunk_text(self, text: str) -> List[str]:
        """
        将文本切分为带重叠的语义块：
        1. 先按句子边界切分
        2. 累积句子直到达到 chunk_size
        3. 使用前一块末尾 overlap 字符作为重叠
        返回文本字符串列表。
        """
        if not text or not text.strip():
            return []

        sentences = self._split_sentences(text)
        if not sentences:
            return [text[:self.chunk_size]]

        chunks: List[str] = []
        current_sentences: List[str] = []
        current_len = 0

        for sentence in sentences:
            s_len = len(sentence)

            # 单句超过 chunk_size，强制按字符切分
            if s_len > self.chunk_size:
                # 先保存已有内容
                if current_sentences:
                    chunks.append("".join(current_sentences))
                    current_sentences = []
                    current_len = 0
                # 切分超长句
                for sub in self._split_long_sentence(sentence):
                    chunks.append(sub)
                continue

            if current_len + s_len > self.chunk_size and current_sentences:
                # 当前块已满，保存并计算重叠
                chunk_text_str = "".join(current_sentences)
                chunks.append(chunk_text_str)

                # 计算重叠：从末尾取 overlap 字符对应的句子
                overlap_text = chunk_text_str[-self.overlap:] if self.overlap > 0 else ""
                current_sentences = [overlap_text] if overlap_text else []
                current_len = len(overlap_text)

            current_sentences.append(sentence)
            current_len += s_len

        # 最后一块
        if current_sentences:
            last = "".join(current_sentences)
            if last.strip():
                chunks.append(last)

        return [c for c in chunks if c.strip()]

    def chunk_with_metadata(
        self,
        text: str,
        chapter: str = "",
        section: str = "",
    ) -> List[dict]:
        """
        返回带元数据的块列表，每个元素包含：
        - content: 文本内容
        - chapter: 一级标题
        - section: 二级标题
        - chunk_index: 块序号（从 0 开始）
        """
        chunks = self.chunk_text(text)
        return [
            {
                "content": chunk,
                "chapter": chapter,
                "section": section,
                "chunk_index": idx,
            }
            for idx, chunk in enumerate(chunks)
        ]

    # ──────────────────────────────────────────────
    # 私有方法
    # ──────────────────────────────────────────────

    def _split_sentences(self, text: str) -> List[str]:
        """按中文句子边界切分文本，保留标点符号"""
        # 匹配以句号、感叹号、问号结尾的句子
        sentences = self._sentence_pattern.findall(text)

        # 处理末尾没有标点的内容
        matched = "".join(sentences)
        remainder = text[len(matched):].strip()
        if remainder:
            sentences.append(remainder)

        # 过滤空字符串
        return [s for s in sentences if s.strip()]

    def _split_long_sentence(self, sentence: str) -> List[str]:
        """将超长句子按 chunk_size 强制切分（字符级别）"""
        result = []
        start = 0
        while start < len(sentence):
            end = start + self.chunk_size
            result.append(sentence[start:end])
            start = end - self.overlap if self.overlap > 0 else end
        return [s for s in result if s.strip()]
