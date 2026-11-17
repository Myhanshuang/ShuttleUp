from plugins.astrbot_plugin_shuttleup.parser import parse


def test_parse_availability_and_activity_override():
    result=parse("/羽球 有空 2026-09-19 18:00-20:00 --个人 --活动 B6R2")
    assert result["command"]=="availability.set" and result["activity_code"]=="B6R2" and result["args"]["personal"]


def test_same_words_map_to_distinct_money_models():
    assert parse("/羽球 记账 球 4个")["args"]["kind"]=="球"
    assert parse("/羽球 记账 球费 48")["args"]["kind"]=="球费"



def test_public_create_entry_and_workflow_commands():
    assert parse('/发起约球 周末 夜场')['args']['title'] == '周末 夜场'
    assert parse('/羽球 发起约球')['command'] == 'activity.create'
    assert parse('/羽球 选择 2')['args']['index'] == 2
    assert parse('/羽球 已订 1号场 ORDER')['args'] == {'court': '1号场', 'order': 'ORDER'}
    assert parse('/羽球 网页')['command'] == 'web.open'


def test_cancel_requires_reason():
    import pytest
    with pytest.raises(ValueError):
        parse('/羽球 取消')


def test_bind_qq_identity_command():
    assert parse('/绑定身份 小林')['args'] == {'display_name': '小林'}
    assert parse('/羽球 绑定身份')['command'] == 'identity.create'
    assert parse('/绑定身份')['args'] == {'display_name': None}
