"""对话的步骤推算（blueprint/chat.py）与回答写回 PRD（workspace.record_answers），不经过 HTTP。"""
from blueprint.chat import HELP, SAVE, SKIP, Message, answer_state
from blueprint.workspace import ANSWERS_HEADING, init_workspace, read_prd, record_answers

QS = ["孩子多大？", "做成小程序还是 App？", "照片要不要保存？"]


def conv(*turns):
    return [Message(role, text) for role, text in turns]


def test_answer_state_counts_answers_skips_and_ignores_help():
    index, answers, action = answer_state(QS, conv(
        ("assistant", "第 1 题"), ("user", "6 岁"),
        ("assistant", "第 2 题"), ("user", HELP),
        ("assistant", "A. 小程序，上手快\nB. App，功能全"), ("user", "A"),
        ("assistant", "第 3 题"), ("user", SKIP),
    ))
    assert index == 3 and action == "skip"
    assert answers == {0: "6 岁", 1: "小程序，上手快"}


def test_answer_state_keeps_free_text_that_starts_with_a_letter():
    _i, answers, _a = answer_state(QS, conv(("assistant", "A. 甲\nB. 乙"), ("user", "B 方案但要改一下")))
    assert answers == {0: "B 方案但要改一下"}


def test_answer_state_save_stops_early():
    index, answers, action = answer_state(QS, conv(("user", "6 岁"), ("user", SAVE)))
    assert (index, action) == (1, "save") and answers == {0: "6 岁"}


def test_record_answers_goes_before_next_section_and_appends_on_repeat(tmp_path):
    ws = init_workspace(tmp_path, "邮件助手", "整理邮件")
    record_answers(ws, [("给谁用？", "我自己\n每天早上")])
    record_answers(ws, [("几点运行？", "早上 8 点")])
    prd = read_prd(ws)
    section = prd.split(ANSWERS_HEADING, 1)[1].split("\n## ", 1)[0]
    assert section.index("给谁用？") < section.index("几点运行？")
    assert "**答**：我自己 每天早上" in section                    # 多行回答压成一行，不破坏列表
    assert prd.index(ANSWERS_HEADING) < prd.index("## 7. 新增需求")


def test_record_answers_adds_section_when_ai_rewrote_prd(tmp_path):
    ws = init_workspace(tmp_path, "邮件助手", "整理邮件")
    (ws / "PRD.md").write_text("# PRD\n\n| 当前版本 | V2 |\n\n正文\n", encoding="utf-8")
    record_answers(ws, [("给谁用？", "我自己")])
    assert read_prd(ws).rstrip().endswith("**答**：我自己")


def test_anthropic_chat_streams_text_and_records_budget():
    """真实模型路径：用假客户端验证流式文字、费用记录和 JSON 整理都走引擎原有的 Runner。"""
    from types import SimpleNamespace

    from blueprint.chat import AnthropicChat
    from blueprint.llm import AnthropicRunner, Budget

    class FakeStream:
        text_stream = iter(["你好，", "说说看"])

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get_final_message(self):
            return SimpleNamespace(usage=SimpleNamespace(input_tokens=30, output_tokens=8))

    calls = []

    class FakeMessages:
        def stream(self, **kwargs):
            calls.append(kwargs)
            return FakeStream()

        def create(self, **kwargs):
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text='{"name": "邮件助手", "idea": "整理邮件"}')],
                stop_reason="end_turn", usage=SimpleNamespace(input_tokens=50, output_tokens=20))

    runner = AnthropicRunner(model="m", budget=Budget(max_calls=4), client=SimpleNamespace(messages=FakeMessages()))
    model = AnthropicChat(runner)
    assert "".join(model.stream("问题")) == "你好，说说看"
    assert calls[0]["system"].startswith("你是「Agent Blueprint」的需求访谈助手")
    assert runner.budget.calls == 1 and runner.budget.output_tokens == 8
    from blueprint.chat import SUMMARIZE_SCHEMA
    assert model.complete_json("chat_summarize", "对话", SUMMARIZE_SCHEMA) == {"name": "邮件助手", "idea": "整理邮件"}
    assert runner.budget.calls == 2
