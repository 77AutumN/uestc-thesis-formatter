"""P0 测试：验证 _is_structural_description() 过滤器和簇群检测。"""
import sys
import os

# Add scripts dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from pandoc_ast_extract import _is_structural_description, find_chapters


class TestStructuralDescription:
    """测试 _is_structural_description() 过滤器。"""

    # ===== 应该被过滤掉的（返回 True）=====

    def test_chapter_with_colon_description(self):
        """冒号 + 长描述 → True"""
        text = "第一章 绪论：阐述课题背景，梳理可靠性分析及多保真度代理模型的研究现状。"
        assert _is_structural_description(text) is True

    def test_chapter_with_colon_description_2(self):
        """冒号 + 长描述（第二章）→ True"""
        text = "第二章 圆柱齿轮参数化建模与多保真度有限元分析：基于 SolidWorks 建立参数化模型"
        assert _is_structural_description(text) is True

    def test_chapter_with_half_colon(self):
        """半角冒号也触发"""
        text = "第三章 基于单保真度代理模型的结构可靠性分析:推导 Kriging 模型机理，结合拉丁超立方抽样"
        assert _is_structural_description(text) is True

    def test_chapter_with_sentence_ending(self):
        """包含句号 → True"""
        text = "第五章 总结与展望：归纳创新成果，分析局限性并展望未来研究方向。"
        assert _is_structural_description(text) is True

    def test_chapter_with_period_in_title(self):
        """标题部分包含句号 → True"""
        text = "第四章 基于多保真度代理模型的结构可靠性分析。本章深入研究融合框架。"
        assert _is_structural_description(text) is True

    # ===== 不应该被过滤掉的（返回 False）=====

    def test_normal_short_chapter_title(self):
        """正常短标题 → False"""
        text = "第一章 绪论"
        assert _is_structural_description(text) is False

    def test_normal_medium_chapter_title(self):
        """正常中等长度标题 → False"""
        text = "第二章 圆柱齿轮参数化建模与多保真度仿真分析"
        assert _is_structural_description(text) is False

    def test_normal_long_title_no_punctuation(self):
        """较长标题但无正文标点 → False"""
        text = "第三章 基于单保真度代理模型的结构可靠性分析"
        assert _is_structural_description(text) is False

    def test_normal_conclusion(self):
        """结论章 → False"""
        text = "第五章 结论"
        assert _is_structural_description(text) is False

    def test_normal_title_with_parenthesis(self):
        """含括号但无正文标点 → False"""
        text = "第四章 基于多保真度代理模型(Co-Kriging)的结构可靠性分析"
        assert _is_structural_description(text) is False


class TestClusterDetection:
    """测试 find_chapters() 中的簇群检测逻辑。"""

    @staticmethod
    def _make_para_block(text, idx):
        """构造一个模拟的 Pandoc Para block。"""
        return {
            "t": "Para",
            "c": [{"t": "Str", "c": text}],
            "_test_idx": idx,
        }

    @staticmethod
    def _make_header_block(text, level=1):
        return {
            "t": "Header",
            "c": [level, ["", [], []], [{"t": "Str", "c": text}]],
        }

    def test_cluster_filtered_out(self):
        """连续 5 个不同章号在 10 个 block 内 → 全部被排除。"""
        blocks = [
            {"t": "Para", "c": [{"t": "Str", "c": "some body text"}]},  # 0
        ]
        # 正文中的真正章节标题
        blocks.append(self._make_para_block("第一章 绪论", len(blocks)))       # 1
        # body content for ch1
        for _ in range(20):
            blocks.append({"t": "Para", "c": [{"t": "Str", "c": "body"}]})
        # "论文结构安排" 的提纲段落（连续出现）
        outline_start = len(blocks)
        blocks.append(self._make_para_block("第一章 绪论", len(blocks)))        # ~22
        blocks.append(self._make_para_block("第二章 参数化建模", len(blocks)))   # ~23
        blocks.append(self._make_para_block("第三章 单保真度分析", len(blocks))) # ~24
        blocks.append(self._make_para_block("第四章 多保真度分析", len(blocks))) # ~25
        blocks.append(self._make_para_block("第五章 结论", len(blocks)))        # ~26
        # 正文中的真正第二章
        for _ in range(5):
            blocks.append({"t": "Para", "c": [{"t": "Str", "c": "gap"}]})
        blocks.append(self._make_para_block("第二章 参数化建模与仿真", len(blocks)))
        for _ in range(5):
            blocks.append({"t": "Para", "c": [{"t": "Str", "c": "gap"}]})
        blocks.append(self._make_para_block("第三章 单保真度代理模型分析", len(blocks)))
        for _ in range(5):
            blocks.append({"t": "Para", "c": [{"t": "Str", "c": "gap"}]})
        blocks.append(self._make_para_block("第四章 多保真度代理模型分析", len(blocks)))
        for _ in range(5):
            blocks.append({"t": "Para", "c": [{"t": "Str", "c": "gap"}]})
        blocks.append(self._make_para_block("第五章 结论与展望", len(blocks)))

        chapters = find_chapters(blocks)

        # 应该检测到 5 个章节，所有标题都应该来自真正的章节标题（分散的），
        # 而不是"论文结构安排"的连续簇
        assert len(chapters) == 5
        # 验证没有任何章节的 idx 落在簇群范围内
        for ch in chapters:
            assert ch["idx"] < outline_start or ch["idx"] > outline_start + 5, \
                f"Chapter {ch['raw_title']} at idx {ch['idx']} should not be from the cluster"

    def test_no_cluster_normal_chapters(self):
        """正常分散的章节标题不触发簇群检测。"""
        blocks = []
        blocks.append(self._make_para_block("第一章 绪论", len(blocks)))
        for _ in range(30):
            blocks.append({"t": "Para", "c": [{"t": "Str", "c": "body"}]})
        blocks.append(self._make_para_block("第二章 方法", len(blocks)))
        for _ in range(30):
            blocks.append({"t": "Para", "c": [{"t": "Str", "c": "body"}]})
        blocks.append(self._make_para_block("第三章 结论", len(blocks)))

        chapters = find_chapters(blocks)
        assert len(chapters) == 3


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
