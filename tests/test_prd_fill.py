"""PRD 第 2–5 节的整理（blueprint/prd_fill.py）：只写模板或之前自动写过的小节，反复写不走样。"""
import json

from blueprint.forward import run_plan
from blueprint.mock import MockRunner
from blueprint.prd_fill import MARK, fill_prd, fillable_sections
from blueprint.workspace import init_workspace, read_prd, revise_workspace

quiet = lambda _m: None  # noqa: E731


def _ws(tmp_path):
    ws = init_workspace(tmp_path, "烘焙助手", "### 一句话想法\n\n在微信上帮社区烘焙店回答顾客问题")
    plan, _ = run_plan(read_prd(ws), MockRunner(), ws, log=quiet)
    return ws, plan.to_dict()


def test_fills_template_sections_and_tags_new_requirements(tmp_path):
    ws, plan = _ws(tmp_path)
    assert fillable_sections(read_prd(ws)) == ["breakdown", "features", "boundaries", "metrics"]
    assert fill_prd(ws, plan, MockRunner(), log=quiet) == ["breakdown", "features", "boundaries", "metrics"]
    revise_workspace(ws, "每晚 9 点发小结", MockRunner(), log=quiet)
    fill_prd(ws, json.loads((ws / "plan.json").read_text(encoding="utf-8")), MockRunner(), log=quiet)
    prd = read_prd(ws)
    features = prd.split("## 3. 功能需求", 1)[1].split("\n## ", 1)[0]
    assert "FR1（V1）在微信上帮社区烘焙店回答顾客问题" in features and "FR2（V2 新增）每晚 9 点发小结" in features
    assert prd.count(MARK) == 4                                    # 四节都有标记，下次推导可以重新整理


def test_refilling_is_stable(tmp_path):
    ws, plan = _ws(tmp_path)
    fill_prd(ws, plan, MockRunner(), log=quiet)
    once = read_prd(ws)
    fill_prd(ws, plan, MockRunner(), log=quiet)
    assert read_prd(ws) == once and "\n\n\n" not in once


def test_never_overwrites_sections_written_by_people(tmp_path):
    ws, plan = _ws(tmp_path)
    prd = read_prd(ws).replace("## 4. 边界与红线\n", "## 4. 边界与红线\n\n- 绝不替店主答应打折（店主亲手写的）\n", 1)
    (ws / "PRD.md").write_text(prd, encoding="utf-8")
    written = fill_prd(ws, plan, MockRunner(), log=quiet)
    assert "boundaries" not in written and "绝不替店主答应打折（店主亲手写的）" in read_prd(ws)


def test_nothing_to_fill_means_no_model_call(tmp_path):
    ws, plan = _ws(tmp_path)
    prd = read_prd(ws)
    for h in ("## 2. 需求拆解", "## 3. 功能需求", "## 4. 边界与红线", "## 5. 成功指标（可度量）"):
        prd = prd.replace(h, h + "\n\n人写的内容", 1)
    prd = prd.replace("（由 AI 按 BLUEPRINT.md Step 1 填写", "（旧说明", 1)
    (ws / "PRD.md").write_text(prd, encoding="utf-8")

    class Boom:
        name = "anthropic"

        def complete(self, *a, **k):
            raise AssertionError("不该调模型")

    assert fill_prd(ws, plan, Boom(), log=quiet) == []


def test_auto_sections_are_output_not_input(tmp_path):
    """自动整理的小节不能回流到推导：否则里面的「待确认」会被再拆成问题，一轮比一轮多。"""
    from blueprint.workspace import strip_auto_sections
    ws, plan = _ws(tmp_path)
    before = read_prd(ws)
    fill_prd(ws, plan, MockRunner(), log=quiet)
    after = read_prd(ws)
    assert after != before and strip_auto_sections(after).count("## ") == before.count("## ")
    assert MARK not in strip_auto_sections(after) and "FR1（V1）" not in strip_auto_sections(after)
    # 填完再推导：需求拆解的输入和缓存与没填之前一样
    run_plan(after, MockRunner(), ws, resume=True, log=quiet)
    from blueprint.workspace import derivation_text
    assert (ws / "input.md").read_text(encoding="utf-8") == derivation_text(after) == derivation_text(before)
    assert strip_auto_sections(before) == before
