from plugins.astrbot_plugin_shuttleup.parser import parse


def test_parse_availability_and_activity_override():
    result=parse("/羽球 有空 2026-09-19 18:00-20:00 --个人 --活动 B6R2")
    assert result["command"]=="availability.set" and result["activity_code"]=="B6R2" and result["args"]["personal"]


def test_same_words_map_to_distinct_money_models():
    assert parse("/羽球 记账 球 4个")["args"]["kind"]=="球"
    assert parse("/羽球 记账 球费 48")["args"]["kind"]=="球费"

